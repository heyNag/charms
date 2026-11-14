"""Everything that reports a version reads it from the plugin's manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR))

from test_basic import SCRIPTS, load_module  # noqa: E402
from test_python_floor import commands  # noqa: E402

RELEASED = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]


class FakeResponse:
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b'{"data": {"id": "1"}}'


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.version = load_module("plugin_version", SCRIPTS / "plugin_version.py")

    def test_the_version_is_the_one_in_plugin_json(self) -> None:
        self.assertRegex(RELEASED, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(self.version.MANIFEST, PLUGIN_ROOT / "plugin.json")
        self.assertEqual(self.version.VERSION, RELEASED)
        self.assertEqual(self.version.VERSION_LINE, f"x-bookmarks {RELEASED}")
        self.assertEqual(self.version.USER_AGENT, f"charms-x-bookmarks/{RELEASED}")

    def test_a_manifest_that_is_missing_or_not_this_plugins_gives_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "plugin.json"
            self.assertEqual(self.version.read_version(manifest), "unknown")
            for content in (
                "{not json", "[]", '"1.2.3"',
                json.dumps({"name": "another-plugin", "version": "1.2.3"}),
                json.dumps({"name": "x-bookmarks"}),
                json.dumps({"name": "x-bookmarks", "version": 5}),
                json.dumps({"name": "x-bookmarks", "version": "1.2"}),
                json.dumps({"name": "x-bookmarks", "version": "v1.2.3"}),
                json.dumps({"name": "x-bookmarks", "version": "1.2.3-beta.1"}),
                json.dumps({"name": "x-bookmarks", "version": "1.2.3\n"}),
                json.dumps({"name": "x-bookmarks", "version": "1.2.3", "pad": "x" * (1024 * 1024)}),
            ):
                with self.subTest(content=content[:60]):
                    manifest.write_text(content, encoding="utf-8")
                    self.assertEqual(self.version.read_version(manifest), "unknown")
            manifest.write_bytes(b"\xff\xfe")
            self.assertEqual(self.version.read_version(manifest), "unknown")
            manifest.write_text(json.dumps({"name": "x-bookmarks", "version": "9.8.7"}), encoding="utf-8")
            self.assertEqual(self.version.read_version(manifest), "9.8.7")


class CommandTests(unittest.TestCase):
    def test_every_command_prints_the_version(self) -> None:
        for script in commands():
            with self.subTest(script=script.name):
                result = subprocess.run(
                    [sys.executable, str(script), "--version"],
                    capture_output=True, text=True, timeout=60, check=False,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr),
                    (0, f"x-bookmarks {RELEASED}\n", ""),
                )

    def test_api_requests_name_the_version(self) -> None:
        api = load_module("fetch_bookmarks_api_version", SCRIPTS / "fetch_bookmarks_api.py")
        with mock.patch.object(api, "open_request", return_value=FakeResponse()) as opened:
            api.api_get("/users/me", "test-bearer-token")
        self.assertEqual(
            opened.call_args.args[0].get_header("User-agent"), f"charms-x-bookmarks/{RELEASED}",
        )


if __name__ == "__main__":
    unittest.main()
