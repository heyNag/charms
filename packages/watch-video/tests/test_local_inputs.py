"""Local video/folder inputs pair supplied TXT evidence without enabling uploads."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import network_guard  # noqa: E402
import watch  # noqa: E402
from groq_transcribe import TranscriptionSegments  # noqa: E402


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


class LocalInputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.inputs = self.root / "meetings"
        self.inputs.mkdir()
        self.out = self.root / "runs"
        self.enterContext(mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "test-placeholder-groq",
            "OPENAI_API_KEY": "test-placeholder-openai",
            "GEMINI_API_KEY": "test-placeholder-gemini",
            "WATCH_VIDEO_CONFIG_DIR": str(self.root / "unused-config"),
        }, clear=True))
        self.enterContext(mock.patch.object(
            watch, "run_command", side_effect=AssertionError("unexpected subprocess"),
        ))
        self.probe_result = {
            "duration_seconds": 120.0, "width": 1280, "height": 720,
            "has_audio": True,
        }
        self.probe = self.enterContext(mock.patch.object(
            watch, "ffprobe_metadata", return_value=self.probe_result,
        ))
        self.url_probe = self.enterContext(mock.patch.object(
            watch, "probe_url", side_effect=AssertionError("unexpected URL probe"),
        ))
        self.download = self.enterContext(mock.patch.object(
            watch, "download_media", side_effect=AssertionError("unexpected download"),
        ))
        self.frames = self.enterContext(mock.patch.object(
            watch, "extract_scene_frames", return_value=([], {}),
        ))

        def extract_audio(_source, target, **_kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic audio fixture")
            return target

        self.audio = self.enterContext(mock.patch.object(
            watch, "extract_audio_clip", side_effect=extract_audio,
        ))
        self.transcribe = self.enterContext(mock.patch.object(
            watch, "transcribe_with_chunking", return_value=(
                TranscriptionSegments([
                    {"start": 0.0, "end": 2.0, "text": "fresh audio evidence"},
                ]), [],
            ),
        ))
        self.gemini = self.enterContext(mock.patch.object(
            watch.gemini, "analyze_video", side_effect=AssertionError("unexpected Gemini upload"),
        ))

    def video(self, relative="meeting.mp4"):
        path = self.inputs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic video fixture, never decoded or uploaded")
        return path

    def run_watch(self, source, *flags, out=None):
        output = out or self.out
        with mock.patch.object(sys, "argv", [
            "watch.py", str(source), "--out-dir", str(output), *flags,
        ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main()
        return code, next(output.iterdir())

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_no_cloud(self):
        self.transcribe.assert_not_called()
        self.gemini.assert_not_called()
        self.url_probe.assert_not_called()
        self.download.assert_not_called()

    def test_video_discovers_only_exact_matching_txt_and_preserves_primary_provenance(self):
        video = self.video()
        sidecar = video.with_suffix(".txt")
        sidecar.write_text("Original untimed supporting text.\n", encoding="utf-8")
        video.with_name("meeting-other.txt").write_text("Wrong meeting.", encoding="utf-8")
        video.with_name("meeting_notes.txt").write_text("Unrelated notes.", encoding="utf-8")

        code, run = self.run_watch(video)

        self.assertEqual(code, 0)
        supporting = self.read_json(run / "supporting_transcripts.json")
        self.assertEqual(len(supporting["sources"]), 1)
        source = supporting["sources"][0]
        self.assertEqual(source["path"], str(sidecar))
        self.assertEqual(source["text"], "Original untimed supporting text.\n")
        self.assertEqual(source["timestamps"], "unavailable")
        self.assertEqual(source["role"], "supporting")
        self.assertEqual(source["provenance"], "supplied_transcript")
        self.assertTrue(all("start" not in block for block in source["blocks"]))
        self.assertEqual(self.read_json(run / "transcript.json")["source"], "none")
        for filename in ("metadata.json", "evidence.json"):
            metadata = self.read_json(run / filename)
            summary = metadata["supporting_transcripts"]
            self.assertEqual(summary["count"], 1)
            self.assertEqual(Path(summary["path"]), run / "supporting_transcripts.json")
            self.assertEqual(summary["sources"][0]["content_hash"], source["content_hash"])
            self.assertNotIn("text", summary["sources"][0])
            self.assertNotIn("blocks", summary["sources"][0])
        self.assertIn("supporting_transcripts.json", (run / "report.md").read_text())
        self.audio.assert_not_called()
        self.assert_no_cloud()

    def test_grouped_and_plain_exports_remain_separate_with_only_supplied_start_times(self):
        video = self.video("screen capture.mp4")
        (video.parent / f"{video.stem}_transcript.txt").write_text("Unaligned text.")
        grouped = video.parent / f"{video.stem}_transcript_grouped.txt"
        grouped.write_text(
            "[00:00:03] Alex: First paragraph.\nContinued line.\n\n"
            "[00:01:23] Sam: Second paragraph.\n", encoding="utf-8",
        )

        code, run = self.run_watch(video, "--detail", "transcript")

        self.assertEqual(code, 0)
        sources = self.read_json(run / "supporting_transcripts.json")["sources"]
        self.assertEqual(len(sources), 2)
        timed = next(source for source in sources if source["path"] == str(grouped))
        self.assertEqual(timed["timestamps"], "block_start")
        self.assertEqual([block["start"] for block in timed["blocks"]], [3.0, 83.0])
        self.assertEqual([block["speaker"] for block in timed["blocks"]], ["Alex", "Sam"])
        self.assertIn("Continued line.", timed["blocks"][0]["text"])
        self.assertTrue(all("end" not in block for block in timed["blocks"]))
        self.assertEqual(self.read_json(run / "transcript.json")["source"], "none")
        self.frames.assert_not_called()
        self.assert_no_cloud()

    def test_supplied_txt_does_not_skip_explicit_audio_transcription(self):
        video = self.video()
        video.with_suffix(".txt").write_text(
            "[00:00:00] Alex: Supplied speech.\n[00:01:59] Alex: Still supplied.\n",
        )

        code, run = self.run_watch(video, "--detail", "transcript", "--transcriber", "groq")

        self.assertEqual(code, 0)
        self.audio.assert_called_once()
        self.transcribe.assert_called_once()
        self.assertEqual(self.transcribe.call_args.kwargs["provider"], "groq")
        transcript = self.read_json(run / "transcript.json")
        self.assertEqual(transcript["source"], "groq_whisper")
        self.assertEqual(transcript["segments"][0]["text"], "fresh audio evidence")
        self.assertEqual(len(self.read_json(run / "supporting_transcripts.json")["sources"]), 1)
        self.gemini.assert_not_called()

    def test_video_keeps_srt_and_txt_with_explicit_srt_intervals_in_source_order(self):
        video = self.video()
        txt = video.with_suffix(".txt")
        txt.write_text("Separate supporting prose.")
        srt = video.with_suffix(".srt")
        srt.write_text(
            "1\n00:01:23,125 --> 00:01:25,500\nLater cue listed first.\n\n"
            "2\n00:00:03,250 --> 00:00:04,750\nEarlier cue listed second.\n",
            encoding="utf-8",
        )

        code, run = self.run_watch(video)

        self.assertEqual(code, 0)
        sources = self.read_json(run / "supporting_transcripts.json")["sources"]
        self.assertEqual({source["path"] for source in sources}, {str(txt), str(srt)})
        timed = next(source for source in sources if source["path"] == str(srt))
        self.assertEqual(timed["role"], "supporting")
        self.assertEqual(timed["provenance"], "supplied_transcript")
        self.assertEqual(
            [(block["start"], block["end"]) for block in timed["blocks"]],
            [(83.125, 85.5), (3.25, 4.75)],
        )
        self.assertEqual(timed["text"], srt.read_text())
        metadata = self.read_json(run / "metadata.json")
        self.assertEqual(metadata["supporting_transcripts"]["count"], 2)
        self.assertEqual(metadata["transcriber"], "none")
        self.audio.assert_not_called()
        self.assert_no_cloud()

    def test_complete_local_srt_does_not_skip_explicit_audio_verification(self):
        video = self.video()
        srt = video.with_suffix(".srt")
        srt.write_text(
            "1\n00:00:00,000 --> 00:02:00,000\nSupplied text covering the whole recording.\n",
            encoding="utf-8",
        )
        # This would satisfy the ordinary caption coverage shortcut.
        self.assertFalse(watch.captions_are_insufficient(watch.parse_vtt(srt), 120.0))

        code, run = self.run_watch(video, "--detail", "transcript", "--transcriber", "groq")

        self.assertEqual(code, 0)
        self.audio.assert_called_once()
        self.transcribe.assert_called_once()
        self.assertEqual(self.transcribe.call_args.kwargs["provider"], "groq")
        primary = self.read_json(run / "transcript.json")
        self.assertEqual(primary["source"], "groq_whisper")
        self.assertEqual(primary["segments"][0]["text"], "fresh audio evidence")
        sources = self.read_json(run / "supporting_transcripts.json")["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["path"], str(srt))
        self.assertEqual(sources[0]["blocks"][0]["end"], 120.0)
        self.gemini.assert_not_called()

    def test_cleanup_retains_supporting_artifact_and_original_files(self):
        video = self.video()
        sidecar = video.with_suffix(".txt")
        sidecar.write_text("Keep this source intact.")

        code, run = self.run_watch(
            video, "--detail", "transcript", "--transcriber", "groq", "--cleanup",
        )

        self.assertEqual(code, 0)
        self.assertTrue(video.is_file())
        self.assertEqual(sidecar.read_text(), "Keep this source intact.")
        self.assertEqual(
            self.read_json(run / "supporting_transcripts.json")["sources"][0]["text"],
            "Keep this source intact.",
        )
        self.assertFalse((run / "audio.mp3").exists())

    def test_downloaded_url_does_not_pick_up_neighboring_local_transcripts(self):
        downloaded_media = self.video()
        downloaded_media.with_suffix(".txt").write_text("Unrelated local supporting text.")
        downloaded_media.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nUnrelated local subtitles.\n",
        )
        self.url_probe.side_effect = None
        self.url_probe.return_value = (None, {"duration": 120.0})
        self.download.side_effect = None
        self.download.return_value = (downloaded_media, None)

        code, run = self.run_watch("https://example.com/recording.mp4", "--transcriber", "none")

        self.assertEqual(code, 0)
        self.url_probe.assert_called_once()
        self.download.assert_called_once()
        self.assertEqual(self.read_json(run / "supporting_transcripts.json")["sources"], [])
        self.assertEqual(self.read_json(run / "metadata.json")["supporting_transcripts"]["count"], 0)
        self.transcribe.assert_not_called()
        self.gemini.assert_not_called()

    def test_folder_pairs_nested_videos_separately_and_ignores_links_and_run_outputs(self):
        first = self.video("first session/meeting.mp4")
        second = self.video("second session/meeting.MP4")
        first.with_suffix(".txt").write_text("First session supporting evidence.")
        second.with_suffix(".txt").write_text("Second session supporting evidence.")
        first_srt = first.with_name(f"{first.stem}_transcript.srt")
        second_srt = second.with_name(f"{second.stem}_transcript_grouped.srt")
        for number, path in enumerate((first_srt, second_srt), start=1):
            path.write_text(
                f"1\n00:00:03,000 --> 00:00:05,000\nSession {number} subtitles.\n",
            )
        (self.inputs / "irrelevant.txt").write_text("Not a video.")
        (self.inputs / "linked.mp4").symlink_to(first)
        (self.inputs / "linked-folder").symlink_to(first.parent, target_is_directory=True)
        out = self.inputs / "generated"
        out.mkdir()
        (out / "old-output.mp4").write_bytes(b"generated output must be skipped")
        prior = self.inputs / "prior-run"
        prior.mkdir()
        prior_metadata = {"engine": "local", "source": str(first)}
        (prior / "metadata.json").write_text(json.dumps(prior_metadata))
        (prior / "evidence.json").write_text(json.dumps({
            **prior_metadata, "schema_version": 1,
        }))
        (prior / "video.mp4").write_bytes(b"prior generated media must be skipped")
        prior_batch = self.inputs / "prior-batch"
        prior_batch.mkdir()
        (prior_batch / "batch.json").write_text(json.dumps({
            "schema_version": 1, "engine": "local", "source": str(self.inputs), "videos": [],
        }))
        (prior_batch / "video.mp4").write_bytes(b"prior batch media must be skipped")

        # The output base already contains a sentinel video, so find the batch by its manifest.
        with mock.patch.object(sys, "argv", [
            "watch.py", str(self.inputs), "--out-dir", str(out),
        ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main()
        batch_path = next(out.glob("*/batch.json"))
        batch = self.read_json(batch_path)

        self.assertEqual(code, 0)
        self.assertEqual(batch["engine"], "local")
        self.assertEqual([entry["source"] for entry in batch["videos"]], [str(first), str(second)])
        self.assertEqual(self.probe.call_count, 2)
        actual_texts = []
        for entry in batch["videos"]:
            self.assertEqual(entry["exit_code"], 0)
            child = Path(entry["run_dir"])
            self.assertTrue(Path(entry["report"]).is_file())
            self.assertTrue(child.is_relative_to(batch_path.parent / "videos"))
            sources = self.read_json(child / "supporting_transcripts.json")["sources"]
            self.assertEqual(len(sources), 2)
            txt = next(source for source in sources if Path(source["path"]).suffix == ".txt")
            srt = next(source for source in sources if Path(source["path"]).suffix == ".srt")
            self.assertEqual(Path(srt["path"]).parent, Path(entry["source"]).parent)
            self.assertEqual((srt["blocks"][0]["start"], srt["blocks"][0]["end"]), (3.0, 5.0))
            self.assertEqual(self.read_json(child / "metadata.json")["transcriber"], "none")
            actual_texts.append(txt["text"])
        self.assertEqual(actual_texts, [
            "First session supporting evidence.", "Second session supporting evidence.",
        ])
        self.assertTrue((batch_path.parent / "report.md").is_file())
        self.assert_no_cloud()

    def test_folder_keeps_real_videos_beside_unrelated_json_files(self):
        first = self.video("a-meeting-export/recording.mp4")
        second = self.video("b-export-job/recording.mp4")
        third = self.video("c-empty-json/recording.mp4")
        (first.parent / "metadata.json").write_text(json.dumps({"title": "Meeting export"}))
        (first.parent / "evidence.json").write_text(json.dumps({"notes": "Unrelated evidence"}))
        (second.parent / "batch.json").write_text(json.dumps({"job": "Video export"}))
        (third.parent / "metadata.json").write_text("{}")
        (third.parent / "evidence.json").write_text("{}")
        (third.parent / "batch.json").write_text("{}")

        code, run = self.run_watch(self.inputs)

        self.assertEqual(code, 0)
        batch = self.read_json(run / "batch.json")
        self.assertEqual(
            [entry["source"] for entry in batch["videos"]],
            [str(first), str(second), str(third)],
        )
        self.assertEqual(self.probe.call_count, 3)
        self.assertTrue(all(entry["exit_code"] == 0 for entry in batch["videos"]))
        self.assert_no_cloud()

    def test_folder_failure_is_reported_and_later_video_is_still_processed(self):
        broken = self.video("a-broken.mp4")
        good = self.video("z-good.mp4")
        good.with_suffix(".txt").write_text("Usable evidence after an earlier failure.")

        def probe(path):
            if path == broken:
                raise RuntimeError("synthetic probe failure")
            return self.probe_result

        self.probe.side_effect = probe
        code, run = self.run_watch(self.inputs)

        self.assertNotEqual(code, 0)
        batch = self.read_json(run / "batch.json")
        self.assertEqual(len(batch["videos"]), 2)
        failed, succeeded = batch["videos"]
        self.assertEqual(failed["source"], str(broken))
        self.assertEqual(failed["status"], "failed")
        self.assertNotEqual(failed["exit_code"], 0)
        self.assertIn("synthetic probe failure", failed["error"])
        self.assertEqual(succeeded["source"], str(good))
        self.assertEqual(succeeded["exit_code"], 0)
        self.assertTrue(Path(succeeded["report"]).is_file())
        self.assert_no_cloud()

    def test_folder_rejects_gemini_and_cached_run_before_processing(self):
        self.video()
        for flags in (("--engine", "gemini"), ("--from-run", str(self.root / "prior"))):
            with self.subTest(flags=flags), mock.patch.object(sys, "argv", [
                "watch.py", str(self.inputs), "--out-dir", str(self.out), *flags,
            ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    watch.main()
                self.assertNotEqual(caught.exception.code, 0)
        self.probe.assert_not_called()
        self.assert_no_cloud()

    def test_empty_folder_reports_no_video_instead_of_creating_successful_run(self):
        (self.inputs / "orphan.txt").write_text("No corresponding recording.")
        with mock.patch.object(sys, "argv", [
            "watch.py", str(self.inputs), "--out-dir", str(self.out),
        ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                watch.main()
        self.assertNotEqual(caught.exception.code, 0)
        self.probe.assert_not_called()
        self.assert_no_cloud()


if __name__ == "__main__":
    unittest.main()
