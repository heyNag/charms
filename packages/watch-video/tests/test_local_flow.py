"""Offline orchestration coverage for original audio + frames + supplied text."""

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


URL = "https://www.youtube.com/watch?v=local-fixture"


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


class LocalFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.inputs = self.root / "meetings"
        self.inputs.mkdir()
        self.video = self.make_video("meeting.mp4")
        self.output_number = 0
        self.enterContext(mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "test-placeholder-groq", "OPENAI_API_KEY": "test-placeholder-openai",
            "GEMINI_API_KEY": "test-placeholder-gemini", "WATCH_VIDEO_LOCAL_API_KEY": "test-placeholder-local",
            "WATCH_VIDEO_CONFIG_DIR": str(self.root / "unused-config"),
        }, clear=True))
        self.hosted_asr = self.enterContext(mock.patch.object(
            watch, "transcribe_with_chunking", side_effect=AssertionError("unexpected cloud ASR")))
        self.hosted_audio = self.enterContext(mock.patch.object(
            watch, "extract_audio_clip", side_effect=AssertionError("unexpected hosted extraction")))
        self.gemini = self.enterContext(mock.patch.object(
            watch.gemini, "analyze_video", side_effect=AssertionError("unexpected Gemini")))
        self.enterContext(mock.patch.object(
            watch, "run_command", side_effect=AssertionError("unexpected external process")))
        self.enterContext(mock.patch.object(watch, "ffprobe_metadata", return_value={
            "duration_seconds": 120.0, "width": 1280, "height": 720, "has_audio": True,
        }))
        self.url_probe = self.enterContext(mock.patch.object(
            watch, "probe_url", return_value=(None, {"duration": 120})))
        self.download = self.enterContext(mock.patch.object(
            watch, "download_media", return_value=(self.video, None)))

        def extract(_source, target, **_kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"synthetic PCM audio")
            return target

        self.extract_audio = self.enterContext(mock.patch.object(
            watch.local_transcribe, "extract_audio_clip", side_effect=extract))
        self.asr = self.enterContext(mock.patch.object(
            watch.local_transcribe, "transcribe_with_chunking", return_value=(
                TranscriptionSegments([{"start": 0, "end": 4, "text": "Original audio says alpha."}]), [],
            )))

        def extract_frames(_source, directory, **_kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            frame = directory / "frame.png"
            frame.write_bytes(b"fixture image never decoded")
            return [{"path": str(frame), "timestamp": "00:30", "timestamp_seconds": 30,
                     "selection_reason": "scene"}], {}

        self.frames = self.enterContext(mock.patch.object(watch, "extract_scene_frames", side_effect=extract_frames))
        self.analyze = self.enterContext(mock.patch.object(
            watch.local_analyze, "analyze_local", return_value={"status": "complete"}))

    def make_video(self, name):
        path = self.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic video never uploaded")
        return path

    def full_caption(self, path):
        path.write_text("1\n00:00:00,000 --> 00:02:00,000\nSupplied captions say beta.\n")
        return path

    def run_watch(self, source, *flags):
        self.output_number += 1
        output = self.root / f"runs-{self.output_number}"
        with mock.patch.object(sys, "argv", ["watch.py", str(source), "--out-dir", str(output), *flags]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main()
        return code, next(output.iterdir())

    def read(self, run, name):
        return json.loads((run / name).read_text())

    def assert_no_cloud(self):
        self.hosted_asr.assert_not_called()
        self.hosted_audio.assert_not_called()
        self.gemini.assert_not_called()

    def test_full_supplied_captions_do_not_replace_original_audio(self):
        self.full_caption(self.video.with_suffix(".srt"))
        self.video.with_suffix(".txt").write_text("[00:00:00] Speaker: Additional supplied gamma.")
        code, run = self.run_watch(self.video, "--analyzer", "local")
        self.assertEqual(code, 0)
        self.extract_audio.assert_called_once()
        self.asr.assert_called_once()
        self.assertEqual(self.extract_audio.call_args.args[1].suffix, ".wav")
        transcript = self.read(run, "transcript.json")
        self.assertEqual(transcript["source"], "local_whisper")
        self.assertEqual(transcript["segments"][0]["text"], "Original audio says alpha.")
        supporting = self.read(run, "supporting_transcripts.json")["sources"]
        self.assertEqual(len(supporting), 2)
        self.assertTrue(all(s["role"] == "supporting" for s in supporting))
        self.assertEqual(self.read(run, "native_captions.json")["segments"][0]["text"], "Supplied captions say beta.")
        metadata = self.read(run, "metadata.json")
        self.assertEqual(metadata["original_audio"]["status"], "complete")
        self.assertEqual(metadata["transcriber"], "local")
        self.frames.assert_called_once()
        self.analyze.assert_called_once()
        self.assert_no_cloud()

    def test_full_url_captions_still_download_original_audio_for_local_asr(self):
        caption = self.full_caption(self.root / "native.srt")
        self.url_probe.return_value = ({"path": str(caption), "caption_type": "manual", "language": "en"}, {"duration": 120})
        code, run = self.run_watch(URL, "--transcriber", "local", "--detail", "transcript")
        self.assertEqual(code, 0)
        self.download.assert_called_once()
        self.assertTrue(self.download.call_args.kwargs["audio_only"])
        self.extract_audio.assert_called_once()
        self.asr.assert_called_once()
        self.assertEqual(self.read(run, "transcript.json")["source"], "local_whisper")
        self.assert_no_cloud()

    def test_analyzer_local_url_defaults_to_local_asr_without_cloud(self):
        code, run = self.run_watch(URL, "--analyzer", "local")
        self.assertEqual(code, 0)
        self.assertEqual(self.read(run, "metadata.json")["transcriber"], "local")
        self.assertFalse(self.download.call_args.kwargs["audio_only"])
        self.asr.assert_called_once()
        self.assert_no_cloud()

    def test_explicit_hosted_asr_with_local_analyzer_is_not_bypassed_by_full_captions(self):
        caption = self.video.with_suffix(".vtt")
        caption.write_text("WEBVTT\n\n00:00:00.000 --> 00:02:00.000\nSupplied captions say beta.\n")
        self.url_probe.return_value = ({"path": str(caption), "caption_type": "manual", "language": "en"}, {"duration": 120})
        self.hosted_audio.side_effect = self.extract_audio.side_effect
        self.hosted_asr.side_effect = None
        self.hosted_asr.return_value = (
            TranscriptionSegments([{"start": 0, "end": 4, "text": "Original audio says alpha."}]), [],
        )
        for source in (URL, self.video):
            for provider in ("groq", "openai"):
                with self.subTest(source=str(source), provider=provider):
                    self.download.reset_mock()
                    self.hosted_audio.reset_mock()
                    self.hosted_asr.reset_mock()
                    code, run = self.run_watch(source, "--analyzer", "local", "--transcriber", provider,
                                               "--detail", "transcript")
                    self.assertEqual(code, 0)
                    self.hosted_audio.assert_called_once()
                    self.hosted_asr.assert_called_once()
                    self.assertEqual(self.hosted_asr.call_args.kwargs["provider"], provider)
                    self.assertEqual(self.read(run, "transcript.json")["source"], f"{provider}_whisper")
                    if source == URL:
                        self.download.assert_called_once()
                        self.assertTrue(self.download.call_args.kwargs["audio_only"])
                    else:
                        self.download.assert_not_called()
        self.extract_audio.assert_not_called()
        self.asr.assert_not_called()
        self.gemini.assert_not_called()

    def test_explicit_none_with_local_analyzer_keeps_complete_url_captions_without_downloading(self):
        caption = self.full_caption(self.root / "native.srt")
        self.url_probe.return_value = ({"path": str(caption), "caption_type": "manual", "language": "en"}, {"duration": 120})
        code, run = self.run_watch(URL, "--analyzer", "local", "--transcriber", "none", "--detail", "transcript")
        self.assertEqual(code, 0)
        self.download.assert_not_called()
        self.extract_audio.assert_not_called()
        self.asr.assert_not_called()
        self.assertEqual(self.read(run, "transcript.json")["source"], "native_captions")
        self.assert_no_cloud()

    def test_explicit_none_disables_original_audio_even_with_local_analyzer(self):
        self.full_caption(self.video.with_suffix(".srt"))
        code, run = self.run_watch(self.video, "--analyzer", "local", "--transcriber", "none")
        self.assertEqual(code, 0)
        self.asr.assert_not_called()
        self.extract_audio.assert_not_called()
        self.analyze.assert_called_once()
        self.assertEqual(self.read(run, "metadata.json")["original_audio"]["status"], "not_requested")
        self.assertEqual(self.read(run, "transcript.json")["source"], "native_captions")
        self.assert_no_cloud()

    def test_local_cache_rejects_hosted_and_wrong_model_but_reuses_matching_model(self):
        code, prior = self.run_watch(self.video, "--transcriber", "local", "--detail", "transcript")
        self.assertEqual(code, 0)
        original = self.read(prior, "transcript.json")
        for source, model, should_transcribe in [
            ("groq_whisper", "whisper-large-v3", True),
            ("openai_whisper", "whisper-1", True),
            ("local_whisper", "other-local-model", True),
            ("local_whisper", original["model"], False),
        ]:
            with self.subTest(source=source, model=model):
                (prior / "transcript.json").write_text(json.dumps({**original, "source": source, "model": model}))
                self.asr.reset_mock()
                self.extract_audio.reset_mock()
                code, run = self.run_watch(self.video, "--transcriber", "local", "--from-run", str(prior), "--detail", "transcript")
                self.assertEqual(code, 0)
                self.assertEqual(self.asr.called, should_transcribe)
                self.assertEqual(self.extract_audio.called, should_transcribe)
                self.assertEqual(self.read(run, "transcript.json")["source"], "local_whisper")
        self.assert_no_cloud()

    def test_failed_original_audio_is_nonzero_and_captions_stay_supplementary(self):
        self.full_caption(self.video.with_suffix(".srt"))
        def fail(_audio, *, out_json, **_kwargs):
            out_json.write_text(json.dumps({"gaps": [{"start": 0, "end": 60}, {"start": 60, "end": 120}]}))
            raise RuntimeError("Local service unavailable.")
        self.asr.side_effect = fail
        code, run = self.run_watch(self.video, "--analyzer", "local")
        self.assertEqual(code, 1)
        transcript = self.read(run, "transcript.json")
        self.assertEqual(transcript["source"], "local_whisper")
        self.assertEqual(transcript["segments"], [])
        self.assertEqual(len(transcript["gaps"]), 2)
        self.assertFalse(transcript["no_speech"])
        self.assertEqual(self.read(run, "metadata.json")["original_audio"]["status"], "incomplete")
        self.assertTrue(self.read(run, "native_captions.json")["segments"])
        self.assertEqual(len(self.read(run, "supporting_transcripts.json")["sources"]), 1)
        self.assert_no_cloud()

    def test_partial_original_audio_never_fills_gaps_with_supplied_captions(self):
        self.full_caption(self.video.with_suffix(".srt"))
        self.asr.return_value = (TranscriptionSegments(
            [{"start": 0, "end": 4, "text": "Independent audio."}], gaps=[{"start": 60, "end": 120}]), ["Second chunk failed."])
        code, run = self.run_watch(self.video, "--analyzer", "local")
        self.assertEqual(code, 1)
        transcript = self.read(run, "transcript.json")
        self.assertEqual(len(transcript["segments"]), 1)
        self.assertEqual(transcript["segments"][0]["provenance"], "local_whisper")
        self.assertEqual(transcript["gaps"], [{"start": 60, "end": 120}])
        self.assert_no_cloud()

    def test_analysis_receives_evidence_before_cleanup(self):
        def analyze(run, **_kwargs):
            manifest = self.read(run, "evidence.json")
            self.assertTrue((run / "audio.wav").is_file())
            self.assertTrue(Path(manifest["frames"][0]["path"]).is_file())
            self.assertTrue(self.read(run, "transcript.json")["segments"])
            return {"status": "complete"}
        self.analyze.side_effect = analyze
        code, run = self.run_watch(self.video, "--analyzer", "local", "--cleanup", "--cleanup-frames")
        self.assertEqual(code, 0)
        self.analyze.assert_called_once()
        self.assertFalse((run / "audio.wav").exists())
        self.assertFalse(self.read(run, "evidence.json")["frames"][0]["available"])
        self.assertTrue(self.video.exists())
        self.assert_no_cloud()

    def test_directory_processes_every_video_with_its_own_matching_transcript(self):
        second = self.make_video("nested/second.mp4")
        self.video.with_suffix(".txt").write_text("First supplied record")
        second.with_suffix(".srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nSecond supplied record\n")
        code, batch_dir = self.run_watch(self.inputs, "--analyzer", "local")
        self.assertEqual(code, 0)
        batch = self.read(batch_dir, "batch.json")
        self.assertEqual(len(batch["videos"]), 2)
        self.assertEqual(self.asr.call_count, 2)
        self.assertEqual(self.analyze.call_count, 2)
        for record in batch["videos"]:
            self.assertEqual(record["status"], "completed")
            run = Path(record["run_dir"])
            self.assertEqual(self.read(run, "transcript.json")["source"], "local_whisper")
            self.assertEqual(len(self.read(run, "supporting_transcripts.json")["sources"]), 1)
        self.assert_no_cloud()

    def test_model_failure_returns_nonzero_without_discarding_audio_or_frames(self):
        self.analyze.side_effect = RuntimeError("Local model unavailable.")
        code, run = self.run_watch(self.video, "--analyzer", "local")
        self.assertEqual(code, 1)
        metadata = self.read(run, "metadata.json")
        self.assertEqual(metadata["local_analysis"]["status"], "error")
        self.assertEqual(metadata["original_audio"]["status"], "complete")
        self.assertTrue((run / "audio.wav").exists())
        self.assertTrue(self.read(run, "evidence.json")["frames"][0]["available"])
        self.assert_no_cloud()


if __name__ == "__main__":
    unittest.main()
