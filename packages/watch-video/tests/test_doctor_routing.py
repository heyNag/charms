"""Offline checks that setup requirements follow the selected video route."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import doctor  # noqa: E402
import network_guard  # noqa: E402


YOUTUBE = "https://www.youtube.com/watch?v=qSuCPooR3E4"
LOCAL_VIDEO = "/tmp/watch-video-fixture.mp4"
OTHER_URL = "https://example.com/recording.mp4"
ALL_BINARIES = ["yt-dlp", "ffmpeg", "ffprobe"]


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def ok_check(name: str) -> dict:
    return {"name": name, "ok": True, "message": "fixture"}


class DoctorRoutingTests(unittest.TestCase):
    def setUp(self):
        # Route tests must not read credentials, inspect the user's artifacts,
        # or run either an installer or a source command.
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        for function, name in (
            ("check_platform", "platform"),
            ("check_python_version", "python"),
            ("check_gemini_key", "GEMINI_API_KEY"),
            ("check_config_file", "whisper-config"),
            ("check_run_artifacts", "run-artifacts"),
            ("check_env_local", ".env.local"),
        ):
            self.enterContext(mock.patch.object(doctor, function, return_value=ok_check(name)))
        self.enterContext(mock.patch.object(
            doctor, "check_whisper_key",
            side_effect=lambda provider: ok_check(f"{provider.upper()}_API_KEY"),
        ))
        self.enterContext(mock.patch.object(doctor, "current_platform", return_value="macOS"))
        self.subprocess_run = self.enterContext(mock.patch.object(
            doctor.subprocess, "run", side_effect=AssertionError("unexpected subprocess"),
        ))

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["doctor.py", *args]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = doctor.main()
        return result, output.getvalue(), errors.getvalue()

    def test_gemini_sources_pass_json_and_check_without_media_binaries(self):
        with mock.patch.object(doctor.shutil, "which", return_value=None):
            for source in (YOUTUBE, LOCAL_VIDEO):
                with self.subTest(source=source):
                    code, output, _ = self.cli(source, "--engine", "gemini", "--json")
                    status = json.loads(output)
                    self.assertEqual(code, 0)
                    self.assertTrue(status["ok"])
                    self.assertEqual(status["required_binaries"], [])
                    code, output, errors = self.cli(source, "--engine", "gemini", "--check")
                    self.assertEqual((code, output, errors), (0, "", ""))
        self.subprocess_run.assert_not_called()

    def test_local_file_ignores_missing_downloader_but_requires_media_tools(self):
        installed = {"ffmpeg", "ffprobe"}
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: f"/fixture/{name}" if name in installed else None,
        ):
            code, output, errors = self.cli(LOCAL_VIDEO, "--check")
            self.assertEqual((code, output, errors), (0, "", ""))
            status = doctor.collect_status(source=LOCAL_VIDEO)
            self.assertEqual(status["required_binaries"], ["ffmpeg", "ffprobe"])
            installed.remove("ffprobe")
            code, _, errors = self.cli(LOCAL_VIDEO, "--check")
            self.assertEqual(code, 1)
            self.assertIn("ffprobe", errors)

    def test_local_url_requires_downloader_even_for_youtube(self):
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: None if name == "yt-dlp" else f"/fixture/{name}",
        ):
            code, _, errors = self.cli(YOUTUBE, "--engine", "local", "--check")
        self.assertEqual(code, 1)
        self.assertIn("yt-dlp", errors)

    def test_cached_local_url_passes_without_downloader(self):
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: None if name == "yt-dlp" else f"/fixture/{name}",
        ):
            args = (YOUTUBE, "--from-run", "/tmp/watch-video-prior-run")
            code, output, errors = self.cli(*args, "--check")
            self.assertEqual((code, output, errors), (0, "", ""))
            code, output, _ = self.cli(*args, "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["required_binaries"], ["ffmpeg", "ffprobe"])
        self.subprocess_run.assert_not_called()

    def test_gemini_rejects_cached_runs_before_checks_or_installation(self):
        with mock.patch.object(doctor.shutil, "which") as which, \
                mock.patch.object(doctor, "collect_status") as collect, \
                mock.patch.object(doctor, "install_missing") as install:
            for action in ("--check", "--install"):
                with self.subTest(action=action), self.assertRaises(SystemExit) as error:
                    self.cli(
                        YOUTUBE, "--engine", "gemini", "--from-run",
                        "/tmp/watch-video-prior-run", action,
                    )
                self.assertEqual(error.exception.code, 2)
        which.assert_not_called()
        collect.assert_not_called()
        install.assert_not_called()
        self.subprocess_run.assert_not_called()

    def test_gemini_other_urls_and_deceptive_youtube_host_require_downloader(self):
        sources = (OTHER_URL, "https://www.youtube.com.example.com/watch?v=qSuCPooR3E4")
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: None if name == "yt-dlp" else f"/fixture/{name}",
        ):
            for source in sources:
                with self.subTest(source=source):
                    code, output, _ = self.cli(source, "--engine", "gemini", "--json")
                    status = json.loads(output)
                    self.assertEqual(code, 1)
                    self.assertFalse(status["ok"])
                    self.assertEqual(status["required_binaries"], ALL_BINARIES)
                    self.assertTrue(any(
                        check["name"] == "yt-dlp" and not check["ok"]
                        for check in status["checks"]
                    ))

    def test_no_source_preserves_full_toolkit_check_for_both_engines(self):
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: None if name == "yt-dlp" else f"/fixture/{name}",
        ):
            for engine in ("local", "gemini"):
                with self.subTest(engine=engine):
                    code, output, _ = self.cli("--engine", engine, "--json")
                    self.assertEqual(code, 1)
                    self.assertEqual(json.loads(output)["required_binaries"], ALL_BINARIES)

    def test_gemini_direct_routes_install_nothing_even_without_brew(self):
        with mock.patch.object(doctor.shutil, "which", return_value=None):
            for source in (YOUTUBE, LOCAL_VIDEO):
                with self.subTest(source=source):
                    code, _, _ = self.cli(source, "--engine", "gemini", "--install")
                    self.assertEqual(code, 0)
        self.subprocess_run.assert_not_called()

    def test_local_file_installer_installs_ffmpeg_once_and_not_downloader(self):
        installed = {"brew"}

        def install(command, **kwargs):
            self.assertEqual(command, ["brew", "install", "ffmpeg"])
            installed.update({"ffmpeg", "ffprobe"})
            return subprocess.CompletedProcess(command, 0)

        self.subprocess_run.side_effect = install
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: f"/fixture/{name}" if name in installed else None,
        ):
            code, _, _ = self.cli(LOCAL_VIDEO, "--install")
        self.assertEqual(code, 0)
        self.subprocess_run.assert_called_once()

    def test_gemini_other_url_installer_installs_missing_downloader(self):
        installed = {"brew", "ffmpeg", "ffprobe"}

        def install(command, **kwargs):
            self.assertEqual(command, ["brew", "install", "yt-dlp"])
            installed.add("yt-dlp")
            return subprocess.CompletedProcess(command, 0)

        self.subprocess_run.side_effect = install
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: f"/fixture/{name}" if name in installed else None,
        ):
            code, _, _ = self.cli(OTHER_URL, "--engine", "gemini", "--install")
        self.assertEqual(code, 0)
        self.subprocess_run.assert_called_once()

    def test_cached_url_installer_installs_only_ffmpeg(self):
        installed = {"brew"}

        def install(command, **kwargs):
            self.assertEqual(command, ["brew", "install", "ffmpeg"])
            installed.update({"ffmpeg", "ffprobe"})
            return subprocess.CompletedProcess(command, 0)

        self.subprocess_run.side_effect = install
        with mock.patch.object(
            doctor.shutil, "which", side_effect=lambda name: f"/fixture/{name}" if name in installed else None,
        ):
            code, _, _ = self.cli(
                YOUTUBE, "--from-run", "/tmp/watch-video-prior-run", "--install",
            )
        self.assertEqual(code, 0)
        self.subprocess_run.assert_called_once()

    def test_local_model_flow_needs_only_media_tools_and_no_hosted_key(self):
        with mock.patch.object(
            doctor.shutil, "which",
            side_effect=lambda name: None if name == "yt-dlp" else f"/fixture/{name}",
        ):
            code, output, errors = self.cli(
                LOCAL_VIDEO, "--transcriber", "local", "--analyzer", "local", "--json",
            )
        self.assertEqual((code, errors), (0, ""))
        status = json.loads(output)
        self.assertEqual(status["required_binaries"], ["ffmpeg", "ffprobe"])
        checks = {check["name"]: check for check in status["checks"]}
        self.assertTrue(checks["local-endpoint"]["ok"])
        self.assertFalse(checks["WATCH_VIDEO_LOCAL_API_KEY"]["ok"])
        self.assertIn("not tested", checks["local-models"]["message"])
        self.assertIn("speech-to-text", checks["local-models"]["message"])
        self.assertIn("vision-language", checks["local-models"]["message"])
        self.subprocess_run.assert_not_called()

    def test_local_analyzer_implicitly_checks_local_asr_but_explicit_none_is_respected(self):
        with mock.patch.object(doctor.shutil, "which", return_value="/fixture/bin"):
            implicit = doctor.collect_status(source=LOCAL_VIDEO, analyzer="local")
            explicit = doctor.collect_status(source=LOCAL_VIDEO, analyzer="local", transcriber="none")
        self.assertEqual(implicit["transcriber"], "local")
        self.assertEqual(explicit["transcriber"], "none")
        for status, needs_asr in ((implicit, True), (explicit, False)):
            model_check = next(c for c in status["checks"] if c["name"] == "local-models")
            self.assertEqual("speech-to-text" in model_check["message"], needs_asr)

    def test_local_endpoint_rejects_remote_urls_without_echoing_secrets(self):
        values = (
            "https://host.invalid/v1",
            "http://user:fixture-secret@127.0.0.1:8147/v1",
            "http://127.0.0.1:8147/v1?api_key=fixture-secret",
        )
        with mock.patch.object(doctor.shutil, "which", return_value="/fixture/bin"):
            for endpoint in values:
                with self.subTest(endpoint=endpoint), mock.patch.dict(os.environ, {
                    "WATCH_VIDEO_LOCAL_BASE_URL": endpoint,
                    "WATCH_VIDEO_LOCAL_API_KEY": "fixture-private-key",
                }):
                    code, output, errors = self.cli(
                        LOCAL_VIDEO, "--transcriber", "local", "--json",
                    )
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(output)["ok"])
                self.assertNotIn(endpoint, output + errors)
                self.assertNotIn("fixture-secret", output + errors)
                self.assertNotIn("fixture-private-key", output + errors)

    def test_unused_local_runtime_does_not_make_extraction_fail(self):
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_BASE_URL": "https://host.invalid/v1"}), \
                mock.patch.object(doctor.shutil, "which", return_value="/fixture/bin"):
            code, output, _ = self.cli(LOCAL_VIDEO, "--transcriber", "none", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(any(c["name"] == "local-endpoint" for c in json.loads(output)["checks"]))

    def test_gemini_rejects_local_model_options_before_installing(self):
        with mock.patch.object(doctor, "install_missing") as install:
            for option in ("--transcriber", "--analyzer"):
                with self.subTest(option=option), self.assertRaises(SystemExit) as error:
                    self.cli(YOUTUBE, "--engine", "gemini", option, "local", "--install")
                self.assertEqual(error.exception.code, 2)
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
