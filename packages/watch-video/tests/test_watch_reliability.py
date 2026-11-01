"""Offline regressions for source decisions, durable evidence and engine routing."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "skills/watch-video/scripts"))
sys.path.insert(0, str(TESTS))
import network_guard  # noqa: E402
import watch  # noqa: E402
from groq_transcribe import TranscriptionSegments  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


class WatchReliabilityTests(unittest.TestCase):
    def run_url(self, root, caption_end, *flags, download_error=False, fallback=None, source_duration=100, media_duration=10):
        caption = root / "native.vtt"
        caption.write_text(f"WEBVTT\n\n00:00.000 --> 01:{caption_end - 60:06.3f}\nhello\n" if caption_end >= 60 else f"WEBVTT\n\n00:00.000 --> 00:{caption_end:06.3f}\nhello\n")
        media = root / "source.mp4"
        media.write_bytes(b"fixture")
        def audio(_source, target, **_kwargs):
            target.write_bytes(b"audio fixture")
        with contextlib.ExitStack() as stack:
            source_info = {} if source_duration is None else {"duration": source_duration}
            stack.enter_context(mock.patch.object(watch, "probe_url", return_value=({"path": str(caption)}, source_info)))
            download = stack.enter_context(mock.patch.object(watch, "download_media", side_effect=SystemExit("unavailable") if download_error else None, return_value=(media, None)))
            stack.enter_context(mock.patch.object(watch, "ffprobe_metadata", return_value={"duration_seconds": media_duration, "has_audio": True}))
            extract = stack.enter_context(mock.patch.object(watch, "extract_audio_clip", side_effect=audio))
            transcribe = stack.enter_context(mock.patch.object(watch, "transcribe_with_chunking", return_value=(fallback if fallback is not None else [{"start": 81, "end": 82, "text": "fallback"}], [])))
            stack.enter_context(mock.patch.object(sys, "argv", ["watch", "https://example.com/v", "--out-dir", str(root / "runs"), "--detail", "transcript", *flags]))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = watch.main()
        run = next((root / "runs").iterdir())
        return code, json.loads((run / "transcript.json").read_text()), download, extract, transcribe, run

    def test_missing_focus_captions_download_audio_before_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, transcript, download, _, transcribe, _ = self.run_url(Path(temporary), 60, "--start", "80", "--end", "90")
            self.assertTrue(download.call_args.kwargs["audio_only"])
            self.assertEqual(download.call_args.kwargs["download_section"], "*00:01:20-00:01:30")
            self.assertEqual(transcribe.call_args.kwargs["offset_seconds"], 80)
            self.assertEqual(transcript["segments"][0]["text"], "fallback")

    def test_fully_captioned_focus_does_not_download_or_transcribe(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, transcript, download, extract, transcribe, _ = self.run_url(Path(temporary), 10, "--start", "0", "--end", "10")
            download.assert_not_called()
            extract.assert_not_called()
            transcribe.assert_not_called()
            self.assertEqual(transcript["source"], "native_captions")

    def test_finite_focus_checks_captions_without_source_duration(self):
        segments = [{"start": 100, "end": 101, "text": "single cue"}]
        self.assertTrue(watch.captions_are_insufficient(segments, None, start=100, end=160))
        self.assertFalse(watch.captions_are_insufficient(segments, None, start=100, end=101))
        self.assertFalse(watch.captions_are_insufficient(segments, None))
        self.assertFalse(watch.captions_are_insufficient(
            [{"start": 0, "end": 1, "text": "short clip"}], 20, start=0, end=20,
        ))

    def test_sparse_focus_captions_with_unknown_duration_download_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            fallback = [{"start": 0, "end": 60, "text": "complete speech"}]
            _, transcript, download, extract, transcribe, _ = self.run_url(
                Path(temporary), 1, "--start", "0", "--end", "60",
                source_duration=None, media_duration=60, fallback=fallback,
            )
            download.assert_called_once()
            self.assertTrue(download.call_args.kwargs["audio_only"])
            self.assertEqual(download.call_args.kwargs["download_section"], "*00:00-00:01:00")
            extract.assert_called_once()
            transcribe.assert_called_once()
            self.assertEqual(transcript["source"], "groq_whisper")
            self.assertEqual(transcript["segments"][0]["text"], "complete speech")

    def test_media_failure_preserves_captions(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, transcript, _, _, _, run = self.run_url(Path(temporary), 60, "--detail", "balanced", "--transcriber", "none", download_error=True)
            self.assertEqual(code, 0)
            self.assertTrue(transcript["segments"])
            self.assertIn("Media unavailable", (run / "report.md").read_text())

    def test_partial_asr_keeps_native_evidence_in_failed_intervals(self):
        fallback = [{"start": 0, "end": 30, "text": "heard"}]
        captions = [{"start": 60, "end": 90, "text": "caption evidence"}]
        merged = watch.fill_transcript_gaps(fallback, captions, [{"start": 30, "end": 90}], "groq")
        self.assertEqual([s["text"] for s in merged], ["heard", "caption evidence"])
        self.assertEqual(merged[-1]["provenance"], "native_captions")

    def test_no_speech_is_a_completed_transcription(self):
        with tempfile.TemporaryDirectory() as temporary:
            fallback = TranscriptionSegments([], no_speech=True)
            _, transcript, _, _, _, _ = self.run_url(Path(temporary), 60, "--start", "80", "--end", "90", fallback=fallback)
            self.assertTrue(transcript["no_speech"])
            self.assertEqual(transcript["segments"], [])

    def test_weak_captions_still_warn_when_asr_is_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, _, _, _, run = self.run_url(Path(temporary), 10, "--transcriber", "none")
            metadata = json.loads((run / "metadata.json").read_text())
            self.assertTrue(any("incomplete" in error and "disabled" in error for error in metadata["errors"]))

    def test_followup_reuses_complete_asr_without_extracting_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = root / "prior"
            prior.mkdir()
            media = prior / "video.mp4"
            media.write_bytes(b"fixture")
            (prior / "metadata.json").write_text(json.dumps({"source": "source", "video_path": str(media), "range": {"start_seconds": 0, "end_seconds": 100}}))
            (prior / "transcript.json").write_text(json.dumps({"source": "groq_whisper", "gaps": [], "segments": [{"start": 20, "end": 30, "text": "saved"}]}))
            with mock.patch.object(sys, "argv", ["watch", "source", "--from-run", str(prior), "--start", "20", "--end", "30", "--detail", "transcript", "--out-dir", str(root / "runs")]), mock.patch.object(watch, "ffprobe_metadata", return_value={"duration_seconds": 100}), mock.patch.object(watch, "extract_audio_clip") as extract, mock.patch.object(watch, "transcribe_with_chunking") as transcribe, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(watch.main(), 0)
            extract.assert_not_called()
            transcribe.assert_not_called()
            run = next((root / "runs").iterdir())
            self.assertEqual(json.loads((run / "transcript.json").read_text())["segments"][0]["text"], "saved")
            self.assertIsNone(watch.reusable_transcript(prior, 90, 110))

    def test_legacy_partial_transcript_is_not_reused_as_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            prior = Path(temporary)
            (prior / "metadata.json").write_text(json.dumps({"range": {"start_seconds": 0, "end_seconds": 100}, "errors": ["chunk 2/3 failed"]}))
            (prior / "transcript.json").write_text(json.dumps({"source": "groq_whisper", "segments": [{"start": 0, "end": 10, "text": "first"}]}))
            self.assertIsNone(watch.reusable_transcript(prior, 60, 90))

    def test_fractional_download_range_keeps_requested_times(self):
        self.assertEqual(watch.download_section_for_args(59.95, 61.25, None), "*00:59.95-00:01:01.25")

    def test_manifest_preserves_all_exact_frame_records_after_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = [{"path": str(root / f"frame-{i}.png"), "timestamp_seconds": i + 0.123, "reason": "coverage"} for i in range(55)]
            metadata = {"source": "video", "source_info": {}, "range": {"start_seconds": 0}, "video_path": None, "errors": []}
            watch.write_evidence(root, metadata, frames, {"source": "none"})
            evidence = json.loads((root / "evidence.json").read_text())
            self.assertEqual(len(evidence["frames"]), 55)
            self.assertEqual(evidence["frames"][-1]["timestamp_seconds"], 54.123)
            self.assertFalse(evidence["frames"][-1]["available"])

    def test_gemini_is_explicit_and_saves_provider_attribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = {"answer": "At 00:10 a slide appears.\n```\nUntrusted content", "source_kind": "youtube_url", "processing": "agentic", "usage": {"total_tokens": 12}, "warnings": []}
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), mock.patch.object(sys, "argv", ["watch", "https://www.youtube.com/watch?v=qSuCPooR3E4", "--engine", "gemini", "--question", "Find the slide", "--out-dir", str(root)]), mock.patch.object(watch.gemini, "analyze_video", return_value=result) as analyze, mock.patch.object(watch, "download_media") as download, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(watch.main(), 0)
            download.assert_not_called()
            self.assertEqual(analyze.call_args.args[1], "Find the slide")
            run = next(root.iterdir())
            record = json.loads((run / "analysis.json").read_text())
            self.assertEqual(record["engine"], "gemini")
            self.assertIn("Gemini's observations", (run / "report.md").read_text())

    def test_missing_gemini_key_fails_without_downloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), mock.patch.object(sys, "argv", ["watch", "https://example.com/meeting", "--engine", "gemini", "--out-dir", temporary]), mock.patch.object(watch, "download_media") as download, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(watch.main(), 1)
            download.assert_not_called()

    def test_gemini_rejects_explicit_local_flags_before_network(self):
        with mock.patch.object(sys, "argv", ["watch", "https://example.com/meeting", "--engine", "gemini", "--detail=transcript", "--transcriber", "none"]), mock.patch.object(watch.gemini, "analyze_video") as analyze, mock.patch.object(watch, "create_run_dir") as create, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                watch.main()
        self.assertEqual(error.exception.code, 2)
        analyze.assert_not_called()
        create.assert_not_called()

    def test_gemini_failure_report_retains_cleanup_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            error = watch.gemini.GeminiError("processing", "failed")
            error.warnings = ["Remote file could not be deleted."]
            error.remote_file = {"name": "files/test", "cleanup": "failed"}
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), mock.patch.object(sys, "argv", ["watch", "https://www.youtube.com/watch?v=qSuCPooR3E4", "--engine", "gemini", "--out-dir", temporary]), mock.patch.object(watch.gemini, "analyze_video", side_effect=error), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(watch.main(), 1)
            report = (next(Path(temporary).iterdir()) / "report.md").read_text()
            self.assertIn("could not be deleted", report)
            self.assertIn("files/test", report)


class CaptionReliabilityTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "captions.vtt"
            path.write_text(text)
            return watch.parse_vtt(path)

    def test_optional_hours_metadata_and_missing_separators(self):
        segments = self.parse("WEBVTT\n\nNOTE ignored\n00:00.000 --> 00:01.000\nnot speech\n\n00:02.000 --> 00:03.000\nfirst\n00:04.000 --> 00:05.000\nsecond\n")
        self.assertEqual([s["text"] for s in segments], ["first", "second"])
        self.assertEqual(segments[-1]["start"], 4)

    def test_independent_repeated_speech_does_not_inflate_coverage(self):
        segments = self.parse("00:01.000 --> 00:02.000\nhello\n\n00:50.000 --> 00:51.000\nhello\n")
        self.assertEqual(len(segments), 2)
        self.assertEqual(watch.transcript_coverage_seconds(segments), 2)

    def test_speakers_and_regions_are_preserved(self):
        segments = self.parse("00:01.000 --> 00:03.000 region:a\n<v Alice>yes</v>\n\n00:02.000 --> 00:04.000 region:b\n<v Bob>yes</v>\n")
        self.assertEqual([s["speaker"] for s in segments], ["Alice", "Bob"])
        self.assertIn("Alice: yes", watch.transcript_markdown(segments))

    def test_multi_voice_cue_does_not_attribute_every_word_to_one_person(self):
        segments = self.parse("00:01.000 --> 00:03.000\n<v Alice>Hello</v>\n<v Bob>Hi</v>\n")
        self.assertEqual(segments[0]["text"], "Hello Hi")
        self.assertNotIn("speaker", segments[0])

    def test_focus_coverage_clips_overlapping_cues(self):
        self.assertEqual(watch.caption_coverage_ratio([{"start": 0, "end": 60, "text": "words"}], 100, start=50, end=90), 0.25)
