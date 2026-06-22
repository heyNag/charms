import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-skill-version.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bump_skill_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BumpSkillVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.release_date = dt.date(2026, 6, 21)

    def test_base_version_uses_unpadded_utc_date_parts(self):
        self.assertEqual(self.module.base_version(self.release_date), "2026.6.21")

    def test_next_version_from_non_date_version_uses_release_date(self):
        self.assertEqual(self.module.next_version("0.1.0", self.release_date), "2026.6.21")

    def test_next_version_adds_same_day_sequence(self):
        self.assertEqual(self.module.next_version("2026.6.21", self.release_date), "2026.6.21.1")
        self.assertEqual(self.module.next_version("2026.6.21.1", self.release_date), "2026.6.21.2")

    def test_next_version_resets_for_new_utc_day(self):
        self.assertEqual(self.module.next_version("2026.6.20.3", self.release_date), "2026.6.21")

    def test_bump_package_updates_plugin_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            plugin_dir = root / "packages" / "x-bookmarks" / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            plugin_path = plugin_dir / "plugin.json"
            plugin_path.write_text(
                json.dumps({"name": "x-bookmarks", "version": "2026.6.21"}) + "\n",
                encoding="utf-8",
            )

            version = self.module.bump_package(root, "x-bookmarks", self.release_date, dry_run=False)

            self.assertEqual(version, "2026.6.21.1")
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "2026.6.21.1")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            plugin_dir = root / "packages" / "x-bookmarks" / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            plugin_path = plugin_dir / "plugin.json"
            plugin_path.write_text(
                json.dumps({"name": "x-bookmarks", "version": "0.1.0"}) + "\n",
                encoding="utf-8",
            )

            version = self.module.bump_package(root, "x-bookmarks", self.release_date, dry_run=True)

            self.assertEqual(version, "2026.6.21")
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "0.1.0")

    def test_main_refuses_local_write_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            plugin_dir = root / "packages" / "x-bookmarks" / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            plugin_path = plugin_dir / "plugin.json"
            plugin_path.write_text(
                json.dumps({"name": "x-bookmarks", "version": "2026.6.21"}) + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stderr"):
                code = self.module.main(["x-bookmarks", "--root", str(root), "--date", "2026-06-21"])

            self.assertEqual(code, 1)
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "2026.6.21")

    def test_main_allows_write_in_release_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            plugin_dir = root / "packages" / "x-bookmarks" / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            plugin_path = plugin_dir / "plugin.json"
            plugin_path.write_text(
                json.dumps({"name": "x-bookmarks", "version": "2026.6.21"}) + "\n",
                encoding="utf-8",
            )

            env = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_WORKFLOW": "Release Skill",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
            }
            with mock.patch.dict("os.environ", env, clear=True), mock.patch("sys.stdout"):
                code = self.module.main(["x-bookmarks", "--root", str(root), "--date", "2026-06-21"])

            self.assertEqual(code, 0)
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "2026.6.21.1")


if __name__ == "__main__":
    unittest.main()
