"""Everything that reports a version reads it from the plugin's manifest."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS_DIR))

import groq_transcribe as groq  # noqa: E402
import local_api  # noqa: E402
import network_guard  # noqa: E402
import plugin_version  # noqa: E402

RELEASED = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
MAIN_GUARD = re.compile(r"""^if __name__ == ["']__main__["']:""", re.MULTILINE)


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


class ManifestTests(unittest.TestCase):
    def test_the_version_is_the_one_in_plugin_json(self) -> None:
        self.assertRegex(RELEASED, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(plugin_version.MANIFEST, PLUGIN_ROOT / "plugin.json")
        self.assertEqual(plugin_version.VERSION, RELEASED)
        self.assertEqual(plugin_version.VERSION_LINE, f"watch-video {RELEASED}")
        self.assertEqual(plugin_version.USER_AGENT, f"charms-watch-video/{RELEASED}")

    def test_a_manifest_that_is_missing_or_not_this_plugins_gives_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "plugin.json"
            self.assertEqual(plugin_version.read_version(manifest), "unknown")
            for content in (
                "{not json", "[]", '"1.2.3"',
                json.dumps({"name": "another-plugin", "version": "1.2.3"}),
                json.dumps({"name": "watch-video"}),
                json.dumps({"name": "watch-video", "version": 5}),
                json.dumps({"name": "watch-video", "version": "1.2"}),
                json.dumps({"name": "watch-video", "version": "v1.2.3"}),
                json.dumps({"name": "watch-video", "version": "1.2.3-beta.1"}),
                json.dumps({"name": "watch-video", "version": "1.2.3\n"}),
                json.dumps({"name": "watch-video", "version": "1.2.3", "pad": "x" * (1024 * 1024)}),
            ):
                with self.subTest(content=content[:60]):
                    manifest.write_text(content, encoding="utf-8")
                    self.assertEqual(plugin_version.read_version(manifest), "unknown")
            manifest.write_bytes(b"\xff\xfe")
            self.assertEqual(plugin_version.read_version(manifest), "unknown")
            manifest.write_text(json.dumps({"name": "watch-video", "version": "9.8.7"}), encoding="utf-8")
            self.assertEqual(plugin_version.read_version(manifest), "9.8.7")


class CommandTests(unittest.TestCase):
    def test_every_command_prints_the_version(self) -> None:
        commands = sorted(
            path for path in SCRIPTS.glob("*.py")
            if MAIN_GUARD.search(path.read_text(encoding="utf-8"))
        )
        self.assertIn("watch.py", [path.name for path in commands])
        for script in commands:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [sys.executable, str(script), "--version"],
                    capture_output=True, text=True, timeout=60, check=False,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr),
                    (0, f"watch-video {RELEASED}\n", ""),
                )


class RequestTests(unittest.TestCase):
    def test_hosted_transcription_requests_name_the_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.mp3"
            audio.write_bytes(b"audio")
            reply = io.BytesIO(json.dumps({"segments": []}).encode())
            with mock.patch.object(groq, "_open_without_redirects", return_value=reply) as upload:
                groq.transcribe_audio(audio, api_key="test-placeholder")
        self.assertEqual(
            upload.call_args.args[0].get_header("User-agent"), f"charms-watch-video/{RELEASED}",
        )

    def test_local_model_requests_name_the_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"WATCH_VIDEO_CONFIG_DIR": temporary}, clear=True,
        ):
            client = local_api.LocalClient(base_url="http://127.0.0.1:8147/v1", api_key="test-placeholder")
            opened = mock.MagicMock()
            opened.__enter__.return_value.read.return_value = b'{"data": []}'
            with mock.patch.object(client._opener, "open", return_value=opened) as request:
                client.request_json("models")
        self.assertEqual(
            request.call_args.args[0].get_header("User-agent"), f"charms-watch-video/{RELEASED}",
        )


if __name__ == "__main__":
    unittest.main()
