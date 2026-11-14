import datetime
import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from release_fixtures import commit_all, git, init_repository, isolate_git, write_marketplace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plugin_release.py"
SHA = "a" * 40
TODAY = datetime.date(2026, 11, 14)


def load_module():
    spec = importlib.util.spec_from_file_location("plugin_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PluginReleaseTests(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        self.module = load_module()

    def test_parse_version_accepts_only_three_plain_numbers(self):
        self.assertEqual(self.module.parse_version("2026.11.0"), (2026, 11, 0))
        # The releases made before CalVer still have to be read and compared.
        self.assertEqual(self.module.parse_version("1.3.2"), (1, 3, 2))
        self.assertEqual(self.module.parse_version("0.0.0"), (0, 0, 0))
        invalid = [
            "1.0",
            "1.0.0.0",
            "2026.8.10.1",
            "01.0.0",
            "1.00.0",
            "1.0.0-beta",
            "1.0.0+build",
            "v1.0.0",
            "1.0.0\n",
            "２.0.0",
            None,
            1,
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "three plain numbers"):
                self.module.parse_version(value)

    def test_parse_calver_accepts_only_year_month_release(self):
        self.assertEqual(self.module.parse_calver("2026.11.0"), (2026, 11, 0))
        self.assertEqual(self.module.parse_calver("2027.1.12"), (2027, 1, 12))
        invalid = [
            "1.3.2",
            "2.0.0",
            "26.11.0",
            "2026.0.0",
            "2026.13.0",
            "2026.04.0",
            "2026.11",
            "2026.11.14.1",
            "2026.11.0-rc1",
            "2026.11.0\n",
            None,
            20261100,
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "YEAR.MONTH.RELEASE"):
                self.module.parse_calver(value)

    def test_utc_today_is_the_date_in_utc(self):
        before = datetime.datetime.now(datetime.timezone.utc).date()
        today = self.module.utc_today()
        after = datetime.datetime.now(datetime.timezone.utc).date()
        self.assertIs(type(today), datetime.date)
        self.assertTrue(before <= today <= after)

    def test_next_version_counts_the_releases_of_the_month(self):
        cases = [
            ([], "2026.11.0"),
            # The first CalVer release follows the 1.x ones.
            (["1.3.1", "1.3.2"], "2026.11.0"),
            (["1.3.2", "2026.10.4"], "2026.11.0"),
            (["2025.11.7"], "2026.11.0"),
            (["2026.11.0"], "2026.11.1"),
            # The latest release counts, in whatever order they are given.
            (["2026.11.1", "2026.10.9", "2026.11.0"], "2026.11.2"),
        ]
        for released, expected in cases:
            with self.subTest(released=released):
                self.assertEqual(self.module.next_version(released, TODAY), expected)
        self.assertEqual(
            self.module.next_version(["2026.12.3"], datetime.date(2027, 1, 1)), "2027.1.0"
        )

    def test_next_version_refuses_a_latest_release_from_a_later_month(self):
        with self.assertRaisesRegex(ValueError, "2026.12.0 names a month after 2026.11"):
            self.module.next_version(["2026.12.0"], TODAY)

    def test_check_next_version_accepts_only_what_next_version_gives(self):
        cases = [
            ("2026.11.0", []),
            ("2026.11.0", ["1.3.2"]),
            ("2026.11.0", ["2026.10.4"]),
            ("2026.11.1", ["1.3.2", "2026.11.0"]),
        ]
        for version, released in cases:
            with self.subTest(version=version, released=released):
                self.assertEqual(self.module.next_version(released, TODAY), version)
                self.module.check_next_version(version, released, TODAY)

    def test_check_next_version_accepts_a_version_set_in_an_earlier_month(self):
        # Set in October and not released until November.
        self.module.check_next_version("2026.10.5", ["2026.10.4"], TODAY)
        self.module.check_next_version("2026.10.0", ["1.3.2"], TODAY)

    def test_check_next_version_refuses_every_other_version(self):
        cases = [
            ("2.0.0", ["1.3.2"], "is not YEAR.MONTH.RELEASE"),
            ("2026.11.14.1", ["1.3.2"], "is not YEAR.MONTH.RELEASE"),
            # A day of the month is not a count of releases.
            ("2026.11.14", ["1.3.2"], "must be 2026.11.0: the third number counts"),
            ("2026.12.0", ["1.3.2"], "names a month after 2026.11, the current month in UTC"),
            ("2027.1.0", [], "names a month after 2026.11"),
            ("2026.11.0", ["2026.11.0"], "must be greater than the latest release 2026.11.0"),
            ("2026.10.9", ["2026.10.8", "2026.11.0"], "must be greater than the latest release 2026.11.0"),
            ("2026.11.2", ["2026.11.0"], "must be 2026.11.1"),
            ("2026.11.1", ["2026.10.3"], "must be 2026.11.0"),
            ("2026.11.1", [], "must be 2026.11.0"),
        ]
        for version, released, message in cases:
            with self.subTest(version=version, released=released):
                with self.assertRaisesRegex(ValueError, message):
                    self.module.check_next_version(version, released, TODAY)

    def test_release_tag_follows_claude_code_plugin_tag_convention(self):
        self.assertEqual(self.module.release_tag("watch-video", "2026.11.0"), "watch-video--v2026.11.0")
        self.assertEqual(self.module.release_tag("watch-video", "1.3.2"), "watch-video--v1.3.2")
        with self.assertRaises(ValueError):
            self.module.release_tag("bad--name", "2026.11.0")
        # Claude Code cannot read a fourth number in a tag, so none is made.
        for version in ["2026.11", "2026.11.14.1"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.module.release_tag("watch-video", version)

    def test_marketplace_entry_pins_tag_and_full_sha(self):
        self.assertEqual(
            self.module.marketplace_entry("demo-plugin", "1.2.0", "Demo.", SHA),
            {
                "name": "demo-plugin",
                "description": "Demo.",
                "version": "1.2.0",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/heyNag/charms.git",
                    "path": "packages/demo-plugin",
                    "ref": "demo-plugin--v1.2.0",
                    "sha": SHA,
                },
            },
        )
        with self.assertRaisesRegex(ValueError, "full 40-character SHA"):
            self.module.marketplace_entry("demo-plugin", "1.2.0", "Demo.", "abc1234")

    def test_released_versions_and_tag_commit_read_local_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            init_repository(root)
            sha = commit_all(root)
            for tag in [
                "demo--v2026.11.0",
                "demo--v1.0.0",
                "demo--v2026.9.12",
                "demo--v1.10.0",
                "demo--v1.2.0",
                "demo--v2026.11.14.1",
                "demo--vlatest",
                "demo-other--v9.0.0",
            ]:
                git(root, "tag", tag)

            self.assertEqual(
                self.module.released_versions(root, "demo"),
                ["1.0.0", "1.2.0", "1.10.0", "2026.9.12", "2026.11.0"],
            )
            self.assertEqual(self.module.tag_commit(root, "demo--v1.2.0"), sha)
            self.assertIsNone(self.module.tag_commit(root, "demo--v2.0.0"))

    def test_released_versions_ignore_porcelain_column_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            init_repository(root)
            commit_all(root)
            for tag in ["demo--v1.0.0", "demo--v1.2.0"]:
                git(root, "tag", tag)
            columns = {
                "GIT_CONFIG_COUNT": "3",
                "GIT_CONFIG_KEY_2": "column.ui",
                "GIT_CONFIG_VALUE_2": "always",
            }
            with mock.patch.dict(os.environ, columns):
                self.assertEqual(self.module.released_versions(root, "demo"), ["1.0.0", "1.2.0"])

    def test_tag_commit_reports_git_failures_instead_of_a_missing_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_a_repository = pathlib.Path(tmp)
            ceiling = {"GIT_CEILING_DIRECTORIES": str(not_a_repository.parent)}
            with mock.patch.dict(os.environ, ceiling), self.assertRaisesRegex(RuntimeError, "git cannot read tag"):
                self.module.tag_commit(not_a_repository, "demo--v1.0.0")

    def test_released_versions_report_git_failures_instead_of_no_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_a_repository = pathlib.Path(tmp)
            ceiling = {"GIT_CEILING_DIRECTORIES": str(not_a_repository.parent)}
            with mock.patch.dict(os.environ, ceiling):
                with self.assertRaisesRegex(RuntimeError, "git cannot list the release tags of demo"):
                    self.module.released_versions(not_a_repository, "demo")
                with self.assertRaisesRegex(RuntimeError, "git cannot list the release tags of demo"):
                    self.module.known_releases(not_a_repository, "demo")

    def test_marketplace_version_is_the_release_the_marketplace_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.assertIsNone(self.module.marketplace_version(root, "demo"))

            path = write_marketplace(
                root,
                [{"name": "demo", "version": "2026.11.1"}, {"name": "other", "version": "1.1.0"}],
            )
            self.assertEqual(self.module.marketplace_version(root, "demo"), "2026.11.1")
            self.assertEqual(self.module.marketplace_version(root, "other"), "1.1.0")
            self.assertIsNone(self.module.marketplace_version(root, "unlisted"))

            # The validator reports a marketplace it cannot read. Here it lists nothing.
            for broken in [
                "{not json",
                "[]",
                '{"plugins": {}}',
                '{"plugins": ["demo", {"name": "demo", "version": "latest"}]}',
                '{"plugins": [{"name": "demo", "version": 2026}]}',
            ]:
                with self.subTest(broken=broken):
                    path.write_text(broken, encoding="utf-8")
                    self.assertIsNone(self.module.marketplace_version(root, "demo"))

    def test_known_releases_add_the_marketplace_entry_to_the_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            init_repository(root)
            commit_all(root)
            for tag in ["demo--v2026.11.0", "demo--v1.3.2"]:
                git(root, "tag", tag)
            self.assertEqual(self.module.known_releases(root, "demo"), ["1.3.2", "2026.11.0"])

            # A checkout whose newest tag was not fetched still holds the entry.
            write_marketplace(root, [{"name": "demo", "version": "2026.11.1"}])
            self.assertEqual(
                self.module.known_releases(root, "demo"), ["1.3.2", "2026.11.0", "2026.11.1"]
            )

            write_marketplace(root, [{"name": "demo", "version": "2026.11.0"}])
            self.assertEqual(self.module.known_releases(root, "demo"), ["1.3.2", "2026.11.0"])

    def test_manifest_at_rejects_option_like_revisions(self):
        with self.assertRaisesRegex(ValueError, "invalid revision"):
            self.module.manifest_at(ROOT, "--output=/tmp/x", "watch-video")


if __name__ == "__main__":
    unittest.main()
