import contextlib
import datetime
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from release_fixtures import commit_all, git, init_repository, isolate_git, write_marketplace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump-plugin-version.py"
TODAY = datetime.date(2027, 3, 15)


def load_module():
    spec = importlib.util.spec_from_file_location("bump_plugin_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_plugin(
    root: pathlib.Path,
    version: str = "2027.2.1",
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
        isolate_git(self)
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        init_repository(self.root)

    def release(self, *versions: str, name: str = "demo-plugin") -> None:
        commit_all(self.root)
        for version in versions:
            git(self.root, "tag", f"{name}--v{version}")

    def bump(self, dry_run: bool = False) -> str:
        return self.module.update_package(self.root, "demo-plugin", TODAY, dry_run=dry_run)

    def test_the_first_release_of_a_month_is_release_zero(self):
        cases = [
            ((), "a plugin that has never been released"),
            (("1.3.1", "1.3.2"), "the first CalVer release after 1.x"),
            (("2027.2.0", "2027.2.1"), "a new month"),
            (("2026.3.4",), "the same month of another year"),
        ]
        for released, label in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                self.root = pathlib.Path(tmp)
                init_repository(self.root)
                write_plugin(self.root)
                self.release(*released)
                self.assertEqual(self.bump(), "2027.3.0")

    def test_counts_the_releases_the_plugin_has_made_this_month(self):
        manifest = write_plugin(self.root, version="2027.3.1")
        self.release("2027.2.6", "2027.3.0", "2027.3.1")
        # Another plugin's releases are not counted.
        self.release("2027.3.7", name="other-plugin")

        self.assertEqual(self.bump(), "2027.3.2")
        self.assertEqual(manifest_version(manifest), "2027.3.2")

    def test_dry_run_prints_the_version_without_writing_it(self):
        manifest = write_plugin(self.root)
        self.release("2027.2.1")

        self.assertEqual(self.bump(dry_run=True), "2027.3.0")
        self.assertEqual(manifest_version(manifest), "2027.2.1")

    def test_update_package_writes_only_the_version(self):
        manifest = write_plugin(self.root)
        self.release("2027.2.1")

        self.assertEqual(self.bump(), "2027.3.0")
        self.assertEqual(
            json.loads(manifest.read_text(encoding="utf-8")),
            {"name": "demo-plugin", "version": "2027.3.0", "description": "Demo."},
        )

    def test_running_it_again_before_the_release_changes_nothing(self):
        manifest = write_plugin(self.root)
        self.release("2027.2.1")
        self.assertEqual(self.bump(), "2027.3.0")
        # Laid out by hand. A second run that wrote the file would lay it out again.
        manifest.write_text('{"name": "demo-plugin", "version": "2027.3.0"}\n', encoding="utf-8")
        before = manifest.read_bytes()

        self.assertEqual(self.bump(), "2027.3.0")
        self.assertEqual(manifest.read_bytes(), before)

    def test_replaces_a_version_of_any_other_form(self):
        for version in ["2.0.0", "2027.3.15", "2026.8.10.1", "1.0.0-beta", "2027.3.9"]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                self.root = pathlib.Path(tmp)
                init_repository(self.root)
                manifest = write_plugin(self.root, version=version)
                self.release("2027.3.0")
                self.assertEqual(self.bump(), "2027.3.1")
                self.assertEqual(manifest_version(manifest), "2027.3.1")

    def test_reads_the_marketplace_when_the_release_tags_were_not_fetched(self):
        manifest = write_plugin(self.root)
        write_marketplace(self.root, [{"name": "demo-plugin", "version": "2027.3.4"}])

        self.assertEqual(self.bump(), "2027.3.5")
        self.assertEqual(manifest_version(manifest), "2027.3.5")

    def test_refuses_when_the_latest_release_names_a_later_month(self):
        manifest = write_plugin(self.root)
        self.release("2027.4.0")

        with self.assertRaisesRegex(ValueError, "2027.4.0 names a month after 2027.3"):
            self.bump()
        self.assertEqual(manifest_version(manifest), "2027.2.1")

    def test_needs_a_git_checkout_to_read_the_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.root = pathlib.Path(tmp)
            manifest = write_plugin(self.root)
            ceiling = {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}
            with mock.patch.dict(os.environ, ceiling):
                with self.assertRaisesRegex(RuntimeError, "git cannot list the release tags"):
                    self.bump()
            self.assertEqual(manifest_version(manifest), "2027.2.1")

    def test_main_writes_and_prints_the_version_for_today_in_utc(self):
        manifest = write_plugin(self.root)
        self.release("2027.3.0")
        stdout = io.StringIO()
        with mock.patch.object(self.module, "utc_today", return_value=TODAY):
            with contextlib.redirect_stdout(stdout):
                code = self.module.main(["demo-plugin", "--root", str(self.root)])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "2027.3.1\n")
        self.assertEqual(manifest_version(manifest), "2027.3.1")

    def test_main_dry_run_leaves_the_manifest_alone(self):
        manifest = write_plugin(self.root)
        self.release("2027.3.0")
        stdout = io.StringIO()
        with mock.patch.object(self.module, "utc_today", return_value=TODAY):
            with contextlib.redirect_stdout(stdout):
                code = self.module.main(["demo-plugin", "--dry-run", "--root", str(self.root)])

        self.assertEqual((code, stdout.getvalue()), (0, "2027.3.1\n"))
        self.assertEqual(manifest_version(manifest), "2027.2.1")

    def test_main_reports_errors_without_writing(self):
        manifest = write_plugin(self.root, name="demo-plugin")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(["other-plugin", "--root", str(self.root)])

        self.assertEqual(code, 1)
        self.assertIn("missing plugin directory", stderr.getvalue())
        self.assertEqual(manifest_version(manifest), "2027.2.1")

    def test_main_takes_no_version_part(self):
        # The date and the releases decide the version, so there is nothing to choose.
        manifest = write_plugin(self.root)
        for part in ["major", "minor", "patch"]:
            with self.subTest(part=part):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as refused:
                    self.module.main(["demo-plugin", part, "--root", str(self.root)])
                self.assertEqual(refused.exception.code, 2)
                self.assertIn(f"unrecognized arguments: {part}", stderr.getvalue())
        self.assertEqual(manifest_version(manifest), "2027.2.1")

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
        outside.write_text('{"name":"demo-plugin","version":"2027.2.1"}\n', encoding="utf-8")
        os.symlink(outside, package / "plugin.json")

        with self.assertRaisesRegex(ValueError, "not a symlink"):
            self.bump(dry_run=True)


if __name__ == "__main__":
    unittest.main()
