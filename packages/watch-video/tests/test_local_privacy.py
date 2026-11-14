"""Every source requires an explicit cloud transcription choice."""

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
import unittest_backports  # noqa: E402, F401
import watch  # noqa: E402
from groq_transcribe import TranscriptionSegments  # noqa: E402
from run_contents import unexpected_entries  # noqa: E402


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
        self.assertEqual(unexpected_entries(run), [])
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

    def test_fresh_url_with_keys_does_not_download_or_upload_audio_by_default(self):
        metadata, transcript = self.run_watch(URL, "--detail", "transcript")
        self.probe.assert_called_once()
        # Captions are missing, but nothing was chosen: no audio download,
        # no extraction and no provider request.
        self.download.assert_not_called()
        self.assertEqual(metadata["transcriber"], "none")
        self.assertEqual(transcript["source"], "none")
        self.assert_no_cloud_or_audio()

    def test_fresh_url_frames_download_video_without_uploading_audio(self):
        metadata, transcript = self.run_watch(URL)
        self.download.assert_called_once()
        self.assertFalse(self.download.call_args.kwargs["audio_only"])
        self.frames.assert_called_once()
        self.assertEqual(metadata["transcriber"], "none")
        self.assertEqual(transcript["source"], "none")
        self.assert_no_cloud_or_audio()

    def test_explicit_hosted_transcriber_on_a_fresh_url_is_preserved(self):
        for provider in ("groq", "openai"):
            with self.subTest(provider=provider):
                self.download.reset_mock()
                self.audio.reset_mock()
                self.transcribe.reset_mock()
                metadata, transcript = self.run_watch(
                    URL, "--detail", "transcript", "--transcriber", provider,
                )
                self.download.assert_called_once()
                self.assertTrue(self.download.call_args.kwargs["audio_only"])
                self.audio.assert_called_once()
                self.transcribe.assert_called_once()
                self.assertEqual(self.transcribe.call_args.kwargs["provider"], provider)
                self.assertEqual(metadata["transcriber"], provider)
                self.assertEqual(transcript["source"], f"{provider}_whisper")
        self.gemini.assert_not_called()

    def test_missing_speech_names_the_opt_in_flags_and_the_consent_condition(self):
        metadata, _ = self.run_watch(URL, "--detail", "transcript")
        warnings = " ".join(metadata["errors"])
        self.assertIn("no transcriber was selected", warnings)
        self.assertIn("--transcriber local", warnings)
        # Both keys are configured in this fixture, so both flags are named,
        # each time with the upload and the consent it needs.
        self.assertIn("--transcriber groq or --transcriber openai is configured", warnings)
        self.assertIn("uploads the audio to Groq or OpenAI", warnings)
        self.assertIn("only with the user's consent for this source", warnings)
        self.assertNotIn("test-placeholder", warnings)

    def test_missing_speech_hint_without_keys_does_not_call_a_provider_ready(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENAI_API_KEY": ""}):
            metadata, _ = self.run_watch(self.media)
        warnings = " ".join(metadata["errors"])
        self.assertIn("--transcriber groq or openai needs an API key", warnings)
        self.assertNotIn("is configured", warnings)
        self.assert_no_cloud_or_audio()

    def test_chosen_hosted_transcriber_without_its_key_fails_before_any_work(self):
        cases = ((URL, "groq", "GROQ_API_KEY"), (self.media, "openai", "OPENAI_API_KEY"))
        for source, provider, key_name in cases:
            out_dir = self.root / f"no-key-{provider}"
            with self.subTest(provider=provider), mock.patch.dict(os.environ, {key_name: " "}), \
                    mock.patch.object(sys, "argv", [
                        "watch.py", str(source), "--out-dir", str(out_dir), "--transcriber", provider,
                    ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    watch.main()
                message = str(error.exception)
                self.assertIn(f"--transcriber {provider} needs {key_name}", message)
                self.assertIn(f"--set-key {provider}", message)
                # Nothing was probed, downloaded, extracted or written.
                self.assertFalse(out_dir.exists())
        self.probe.assert_not_called()
        self.download.assert_not_called()
        self.assert_no_cloud_or_audio()

    def test_stored_key_satisfies_the_early_key_check(self):
        config = self.root / "stored-config"
        config.mkdir()
        (config / ".env").write_text("GROQ_API_KEY=test-placeholder-stored\n", encoding="utf-8")
        (config / ".env").chmod(0o600)
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "WATCH_VIDEO_CONFIG_DIR": str(config)}):
            metadata, _ = self.run_watch(URL, "--detail", "transcript", "--transcriber", "groq")
        self.assertEqual(metadata["transcriber"], "groq")
        self.transcribe.assert_called_once()

    def test_silent_media_does_not_suggest_transcription(self):
        with mock.patch.object(watch, "ffprobe_metadata", return_value={
            "duration_seconds": 30.0, "width": 1280, "height": 720, "has_audio": False,
        }):
            metadata, _ = self.run_watch(self.media)
        self.assertFalse(any("--transcriber" in error for error in metadata["errors"]))


if __name__ == "__main__":
    unittest.main()
