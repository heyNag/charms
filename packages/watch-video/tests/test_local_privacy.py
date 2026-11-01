"""Local and cached media require an explicit cloud transcription choice."""

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


URL = "https://example.com/recording.mp4"


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


class LocalPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.media = self.root / "synthetic.mp4"
        self.media.write_bytes(b"synthetic media fixture, never decoded or uploaded")
        self.run_number = 0
        # The presence of credentials must not enable an upload implicitly.
        self.enterContext(mock.patch.dict(os.environ, {
            "GROQ_API_KEY": "test-placeholder-groq",
            "OPENAI_API_KEY": "test-placeholder-openai",
            "GEMINI_API_KEY": "test-placeholder-gemini",
            "WATCH_VIDEO_CONFIG_DIR": str(self.root / "unused-config"),
        }, clear=True))
        self.enterContext(mock.patch.object(
            watch, "run_command", side_effect=AssertionError("unexpected media subprocess"),
        ))
        self.enterContext(mock.patch.object(watch, "ffprobe_metadata", return_value={
            "duration_seconds": 30.0, "width": 1280, "height": 720, "has_audio": True,
        }))
        self.probe = self.enterContext(mock.patch.object(
            watch, "probe_url", return_value=(None, {"duration": 30.0}),
        ))
        self.download = self.enterContext(mock.patch.object(
            watch, "download_media", return_value=(self.media, None),
        ))
        self.resolve_cached = self.enterContext(mock.patch.object(
            watch, "resolve_from_run", return_value=(self.media, None, {"duration": 30.0}),
        ))
        self.cached_transcript = self.enterContext(mock.patch.object(
            watch, "reusable_transcript", return_value=None,
        ))
        self.frames = self.enterContext(mock.patch.object(
            watch, "extract_scene_frames", return_value=([], {}),
        ))

        def extract_audio(_source, target, **_kwargs):
            target.write_bytes(b"synthetic audio fixture")
            return target

        self.audio = self.enterContext(mock.patch.object(
            watch, "extract_audio_clip", side_effect=extract_audio,
        ))
        self.transcribe = self.enterContext(mock.patch.object(
            watch, "transcribe_with_chunking", return_value=(
                TranscriptionSegments([{"start": 0.0, "end": 2.0, "text": "fixture speech"}]),
                [],
            ),
        ))
        self.gemini = self.enterContext(mock.patch.object(
            watch.gemini, "analyze_video", side_effect=AssertionError("unexpected Gemini upload"),
        ))

    def run_watch(self, source, *flags):
        self.run_number += 1
        out_dir = self.root / f"runs-{self.run_number}"
        with mock.patch.object(sys, "argv", [
            "watch.py", str(source), "--out-dir", str(out_dir), *flags,
        ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(watch.main(), 0)
        run = next(out_dir.iterdir())
        return (
            json.loads((run / "metadata.json").read_text()),
            json.loads((run / "transcript.json").read_text()),
        )

    def assert_no_cloud_or_audio(self):
        self.audio.assert_not_called()
        self.transcribe.assert_not_called()
        self.gemini.assert_not_called()

    def test_local_file_with_keys_uses_local_frames_without_cloud_transcription(self):
        metadata, transcript = self.run_watch(self.media)
        self.assertEqual(metadata["engine"], "local")
        self.assertEqual(metadata["transcriber"], "none")
        self.assertEqual(transcript["source"], "none")
        self.frames.assert_called_once()
        self.probe.assert_not_called()
        self.download.assert_not_called()
        self.assert_no_cloud_or_audio()

    def test_explicit_local_cloud_provider_is_preserved(self):
        for provider in ("groq", "openai"):
            with self.subTest(provider=provider):
                self.audio.reset_mock()
                self.transcribe.reset_mock()
                metadata, transcript = self.run_watch(
                    self.media, "--detail", "transcript", "--transcriber", provider,
                )
                self.audio.assert_called_once()
                self.transcribe.assert_called_once()
                self.assertEqual(self.transcribe.call_args.kwargs["provider"], provider)
                self.assertEqual(metadata["transcriber"], provider)
                self.assertEqual(transcript["source"], f"{provider}_whisper")
        self.probe.assert_not_called()
        self.download.assert_not_called()
        self.gemini.assert_not_called()

    def test_cached_url_without_reusable_transcript_does_not_upload(self):
        metadata, transcript = self.run_watch(
            URL, "--from-run", str(self.root / "prior-run"), "--detail", "transcript",
        )
        self.resolve_cached.assert_called_once()
        self.cached_transcript.assert_called_once()
        self.assertEqual(metadata["transcriber"], "none")
        self.assertEqual(transcript["source"], "none")
        self.probe.assert_not_called()
        self.download.assert_not_called()
        self.assert_no_cloud_or_audio()

    def test_refreshing_cached_transcript_does_not_authorize_cloud_upload(self):
        metadata, _ = self.run_watch(
            URL, "--from-run", str(self.root / "prior-run"), "--refresh-transcript",
            "--detail", "transcript",
        )
        self.cached_transcript.assert_not_called()
        self.assertEqual(metadata["transcriber"], "none")
        self.assert_no_cloud_or_audio()

    def test_fresh_url_retains_groq_fallback_default(self):
        metadata, transcript = self.run_watch(URL, "--detail", "transcript")
        self.probe.assert_called_once()
        self.download.assert_called_once()
        self.assertTrue(self.download.call_args.kwargs["audio_only"])
        self.audio.assert_called_once()
        self.transcribe.assert_called_once()
        self.assertEqual(self.transcribe.call_args.kwargs["provider"], "groq")
        self.assertEqual(metadata["transcriber"], "groq")
        self.assertEqual(transcript["source"], "groq_whisper")
        self.gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
