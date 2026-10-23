import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from release_fixtures import commit_all, git, init_repository, isolate_git


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "plugin_release.py"
SHA = "a" * 40


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

    def test_parse_version_accepts_only_major_minor_patch(self):
        self.assertEqual(self.module.parse_version("0.0.0"), (0, 0, 0))
        self.assertEqual(self.module.parse_version("10.20.30"), (10, 20, 30))
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
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "semantic versioning"):
                self.module.parse_version(value)

    def test_bump_version_resets_lower_parts(self):
        self.assertEqual(self.module.bump_version("1.2.3", "major"), "2.0.0")
        self.assertEqual(self.module.bump_version("1.2.3", "minor"), "1.3.0")
        self.assertEqual(self.module.bump_version("1.2.3", "patch"), "1.2.4")
        with self.assertRaisesRegex(ValueError, "unsupported version part"):
            self.module.bump_version("1.2.3", "date")

    def test_release_tag_follows_claude_code_plugin_tag_convention(self):
        self.assertEqual(self.module.release_tag("watch-video", "1.0.0"), "watch-video--v1.0.0")
        with self.assertRaises(ValueError):
            self.module.release_tag("bad--name", "1.0.0")
        with self.assertRaises(ValueError):
            self.module.release_tag("watch-video", "1.0")

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
                "demo--v1.0.0",
                "demo--v1.10.0",
                "demo--v1.2.0",
                "demo--vlatest",
                "demo-other--v9.0.0",
            ]:
                git(root, "tag", tag)

            self.assertEqual(
                self.module.released_versions(root, "demo"),
                ["1.0.0", "1.2.0", "1.10.0"],
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

    def test_manifest_at_rejects_option_like_revisions(self):
        with self.assertRaisesRegex(ValueError, "invalid revision"):
            self.module.manifest_at(ROOT, "--output=/tmp/x", "watch-video")


if __name__ == "__main__":
    unittest.main()
