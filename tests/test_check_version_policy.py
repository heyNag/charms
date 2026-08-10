import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-version-policy.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_version_policy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CheckVersionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def git(self, root, *args):
        return subprocess.run(["git", *args], cwd=root, check=True, text=True, stdout=subprocess.PIPE)

    def init_repo(self, root):
        self.git(root, "init")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "config", "commit.gpgsign", "false")

    def write_plugin(self, root, version):
        path = root / "packages" / "demo-plugin" / "plugin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"name": "demo-plugin", "version": version}) + "\n",
            encoding="utf-8",
        )

    def activate_policy(self, root):
        policy = root / "scripts" / "check-version-policy.py"
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("policy placeholder\n", encoding="utf-8")

    def commit(self, root, message):
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", message)
        return self.git(root, "rev-parse", "HEAD").stdout.strip()

    def test_identifies_only_package_root_manifests(self):
        self.assertTrue(self.module.is_package_manifest("packages/demo-plugin/plugin.json"))
        self.assertFalse(self.module.is_package_manifest("packages/demo-plugin/metadata/plugin.json"))
        self.assertFalse(self.module.is_package_manifest("plugin.json"))
        self.assertFalse(self.module.is_package_manifest("packages/demo-plugin/skills/x/plugin.json"))

    def test_detects_existing_plugin_version_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            self.write_plugin(root, "2026.8.10")
            base = self.commit(root, "initial")
            self.write_plugin(root, "2026.8.10.1")
            head = self.commit(root, "manual bump")

            changes = self.module.plugin_version_changes(root, base, head)

        self.assertEqual(
            changes,
            ["packages/demo-plugin/plugin.json: 2026.8.10 -> 2026.8.10.1"],
        )

    def test_main_rejects_human_version_change_when_policy_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            self.write_plugin(root, "2026.8.10")
            self.activate_policy(root)
            base = self.commit(root, "initial")
            self.write_plugin(root, "2026.8.10.1")
            head = self.commit(root, "manual bump")

            with mock.patch("sys.stderr"):
                code = self.module.main(
                    ["--base", base, "--head", head, "--actor", "nag", "--root", str(root)]
                )

        self.assertEqual(code, 1)

    def test_main_allows_release_bot_version_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            self.write_plugin(root, "2026.8.10")
            self.activate_policy(root)
            base = self.commit(root, "initial")
            self.write_plugin(root, "2026.8.11")
            head = self.commit(root, "release")

            with mock.patch("sys.stdout"):
                code = self.module.main(
                    [
                        "--base",
                        base,
                        "--head",
                        head,
                        "--actor",
                        "github-actions[bot]",
                        "--root",
                        str(root),
                    ]
                )

        self.assertEqual(code, 0)

    def test_new_plugin_manifest_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            (root / "README.md").write_text("demo\n", encoding="utf-8")
            base = self.commit(root, "initial")
            self.write_plugin(root, "2026.8.10")
            head = self.commit(root, "add plugin")

            changes = self.module.plugin_version_changes(root, base, head)

        self.assertEqual(changes, [])

    def test_noncanonical_manifest_change_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            path = root / "packages/demo-plugin/metadata/plugin.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"version":"2026.8.10"}\n', encoding="utf-8")
            base = self.commit(root, "initial")
            path.write_text('{"version":"2026.8.11"}\n', encoding="utf-8")
            head = self.commit(root, "change unrelated json")

            changes = self.module.plugin_version_changes(root, base, head)

        self.assertEqual(changes, [])

    def test_main_skips_when_policy_was_not_present_at_base_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.init_repo(root)
            self.write_plugin(root, "2026.8.10")
            base = self.commit(root, "initial")
            self.write_plugin(root, "2026.8.11")
            self.activate_policy(root)
            head = self.commit(root, "add policy")

            with mock.patch("sys.stdout"):
                code = self.module.main(
                    ["--base", base, "--head", head, "--actor", "nag", "--root", str(root)]
                )

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
