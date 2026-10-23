import contextlib
import importlib.util
import io
import pathlib
import tempfile
import unittest

from release_fixtures import commit_all, git, init_repository, isolate_git, write_json


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plan-plugin-release.py"


def load_module():
    spec = importlib.util.spec_from_file_location("plan_plugin_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PlanPluginReleaseTests(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        init_repository(self.root)

    def commit_version(self, version: str) -> str:
        write_json(
            self.root / "packages" / "demo-plugin" / "plugin.json",
            {"name": "demo-plugin", "version": version},
        )
        return commit_all(self.root, f"Set demo-plugin {version}")

    def test_first_release_has_no_previous_tag(self):
        self.commit_version("1.0.0")
        self.assertEqual(
            self.module.plan_release(self.root, "demo-plugin"),
            {"version": "1.0.0", "tag": "demo-plugin--v1.0.0", "previous_tag": ""},
        )

    def test_next_release_names_the_latest_previous_tag(self):
        self.commit_version("1.0.0")
        git(self.root, "tag", "demo-plugin--v1.0.0")
        self.commit_version("1.1.0")
        self.assertEqual(
            self.module.plan_release(self.root, "demo-plugin"),
            {"version": "1.1.0", "tag": "demo-plugin--v1.1.0", "previous_tag": "demo-plugin--v1.0.0"},
        )

    def test_refuses_an_already_released_version(self):
        self.commit_version("1.0.0")
        git(self.root, "tag", "demo-plugin--v1.0.0")
        with self.assertRaisesRegex(ValueError, "already exists; bump the version"):
            self.module.plan_release(self.root, "demo-plugin")

    def test_refuses_a_version_below_the_latest_release(self):
        self.commit_version("1.2.0")
        git(self.root, "tag", "demo-plugin--v1.2.0")
        self.commit_version("1.1.9")
        with self.assertRaisesRegex(ValueError, "must be greater than the latest release 1.2.0"):
            self.module.plan_release(self.root, "demo-plugin")

    def test_plans_the_committed_manifest_not_the_working_tree(self):
        self.commit_version("1.0.0")
        write_json(
            self.root / "packages" / "demo-plugin" / "plugin.json",
            {"name": "demo-plugin", "version": "9.9.9"},
        )
        self.assertEqual(self.module.plan_release(self.root, "demo-plugin")["version"], "1.0.0")

    def test_main_prints_github_output_lines_or_an_error(self):
        self.commit_version("1.0.0")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.module.main(["demo-plugin", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "version=1.0.0\ntag=demo-plugin--v1.0.0\nprevious_tag=\n",
        )

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(["missing-plugin", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("cannot read packages/missing-plugin/plugin.json at HEAD", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
