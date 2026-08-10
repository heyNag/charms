import datetime as dt
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-plugin-version.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bump_plugin_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_plugin(
    root: pathlib.Path,
    version: str = "2026.8.10",
    name: str = "demo-plugin",
) -> pathlib.Path:
    package_dir = root / "packages" / name
    package_dir.mkdir(parents=True)
    path = package_dir / "plugin.json"
    path.write_text(json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8")
    return path


class BumpPluginVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.release_date = dt.date(2026, 8, 10)

    def test_base_version_uses_four_digit_year_and_unpadded_month_day(self):
        self.assertEqual(self.module.base_version(self.release_date), "2026.8.10")
        self.assertEqual(self.module.base_version(dt.date(1, 2, 3)), "0001.2.3")

    def test_current_preserves_valid_date_version(self):
        self.assertEqual(
            self.module.next_version("2026.8.10.3", "current", self.release_date),
            "2026.8.10.3",
        )

    def test_date_mode_uses_new_utc_date(self):
        self.assertEqual(
            self.module.next_version("2026.8.9.2", "date", self.release_date),
            "2026.8.10",
        )

    def test_date_mode_adds_and_increments_same_day_sequence(self):
        self.assertEqual(
            self.module.next_version("2026.8.10", "date", self.release_date),
            "2026.8.10.1",
        )
        self.assertEqual(
            self.module.next_version("2026.8.10.1", "date", self.release_date),
            "2026.8.10.2",
        )

    def test_rejects_non_calver_and_invalid_dates(self):
        versions = [
            "1.0.0",
            "2026.08.10",
            "2026.8.010",
            "2026.8.10.0",
            "2026.8.10-beta",
            "2026.2.30",
            "0000.1.1",
            "２０２６.8.10",
        ]
        for version in versions:
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.module.parse_version(version)

    def test_rejects_release_date_before_current_version_date(self):
        with self.assertRaisesRegex(ValueError, "precedes current version date"):
            self.module.next_version("2026.8.11", "date", self.release_date)

    def test_update_package_changes_only_portable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root, version="2026.8.9")

            version = self.module.update_package(
                root,
                "demo-plugin",
                "date",
                self.release_date,
                dry_run=False,
            )

            self.assertEqual(version, "2026.8.10")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "2026.8.10",
            )

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)

            version = self.module.update_package(
                root,
                "demo-plugin",
                "date",
                self.release_date,
                dry_run=True,
            )

            self.assertEqual(version, "2026.8.10.1")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "2026.8.10",
            )

    def test_current_mode_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)

            version = self.module.update_package(
                root,
                "demo-plugin",
                "current",
                self.release_date,
                dry_run=False,
            )

            self.assertEqual(version, "2026.8.10")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "2026.8.10",
            )

    def test_main_allows_current_mode_outside_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            write_plugin(root)
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stdout"):
                code = self.module.main(
                    ["demo-plugin", "--mode", "current", "--root", str(root)]
                )
            self.assertEqual(code, 0)

    def test_main_refuses_local_date_write_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root, version="2026.8.9")
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stderr"):
                code = self.module.main(
                    [
                        "demo-plugin",
                        "--mode",
                        "date",
                        "--date",
                        "2026-08-10",
                        "--root",
                        str(root),
                    ]
                )

            self.assertEqual(code, 1)
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "2026.8.9",
            )

    def test_main_allows_date_write_in_release_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root, version="2026.8.9")
            env = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_WORKFLOW": "Release Plugin",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
            }
            with mock.patch.dict("os.environ", env, clear=True), mock.patch("sys.stdout"):
                code = self.module.main(
                    [
                        "demo-plugin",
                        "--mode",
                        "date",
                        "--date",
                        "2026-08-10",
                        "--root",
                        str(root),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "2026.8.10",
            )

    def test_plugin_name_matches_agent_plugins_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            write_plugin(root, name="a")
            self.assertEqual(
                self.module.package_plugin_path(root, "a"),
                root / "packages/a/plugin.json",
            )
            invalid_names = ["Uppercase", "-start", "end-", "has--double", "has..dots", "../escape"]
            for name in invalid_names:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.module.package_plugin_path(root, name)

    def test_rejects_symlinked_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = root / "packages/demo-plugin"
            package.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text(
                '{"name":"demo-plugin","version":"2026.8.10"}\n',
                encoding="utf-8",
            )
            os.symlink(outside, package / "plugin.json")

            with self.assertRaisesRegex(ValueError, "not a symlink"):
                self.module.update_package(
                    root,
                    "demo-plugin",
                    "date",
                    self.release_date,
                    dry_run=True,
                )


if __name__ == "__main__":
    unittest.main()
