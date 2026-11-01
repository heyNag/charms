"""Local file onboarding and runtime precedence without secret-manager dependencies."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "skills/watch-video/scripts"))

import doctor  # noqa: E402
import local_analyze  # noqa: E402
import local_api  # noqa: E402
import local_config as config  # noqa: E402
import local_transcribe  # noqa: E402
import watch  # noqa: E402


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ, {
            "WATCH_VIDEO_CONFIG_DIR": str(self.root / "settings"),
        }, clear=True))

    def write_config(self, text, mode=0o600):
        path = config.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def test_private_template_contains_defaults_and_no_generated_key(self):
        result = config.create_config_template()
        path = Path(result["path"])
        self.assertEqual(result["status"], "created")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        values = config.read_config()
        self.assertEqual(set(values), config.CONFIG_KEYS)
        self.assertEqual(values["WATCH_VIDEO_LOCAL_API_KEY"], "")
        self.assertEqual(values["WATCH_VIDEO_LOCAL_BASE_URL"], local_api.DEFAULT_BASE_URL)

    def test_default_path_uses_home_and_override_stays_outside_package(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(Path, "home", return_value=self.root):
            self.assertEqual(config.config_path(), self.root / ".config/watch-video/local.env")
        self.assertEqual(config.config_path(), self.root / "settings/local.env")

    def test_existing_config_is_preserved_without_reading_its_contents(self):
        path = self.write_config("KEEP PRIVATE\n", mode=0o400)
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
            self.assertEqual(config.create_config_template()["status"], "exists")
        self.assertEqual(path.read_text(), "KEEP PRIVATE\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)

    def test_symlink_is_never_read_or_overwritten(self):
        target = self.root / "target"
        target.write_text("unchanged")
        path = config.config_path()
        path.parent.mkdir()
        path.symlink_to(target)
        for operation in (config.create_config_template, config.read_config):
            with self.subTest(operation=operation.__name__), self.assertRaises(config.LocalConfigError):
                operation()
        self.assertEqual(target.read_text(), "unchanged")

    def test_nonregular_configuration_is_refused(self):
        path = config.config_path()
        path.mkdir(parents=True)
        for operation in (config.create_config_template, config.read_config):
            with self.subTest(operation=operation.__name__), self.assertRaises(config.LocalConfigError):
                operation()

    def test_absent_file_uses_defaults_without_creating_anything(self):
        self.assertEqual(config.read_config(), {})
        self.assertEqual(config.get_setting("WATCH_VIDEO_LOCAL_MODEL", "fallback"), "fallback")
        self.assertEqual(config.resolve_api_key(), "")
        self.assertFalse(config.config_path().parent.exists())

    def test_loose_permissions_are_rejected_without_echo(self):
        self.write_config("WATCH_VIDEO_LOCAL_API_KEY=hidden-fixture\n", mode=0o644)
        with self.assertRaisesRegex(config.LocalConfigError, "600") as caught:
            config.resolve_api_key()
        self.assertNotIn("hidden-fixture", str(caught.exception))

    def test_environment_and_explicit_values_override_file(self):
        self.write_config("WATCH_VIDEO_LOCAL_BASE_URL=http://127.0.0.1:8123/v1\n"
                          "WATCH_VIDEO_LOCAL_API_KEY=file-secret\n"
                          "WATCH_VIDEO_LOCAL_ASR_MODEL=file-asr\n"
                          "WATCH_VIDEO_LOCAL_MODEL=file-vision\n")
        self.assertEqual(local_api.LocalClient().base_url, "http://127.0.0.1:8123/v1")
        self.assertEqual(local_api.LocalClient()._api_key, "file-secret")
        self.assertEqual(local_transcribe.default_model(), "file-asr")
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_BASE_URL": "http://localhost:9123/v1",
                                         "WATCH_VIDEO_LOCAL_API_KEY": "env-secret",
                                         "WATCH_VIDEO_LOCAL_ASR_MODEL": "env-asr"}):
            self.assertEqual(local_api.LocalClient().base_url, "http://127.0.0.1:9123/v1")
            self.assertEqual(local_api.LocalClient()._api_key, "env-secret")
            self.assertEqual(local_transcribe.default_model(), "env-asr")
            client = local_api.LocalClient("http://localhost:9222/v1", "argument-secret")
            self.assertEqual(client.base_url, "http://127.0.0.1:9222/v1")
            self.assertEqual(client._api_key, "argument-secret")
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_API_KEY": ""}):
            self.assertEqual(config.resolve_api_key(), "")

    def test_environment_key_does_not_need_to_read_file(self):
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_API_KEY": "injected"}), \
                mock.patch.object(config, "read_config", side_effect=AssertionError("file read")):
            self.assertEqual(config.resolve_api_key(), "injected")

    def test_literals_quotes_and_comments_do_not_execute_or_expand(self):
        literal = "$(touch /tmp/do-not-create) ${HOME} `command` # literal"
        self.write_config(f'WATCH_VIDEO_LOCAL_API_KEY="{literal}"\n'
                          "WATCH_VIDEO_LOCAL_MODEL='vision-model'\n"
                          "WATCH_VIDEO_LOCAL_ASR_MODEL=asr-model # comment\n")
        with mock.patch("subprocess.run", side_effect=AssertionError("no subprocess")), \
                mock.patch("os.system", side_effect=AssertionError("no shell")):
            values = config.read_config()
        self.assertEqual(values["WATCH_VIDEO_LOCAL_API_KEY"], literal)
        self.assertEqual(values["WATCH_VIDEO_LOCAL_MODEL"], "vision-model")
        self.assertEqual(values["WATCH_VIDEO_LOCAL_ASR_MODEL"], "asr-model")

    def test_unresolved_secret_reference_needs_explicit_manager_injection(self):
        reference = "op://private-fixture/item-fixture/password"
        self.write_config(f'WATCH_VIDEO_LOCAL_API_KEY="{reference}"\n')
        with self.assertRaisesRegex(config.LocalConfigError, "unresolved secret reference") as caught:
            local_api.LocalClient()
        self.assertNotIn(reference, str(caught.exception))
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_API_KEY": "injected-key"}):
            self.assertEqual(local_api.LocalClient()._api_key, "injected-key")

    def test_invalid_input_errors_do_not_echo_values(self):
        samples = ["UNKNOWN_SECRET=private-fixture\n", "private-fixture\n",
                   "WATCH_VIDEO_LOCAL_API_KEY='private-fixture\n",
                   "WATCH_VIDEO_LOCAL_API_KEY=private-fixture\x00\n",
                   "WATCH_VIDEO_LOCAL_API_KEY=private-fixture\nWATCH_VIDEO_LOCAL_API_KEY=again\n"]
        for text in samples:
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(config.LocalConfigError) as caught:
                    config.read_config()
                self.assertNotIn("private-fixture", str(caught.exception))

    def test_configuration_has_a_size_and_encoding_bound(self):
        path = self.write_config("#" * (config.MAX_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(config.LocalConfigError, "size limit"):
            config.read_config()
        path.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(config.LocalConfigError, "UTF-8"):
            config.read_config()

    def test_file_endpoint_keeps_loopback_enforcement(self):
        self.write_config("WATCH_VIDEO_LOCAL_BASE_URL=https://private-fixture@example.com/v1\n")
        with self.assertRaises(ValueError) as caught:
            local_api.LocalClient()
        self.assertNotIn("private-fixture", str(caught.exception))

    def test_file_key_is_only_an_auth_header_and_echoes_are_redacted(self):
        self.write_config("WATCH_VIDEO_LOCAL_API_KEY=file-secret\n")
        client = local_api.LocalClient()
        opened = mock.MagicMock()
        opened.__enter__.return_value.read.return_value = b'{"message":"echo file-secret"}'
        with mock.patch.object(client._opener, "open", return_value=opened) as request:
            result = client.request_json("models")
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer file-secret")
        self.assertNotIn("file-secret", request.call_args.args[0].full_url)
        self.assertNotIn("file-secret", json.dumps(result))
        self.assertEqual(local_analyze._redact("echo file-secret", None), "echo [REDACTED]")

    def test_analyzer_uses_file_model_and_preserves_redaction(self):
        self.write_config("WATCH_VIDEO_LOCAL_MODEL=file-vision\nWATCH_VIDEO_LOCAL_API_KEY=file-secret\n")
        run = self.root / "run"
        run.mkdir()
        (run / "evidence.json").write_text(json.dumps({"source": "sample.mp4", "frames": [],
                                                      "range": {"start_seconds": 0, "end_seconds": 5}}))
        (run / "transcript.json").write_text(json.dumps({"source": "local_whisper", "segments": [
            {"start": 0, "end": 1, "text": "test audio"}]}))
        client = mock.Mock()
        client.request_json.side_effect = RuntimeError("failure echo file-secret")
        with mock.patch.object(local_analyze, "LocalClient", return_value=client), \
                contextlib.redirect_stdout(io.StringIO()):
            result = local_analyze.analyze_local(run)
        self.assertEqual(result["model"], "file-vision")
        self.assertEqual(client.request_json.call_args.args[1]["model"], "file-vision")
        for p in run.rglob("*"):
            if p.is_file():
                self.assertNotIn("file-secret", p.read_text())

    def test_doctor_reports_file_configuration_without_the_key(self):
        self.write_config("WATCH_VIDEO_LOCAL_BASE_URL=http://localhost:9123/v1\n"
                          "WATCH_VIDEO_LOCAL_API_KEY=file-secret\n")
        checks = doctor.check_local_runtime("local", "local")
        by_name = {row["name"]: row for row in checks}
        self.assertIn("127.0.0.1:9123", by_name["local-endpoint"]["message"])
        self.assertTrue(by_name["WATCH_VIDEO_LOCAL_API_KEY"]["ok"])
        self.assertIn("local.env", by_name["WATCH_VIDEO_LOCAL_API_KEY"]["message"])
        self.assertNotIn("file-secret", json.dumps(checks))

    def test_doctor_flags_invalid_config_and_unresolved_reference_safely(self):
        self.write_config('WATCH_VIDEO_LOCAL_API_KEY="op://private-fixture/item/password"\n')
        checks = doctor.check_local_runtime("local", "local")
        self.assertTrue(any(row["name"] == "local-config" and not row["ok"] for row in checks))
        self.assertNotIn("private-fixture", json.dumps(checks))
        config.config_path().chmod(0o644)
        checks = doctor.check_local_runtime("local", "local")
        self.assertFalse(next(row for row in checks if row["name"] == "local-endpoint")["ok"])

    def test_preflight_url_validation_does_not_read_the_file(self):
        with mock.patch.object(config, "read_config", side_effect=AssertionError("secret file read")):
            self.assertEqual(local_api.validate_base_url(), local_api.DEFAULT_BASE_URL)

    def test_watch_reports_bad_local_configuration_before_media_or_artifacts(self):
        invalid_cases = [
            ("WATCH_VIDEO_LOCAL_API_KEY=private-fixture\n", 0o644),
            ("WATCH_VIDEO_LOCAL_API_KEY='private-fixture\n", 0o600),
            ("WATCH_VIDEO_LOCAL_API_KEY=op://private-fixture/item/field\n", 0o600),
            ("WATCH_VIDEO_LOCAL_BASE_URL=http://private-fixture@example.com/v1\n", 0o600),
        ]
        for content, mode in invalid_cases:
            with self.subTest(content=content, mode=mode):
                self.write_config(content, mode)
                with mock.patch.object(sys, "argv", ["watch.py", "meeting.mp4", "--analyzer", "local"]), \
                        mock.patch.object(watch, "create_run_dir") as create, \
                        mock.patch.object(watch, "run_source") as run, \
                        self.assertRaises(SystemExit) as caught:
                    watch.main()
                self.assertNotIn("private-fixture", str(caught.exception))
                create.assert_not_called()
                run.assert_not_called()

    def test_watch_preserves_explicit_model_overrides_and_skips_config_for_extraction(self):
        self.write_config("WATCH_VIDEO_LOCAL_MODEL=file-vision\nWATCH_VIDEO_LOCAL_ASR_MODEL=file-asr\n")
        with mock.patch.object(sys, "argv", ["watch.py", "meeting.mp4", "--analyzer", "local",
                                             "--local-model", "chosen-vision", "--local-asr-model", "chosen-asr"]), \
                mock.patch.object(watch, "create_run_dir", return_value=self.root), \
                mock.patch.object(watch, "run_source", return_value=0) as run:
            self.assertEqual(watch.main(), 0)
        args = run.call_args.args[0]
        self.assertEqual(args.local_model, "chosen-vision")
        self.assertEqual(args.local_asr_model, "chosen-asr")
        with mock.patch.object(sys, "argv", ["watch.py", "meeting.mp4", "--transcriber", "none"]), \
                mock.patch.object(watch, "create_run_dir", return_value=self.root), \
                mock.patch.object(watch, "run_source", return_value=0), \
                mock.patch.object(config, "read_config", side_effect=AssertionError("unrequested local settings")):
            self.assertEqual(watch.main(), 0)


if __name__ == "__main__":
    unittest.main()
