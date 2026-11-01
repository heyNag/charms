"""First-time hardware guidance works without apps, credentials, or a server."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills/watch-video/scripts"))

import local_preflight as preflight  # noqa: E402
import local_config  # noqa: E402
import network_guard  # noqa: E402
import setup_local  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


@contextlib.contextmanager
def host(*, chip="Apple M1 Max", memory=64, system="Darwin", architecture="arm64",
         version="27.0", translated="0"):
    values = {"machdep.cpu.brand_string": chip,
              "hw.memsize": str(memory * 1024**3) if memory is not None else None,
              "sysctl.proc_translated": translated}
    with mock.patch.object(preflight.platform, "system", return_value=system), \
            mock.patch.object(preflight.platform, "machine", return_value=architecture), \
            mock.patch.object(preflight.platform, "mac_ver", return_value=(version, (), "")), \
            mock.patch.object(preflight, "_sysctl", side_effect=values.get) as query:
        yield query


class HardwareTests(unittest.TestCase):
    def test_m1_m2_and_m3_builds_keep_ram_as_observation(self):
        for chip, memory, expected in (("Apple M1 Max", 64, "splash-m1"),
                                      ("Apple M2 Ultra", 192, "splash-m1"),
                                      ("Apple M3 Max", 36, "splash"),
                                      ("Apple M4", 16, "splash")):
            with self.subTest(chip=chip), host(chip=chip, memory=memory):
                data = preflight.detect_hardware()
            self.assertEqual(data["preferred_splash"], expected)
            self.assertEqual(data["memory_bytes"], memory * 1024**3)
            self.assertEqual(data["memory_gib"], memory)
            self.assertEqual(data["support"], "supported")
            self.assertNotIn("model", data)
            self.assertNotIn("memory_limit", data)

    def test_rosetta_uses_chip_generation_not_process_architecture(self):
        with host(chip="Apple M3 Max", architecture="x86_64", translated=None):
            data = preflight.detect_hardware()
        self.assertEqual(data["preferred_splash"], "splash")
        self.assertTrue(data["rosetta"])
        self.assertEqual(data["support"], "supported")

    def test_non_mac_does_not_query_sysctl(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), host(system=system) as query:
                data = preflight.detect_hardware()
                query.assert_not_called()
            self.assertEqual(data["support"], "unsupported")
            self.assertIsNone(data["preferred_splash"])

    def test_unknown_chip_never_guesses_launcher(self):
        for chip in (None, "Apple Silicon", "VirtualApple", "Unknown CPU"):
            with self.subTest(chip=chip), host(chip=chip):
                data = preflight.detect_hardware()
            self.assertEqual(data["support"], "unknown")
            self.assertIsNone(data["preferred_splash"])

    def test_intel_mac_is_not_apple_silicon_setup(self):
        with host(chip="Intel(R) Core(TM) i7", architecture="x86_64"):
            data = preflight.detect_hardware()
        self.assertEqual(data["support"], "unsupported")
        self.assertIsNone(data["preferred_splash"])

    def test_old_macos_and_unknown_version_have_explicit_outcomes(self):
        for version, expected in (("15.7.1", "unsupported"), ("26.3", "unsupported"),
                                  ("26.4", "supported"), ("", "unknown"), ("invalid", "unknown")):
            with self.subTest(version=version), host(version=version):
                data = preflight.detect_hardware()
            self.assertEqual(data["support"], expected)

    def test_unavailable_memory_stays_unknown(self):
        with host(memory=None):
            data = preflight.detect_hardware()
        self.assertIsNone(data["memory_bytes"])
        self.assertIsNone(data["memory_gib"])

    def test_hardware_subprocess_is_fixed_bounded_and_handles_failure(self):
        reply = subprocess.CompletedProcess([], 0, "Apple M1 Max\n", "")
        with mock.patch.object(preflight.subprocess, "run", return_value=reply) as run:
            self.assertEqual(preflight._sysctl("machdep.cpu.brand_string"), "Apple M1 Max")
        run.assert_called_once_with(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
                                    capture_output=True, text=True, check=False, timeout=3)
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("sysctl", 3)):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(preflight.subprocess, "run", side_effect=error):
                self.assertIsNone(preflight._sysctl("hw.memsize"))
        with mock.patch.object(preflight.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "private stderr")):
            self.assertIsNone(preflight._sysctl("hw.memsize"))
        with self.assertRaises(ValueError):
            preflight._sysctl("hw.serialnumber")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = str(self.home / "Applications/oMLX.app")
        self.binaries = {name: str(self.home / "bin" / name) for name in ("ffmpeg", "ffprobe")}
        self.launchers = {"splash-m1": str(self.home / ".local/bin/splash-m1"), "splash": None}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(preflight.Path, "home", return_value=self.home))
        self.stack.enter_context(mock.patch.object(preflight, "_find_app", side_effect=lambda _home: self.app))
        self.stack.enter_context(mock.patch.object(preflight, "_find_launcher", side_effect=lambda name, _home: self.launchers[name]))
        self.stack.enter_context(mock.patch.object(preflight.shutil, "which", side_effect=self.binaries.get))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "WATCH_VIDEO_CONFIG_DIR": str(self.home / ".config/watch-video"),
        }, clear=True))

    def test_present_prerequisites_still_require_runtime_check(self):
        with host():
            result = preflight.preflight()
        self.assertEqual(result["status"], "requires_runtime_check")
        self.assertEqual(result["runtime"]["server_state"], "not_checked")
        self.assertEqual(result["runtime"]["models"], "not_checked")
        self.assertEqual(result["connection"]["authentication"], "not_checked")
        self.assertFalse(result["blockers"])
        self.assertIsNone(result["binaries"]["yt-dlp"])
        self.assertIsNone(result["binaries"]["op"])
        self.assertIsNone(result["binaries"]["brew"])
        self.assertNotIn("model_fit", result)
        self.assertEqual([step["id"] for step in result["next_steps"]],
                         ["connection", "server", "runtime_check", "models", "smoke_test"])

    def test_fresh_mac_reports_ordered_setup_without_api_or_files(self):
        self.app = None
        self.launchers["splash-m1"] = None
        self.binaries.clear()
        before = list(self.home.rglob("*"))
        with host(), mock.patch.object(setup_local, "AdminClient", side_effect=AssertionError("API client constructed")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight", "--json"])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "needs_setup")
        self.assertEqual([step["id"] for step in result["next_steps"]][:3], ["ffmpeg", "omlx", "splash"])
        self.assertEqual(result["runtime"]["preferred_splash"], "splash-m1")
        self.assertEqual(before, list(self.home.rglob("*")))

    def test_m3_guidance_uses_official_splash_and_same_model_workflow(self):
        with host(chip="Apple M3 Max", memory=36):
            result = preflight.preflight()
        self.assertEqual(result["status"], "needs_setup")
        self.assertEqual(result["runtime"]["preferred_splash"], "splash")
        step = next(step for step in result["next_steps"] if step["id"] == "splash")
        self.assertIn("brew install incoai/tap/splash", step["instruction"])
        self.assertEqual(result["connection"]["model_directory"], str((self.home / ".omlx/models").resolve()))
        self.assertNotIn("model_repo", json.dumps(result))

    def test_secret_and_config_contents_are_never_read_or_printed(self):
        env_file = self.home / ".config/watch-video/local.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("SECRET_FILE_CONTENT=not-for-output")
        with host(), mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_API_KEY": "super-secret-key"}), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("Read config contents")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("Read config contents")), \
                mock.patch.object(local_config, "read_config", side_effect=AssertionError("Read config contents")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight", "--json"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["connection"]["api_key_in_environment"])
        self.assertTrue(result["connection"]["local_env_file_present"])
        self.assertEqual(result["connection"]["base_url_source"], "default")
        self.assertTrue(any("endpoint may differ" in warning for warning in result["warnings"]))
        self.assertNotIn("super-secret-key", output.getvalue())
        self.assertNotIn("SECRET_FILE_CONTENT", output.getvalue())
        self.assertNotIn("not-for-output", output.getvalue())

    def test_endpoint_and_model_directory_overrides_are_preserved(self):
        custom = self.home / "Common Models"
        with host(), mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_BASE_URL": "http://localhost:9001/v1"}):
            result = preflight.preflight(model_dir=custom)
            override = preflight.preflight(base_url="http://[::1]:9002/v1", model_dir=custom)
        self.assertEqual(result["connection"]["base_url"], "http://127.0.0.1:9001/v1")
        self.assertEqual(result["connection"]["base_url_source"], "environment")
        self.assertEqual(override["connection"]["base_url"], "http://[::1]:9002/v1")
        self.assertEqual(override["connection"]["base_url_source"], "argument")
        self.assertEqual(result["connection"]["model_directory"], str(custom.resolve()))
        self.assertFalse(custom.exists())

    def test_invalid_endpoint_has_safe_error_without_network(self):
        with mock.patch.object(setup_local, "AdminClient", side_effect=AssertionError("API client constructed")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight", "--base-url", "http://secret@outside.example/v1", "--json"])
        self.assertEqual(code, 1)
        self.assertNotIn("secret@", output.getvalue())
        self.assertNotIn("outside.example", output.getvalue())
        self.assertIn("loopback", output.getvalue())

    def test_python_version_is_checked_without_changing_interpreter(self):
        with host(), mock.patch.object(preflight.sys, "version_info", (3, 10, 16)):
            result = preflight.preflight()
        self.assertEqual(result["status"], "needs_setup")
        self.assertEqual(result["python"], {"version": "3.10.16", "ok": False})
        self.assertEqual(result["next_steps"][0]["id"], "python")

    def test_unsupported_host_does_not_propose_app_or_model_installs(self):
        with host(system="Linux"), contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight", "--json"])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "unsupported")
        self.assertFalse({"omlx", "splash", "models"} & {step["id"] for step in result["next_steps"]})

    def test_rosetta_and_missing_memory_are_uncertainties_not_model_changes(self):
        with host(architecture="x86_64", memory=None):
            result = preflight.preflight()
        self.assertEqual(result["status"], "requires_runtime_check")
        self.assertTrue(any("Rosetta" in warning for warning in result["warnings"]))
        self.assertTrue(any("memory" in warning for warning in result["warnings"]))
        self.assertIn("do not prove model fit", result["note"])

    def test_friendly_output_has_hardware_build_and_next_steps(self):
        with host(), contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight"])
        self.assertEqual(code, 0)
        text = output.getvalue()
        for expected in ("Apple M1 Max", "64 GiB", "splash-m1", "Next steps:", "requires_runtime_check"):
            self.assertIn(expected, text)

    def test_modes_are_exclusive_and_wait_requires_configure(self):
        for flag in ("--check", "--configure"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                setup_local.main(["--preflight", flag])
            self.assertEqual(error.exception.code, 2)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--preflight", "--wait", "10", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("--wait requires --configure", output.getvalue())

    def test_init_config_creates_private_blank_template_without_api_or_hardware(self):
        with mock.patch.object(setup_local, "AdminClient", side_effect=AssertionError("API client constructed")), \
                mock.patch.object(setup_local, "preflight", side_effect=AssertionError("Hardware check run")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--init-config", "--json"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "created")
        config = Path(result["path"])
        self.assertEqual(config, self.home / ".config/watch-video/local.env")
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertIn("WATCH_VIDEO_LOCAL_API_KEY=\n", config.read_text())
        self.assertNotIn("WATCH_VIDEO_LOCAL_API_KEY", output.getvalue())

    def test_init_config_preserves_existing_file_and_never_prints_contents(self):
        config = self.home / ".config/watch-video/local.env"
        config.parent.mkdir(parents=True)
        config.write_text("WATCH_VIDEO_LOCAL_API_KEY=private-fixture-value\n")
        before = config.read_bytes()
        with mock.patch.object(setup_local, "AdminClient", side_effect=AssertionError("API client constructed")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--init-config"])
        self.assertEqual(code, 0)
        self.assertEqual(before, config.read_bytes())
        self.assertIn("exists", output.getvalue())
        self.assertNotIn("private-fixture-value", output.getvalue())

    def test_init_config_is_exclusive_and_does_not_accept_wait(self):
        for flag in ("--check", "--configure", "--preflight"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                setup_local.main(["--init-config", flag])
            self.assertEqual(error.exception.code, 2)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = setup_local.main(["--init-config", "--wait", "10", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("--wait requires --configure", output.getvalue())


class DiscoveryTests(unittest.TestCase):
    def test_user_app_location_is_supported_without_launching(self):
        home = Path("/test/home")
        expected = home / "Applications/oMLX.app"
        with mock.patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path == expected):
            self.assertEqual(preflight._find_app(home), str(expected))

    def test_launcher_fallback_in_user_bin_without_running_binary(self):
        home = Path("/test/home")
        expected = home / ".local/bin/splash-m1"
        with mock.patch.object(preflight.shutil, "which", return_value=None), \
                mock.patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path == expected), \
                mock.patch.object(preflight.os, "access", return_value=True), \
                mock.patch.object(preflight.subprocess, "run", side_effect=AssertionError("Executed launcher")):
            self.assertEqual(preflight._find_launcher("splash-m1", home), str(expected))

    def test_disk_space_uses_existing_ancestor_without_creating_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "not-created/models"
            with mock.patch.object(preflight.shutil, "disk_usage", return_value=shutil_disk(100, 50, 50)) as usage:
                self.assertEqual(preflight._disk_space(root), 50)
            usage.assert_called_once_with(Path(temporary))
            self.assertFalse(root.exists())


def shutil_disk(total, used, free):
    return type("DiskUsage", (), {"total": total, "used": used, "free": free})()


if __name__ == "__main__":
    unittest.main()
