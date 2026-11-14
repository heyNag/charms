import contextlib
import datetime
import importlib.util
import io
import pathlib
import tempfile
import unittest
from unittest import mock

from release_fixtures import commit_all, git, init_repository, isolate_git, write_json


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plan-plugin-release.py"
TODAY = datetime.date(2027, 3, 15)
SET_IT = "; set the version with scripts/bump-plugin-version.py first"


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

    def release(self, version: str) -> str:
        sha = self.commit_version(version)
        git(self.root, "tag", f"demo-plugin--v{version}")
        return sha

    def plan(self, revision: str = "HEAD") -> dict[str, str]:
        return self.module.plan_release(self.root, "demo-plugin", revision, today=TODAY)

    def test_first_release_has_no_previous_tag(self):
        self.commit_version("2027.3.0")
        self.assertEqual(
            self.plan(),
            {"version": "2027.3.0", "tag": "demo-plugin--v2027.3.0", "previous_tag": ""},
        )

    def test_next_release_names_the_latest_previous_tag(self):
        self.release("2027.2.0")
        self.release("2027.3.0")
        self.commit_version("2027.3.1")
        self.assertEqual(
            self.plan(),
            {
                "version": "2027.3.1",
                "tag": "demo-plugin--v2027.3.1",
                "previous_tag": "demo-plugin--v2027.3.0",
            },
        )

    def test_the_first_calver_release_follows_the_1_x_releases(self):
        self.release("1.3.1")
        self.release("1.3.2")
        self.commit_version("2027.3.0")
        self.assertEqual(
            self.plan(),
            {
                "version": "2027.3.0",
                "tag": "demo-plugin--v2027.3.0",
                "previous_tag": "demo-plugin--v1.3.2",
            },
        )

    def test_a_version_set_in_an_earlier_month_can_still_be_released(self):
        self.release("2027.2.0")
        self.commit_version("2027.2.1")
        self.assertEqual(self.plan()["tag"], "demo-plugin--v2027.2.1")

    def test_refuses_an_already_released_version(self):
        for version in ["2027.3.0", "1.3.2"]:
            with self.subTest(version=version):
                self.release(version)
                with self.assertRaisesRegex(
                    ValueError,
                    f"demo-plugin--v{version} already exists; "
                    "bump the version with scripts/bump-plugin-version.py first",
                ):
                    self.plan()

    def test_refuses_a_version_below_the_latest_release(self):
        self.release("2027.3.0")
        self.commit_version("2027.2.9")
        with self.assertRaisesRegex(
            ValueError, "version 2027.2.9 must be greater than the latest release 2027.3.0" + SET_IT
        ):
            self.plan()

    def test_refuses_a_version_that_is_not_the_next_calver_release(self):
        self.release("1.3.2")
        cases = [
            ("2.0.0", "version is not YEAR.MONTH.RELEASE, such as 2026.11.0: '2.0.0'"),
            ("1.3.3", "version is not YEAR.MONTH.RELEASE"),
            ("2027.4.0", "version 2027.4.0 names a month after 2027.3, the current month in UTC"),
            ("2027.3.1", "version 2027.3.1 must be 2027.3.0"),
            ("2027.3.15", "version 2027.3.15 must be 2027.3.0"),
        ]
        for version, message in cases:
            with self.subTest(version=version):
                self.commit_version(version)
                with self.assertRaises(ValueError) as refused:
                    self.plan()
                self.assertIn(message, str(refused.exception))
                self.assertTrue(str(refused.exception).endswith(SET_IT), refused.exception)

    def test_refuses_a_version_that_is_not_three_plain_numbers(self):
        for version in ["2027.3", "2027.3.15.1", "2027.3.0-rc1"]:
            with self.subTest(version=version):
                self.commit_version(version)
                with self.assertRaisesRegex(ValueError, "version is not three plain numbers"):
                    self.plan()

    def test_plans_the_committed_manifest_not_the_working_tree(self):
        self.commit_version("2027.3.0")
        write_json(
            self.root / "packages" / "demo-plugin" / "plugin.json",
            {"name": "demo-plugin", "version": "2027.3.9"},
        )
        self.assertEqual(self.plan()["version"], "2027.3.0")

    def test_plans_the_named_revision(self):
        ready = self.commit_version("2027.3.0")
        self.commit_version("2027.3.9")
        self.assertEqual(self.plan(ready)["version"], "2027.3.0")
        with self.assertRaisesRegex(ValueError, "version 2027.3.9 must be 2027.3.0"):
            self.plan()

    def test_reads_the_current_month_from_the_date_in_utc(self):
        self.commit_version("2027.3.0")
        with mock.patch.object(self.module, "utc_today", return_value=datetime.date(2027, 2, 28)):
            with self.assertRaisesRegex(ValueError, "names a month after 2027.2"):
                self.module.plan_release(self.root, "demo-plugin")
        with mock.patch.object(self.module, "utc_today", return_value=datetime.date(2027, 3, 1)):
            self.assertEqual(
                self.module.plan_release(self.root, "demo-plugin")["version"], "2027.3.0"
            )

    def test_main_prints_github_output_lines_or_an_error(self):
        self.commit_version("2027.3.0")
        stdout = io.StringIO()
        with mock.patch.object(self.module, "utc_today", return_value=TODAY):
            with contextlib.redirect_stdout(stdout):
                code = self.module.main(["demo-plugin", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "version=2027.3.0\ntag=demo-plugin--v2027.3.0\nprevious_tag=\n",
        )

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(["missing-plugin", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("cannot read packages/missing-plugin/plugin.json at HEAD", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
