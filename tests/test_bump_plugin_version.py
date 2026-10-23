import contextlib
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest


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
    version: str = "1.2.3",
    name: str = "demo-plugin",
) -> pathlib.Path:
    package_dir = root / "packages" / name
    package_dir.mkdir(parents=True)
    path = package_dir / "plugin.json"
    path.write_text(
        json.dumps({"name": name, "version": version, "description": "Demo."}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def manifest_version(path: pathlib.Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["version"]


class BumpPluginVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def test_bumps_each_semantic_version_part(self):
        manifest = write_plugin(self.root)
        expected = {"major": "2.0.0", "minor": "1.3.0", "patch": "1.2.4"}
        for part, version in expected.items():
            with self.subTest(part=part):
                self.assertEqual(
                    self.module.update_package(self.root, "demo-plugin", part, dry_run=True),
                    version,
                )
        self.assertEqual(manifest_version(manifest), "1.2.3")

    def test_update_package_writes_only_the_version(self):
        manifest = write_plugin(self.root)

        version = self.module.update_package(self.root, "demo-plugin", "minor", dry_run=False)

        self.assertEqual(version, "1.3.0")
        self.assertEqual(
            json.loads(manifest.read_text(encoding="utf-8")),
            {"name": "demo-plugin", "version": "1.3.0", "description": "Demo."},
        )

    def test_rejects_a_manifest_version_that_is_not_semver(self):
        for version in ["2026.8.10.1", "1.0", "1.0.0-beta", "01.0.0"]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                write_plugin(root, version=version)
                with self.assertRaisesRegex(ValueError, "semantic versioning"):
                    self.module.update_package(root, "demo-plugin", "patch", dry_run=True)

    def test_main_writes_and_prints_the_new_version(self):
        manifest = write_plugin(self.root)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.module.main(["demo-plugin", "major", "--root", str(self.root)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "2.0.0\n")
        self.assertEqual(manifest_version(manifest), "2.0.0")

    def test_main_reports_errors_without_writing(self):
        manifest = write_plugin(self.root, name="demo-plugin")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(["other-plugin", "patch", "--root", str(self.root)])

        self.assertEqual(code, 1)
        self.assertIn("missing plugin directory", stderr.getvalue())
        self.assertEqual(manifest_version(manifest), "1.2.3")

    def test_main_rejects_unknown_part(self):
        write_plugin(self.root)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.module.main(["demo-plugin", "date", "--root", str(self.root)])

    def test_plugin_name_matches_agent_plugins_constraints(self):
        write_plugin(self.root, name="a")
        self.assertEqual(
            self.module.package_plugin_path(self.root, "a"),
            self.root / "packages/a/plugin.json",
        )
        invalid_names = ["Uppercase", "-start", "end-", "has--double", "has..dots", "../escape"]
        for name in invalid_names:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.package_plugin_path(self.root, name)

    def test_rejects_symlinked_manifest(self):
        package = self.root / "packages/demo-plugin"
        package.mkdir(parents=True)
        outside = self.root / "outside.json"
        outside.write_text('{"name":"demo-plugin","version":"1.0.0"}\n', encoding="utf-8")
        os.symlink(outside, package / "plugin.json")

        with self.assertRaisesRegex(ValueError, "not a symlink"):
            self.module.update_package(self.root, "demo-plugin", "patch", dry_run=True)


if __name__ == "__main__":
    unittest.main()
