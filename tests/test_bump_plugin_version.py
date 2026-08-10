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


def write_plugin(root: pathlib.Path, version: str = "1.2.3", name: str = "demo-plugin") -> pathlib.Path:
    package_dir = root / "packages" / name
    package_dir.mkdir(parents=True)
    path = package_dir / "plugin.json"
    path.write_text(json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8")
    return path


class BumpPluginVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_current_preserves_strict_semver(self):
        self.assertEqual(self.module.next_version("1.2.3-beta.1+build.7", "current"), "1.2.3-beta.1+build.7")

    def test_semver_bumps(self):
        self.assertEqual(self.module.next_version("1.2.3", "major"), "2.0.0")
        self.assertEqual(self.module.next_version("1.2.3", "minor"), "1.3.0")
        self.assertEqual(self.module.next_version("1.2.3", "patch"), "1.2.4")

    def test_bump_discards_prerelease_and_build_metadata(self):
        self.assertEqual(self.module.next_version("1.2.3-beta.1+build.7", "patch"), "1.2.4")

    def test_rejects_non_semver_versions(self):
        for version in ["1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03", "v1.2.3"]:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    self.module.parse_version(version)

    def test_update_package_changes_only_portable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)

            version = self.module.update_package(root, "demo-plugin", "minor", dry_run=False)

            self.assertEqual(version, "1.3.0")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "1.3.0")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)

            version = self.module.update_package(root, "demo-plugin", "patch", dry_run=True)

            self.assertEqual(version, "1.2.4")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "1.2.3")

    def test_current_mode_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)

            version = self.module.update_package(root, "demo-plugin", "current", dry_run=False)

            self.assertEqual(version, "1.2.3")
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "1.2.3")

    def test_main_allows_current_mode_outside_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            write_plugin(root)
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stdout"):
                code = self.module.main(
                    ["demo-plugin", "--bump", "current", "--root", str(root)]
                )
            self.assertEqual(code, 0)

    def test_main_refuses_local_write_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stderr"):
                code = self.module.main(
                    ["demo-plugin", "--bump", "patch", "--root", str(root)]
                )

            self.assertEqual(code, 1)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "1.2.3")

    def test_main_allows_write_in_release_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = write_plugin(root)
            env = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_WORKFLOW": "Release Plugin",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
            }
            with mock.patch.dict("os.environ", env, clear=True), mock.patch("sys.stdout"):
                code = self.module.main(
                    ["demo-plugin", "--bump", "major", "--root", str(root)]
                )

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["version"], "2.0.0")

    def test_plugin_name_matches_agent_plugins_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            write_plugin(root, name="a")
            self.assertEqual(self.module.package_plugin_path(root, "a"), root / "packages/a/plugin.json")
            for name in ["Uppercase", "-start", "end-", "has--double", "has..dots", "../escape"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.module.package_plugin_path(root, name)

    def test_rejects_symlinked_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = root / "packages/demo-plugin"
            package.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text('{"name":"demo-plugin","version":"1.0.0"}\n', encoding="utf-8")
            os.symlink(outside, package / "plugin.json")

            with self.assertRaisesRegex(ValueError, "not a symlink"):
                self.module.update_package(root, "demo-plugin", "patch", dry_run=True)


if __name__ == "__main__":
    unittest.main()
