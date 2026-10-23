import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest

from release_fixtures import (
    commit_all,
    git,
    init_repository,
    isolate_git,
    write_json,
    write_marketplace,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update-marketplace.py"


def load_module():
    spec = importlib.util.spec_from_file_location("update_marketplace", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class UpdateMarketplaceTests(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        init_repository(self.root)
        self.marketplace = write_marketplace(self.root)

    def release(self, plugin: str, version: str, description: str = "Demo plugin.") -> str:
        write_json(
            self.root / "packages" / plugin / "plugin.json",
            {"name": plugin, "version": version, "description": description},
        )
        sha = commit_all(self.root, f"Release {plugin} {version}")
        git(self.root, "tag", f"{plugin}--v{version}")
        return sha

    def entries(self) -> list:
        return json.loads(self.marketplace.read_text(encoding="utf-8"))["plugins"]

    def test_adds_a_pinned_entry_from_the_release_commit(self):
        sha = self.release("demo-plugin", "1.0.0")

        entry, changed = self.module.update_marketplace(self.root, "demo-plugin", sha)

        self.assertTrue(changed)
        self.assertEqual(self.entries(), [entry])
        self.assertEqual(
            entry["source"],
            {
                "source": "git-subdir",
                "url": "https://github.com/heyNag/charms.git",
                "path": "packages/demo-plugin",
                "ref": "demo-plugin--v1.0.0",
                "sha": sha,
            },
        )
        self.assertEqual((entry["version"], entry["description"]), ("1.0.0", "Demo plugin."))

    def test_rerunning_for_the_same_release_is_a_no_op(self):
        sha = self.release("demo-plugin", "1.0.0")
        self.module.update_marketplace(self.root, "demo-plugin", sha)
        before = self.marketplace.read_bytes()

        _entry, changed = self.module.update_marketplace(self.root, "demo-plugin", sha)

        self.assertFalse(changed)
        self.assertEqual(self.marketplace.read_bytes(), before)

    def test_moves_forward_and_keeps_entries_sorted(self):
        first = self.release("demo-plugin", "1.0.0")
        self.module.update_marketplace(self.root, "demo-plugin", first)
        other = self.release("another-plugin", "1.0.0")
        self.module.update_marketplace(self.root, "another-plugin", other)
        second = self.release("demo-plugin", "1.1.0")

        self.module.update_marketplace(self.root, "demo-plugin", second)

        entries = self.entries()
        self.assertEqual([entry["name"] for entry in entries], ["another-plugin", "demo-plugin"])
        self.assertEqual(entries[1]["source"]["sha"], second)

    def test_refuses_to_move_an_entry_backwards(self):
        old = self.release("demo-plugin", "1.0.0")
        new = self.release("demo-plugin", "1.1.0")
        self.module.update_marketplace(self.root, "demo-plugin", new)

        with self.assertRaisesRegex(ValueError, "refusing to move it to 1.0.0"):
            self.module.update_marketplace(self.root, "demo-plugin", old)

    def test_requires_the_release_tag_at_the_commit(self):
        write_json(
            self.root / "packages" / "demo-plugin" / "plugin.json",
            {"name": "demo-plugin", "version": "1.0.0", "description": "Demo plugin."},
        )
        sha = commit_all(self.root)
        with self.assertRaisesRegex(ValueError, "missing or does not point at"):
            self.module.update_marketplace(self.root, "demo-plugin", sha)

        git(self.root, "tag", "demo-plugin--v1.0.0")
        later = commit_all(self.root, "Later commit")
        with self.assertRaisesRegex(ValueError, "missing or does not point at"):
            self.module.update_marketplace(self.root, "demo-plugin", later)

    def test_main_rejects_an_abbreviated_sha(self):
        sha = self.release("demo-plugin", "1.0.0")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(["demo-plugin", "--sha", sha[:12], "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("full 40-character SHA", stderr.getvalue())
        self.assertEqual(self.entries(), [])


if __name__ == "__main__":
    unittest.main()
