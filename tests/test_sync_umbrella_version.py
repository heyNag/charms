import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-umbrella-version.py"

JSON_MANIFESTS = [
    "package.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
]


def load_module():
    spec = importlib.util.spec_from_file_location("sync_umbrella_version", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_root(tmp, package_versions, umbrella_version="0.1.0"):
    root = pathlib.Path(tmp)
    for name, version in package_versions.items():
        plugin_dir = root / "packages" / name / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8"
        )
    for rel in JSON_MANIFESTS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"name": "charms", "version": umbrella_version}) + "\n", encoding="utf-8"
        )
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "charms"\nversion = "{umbrella_version}"\n\n'
        '[tool.ruff]\nline-length = 100\ntarget-version = "py311"\n',
        encoding="utf-8",
    )
    return root


def umbrella_value(root, rel):
    if rel.endswith(".toml"):
        return load_module().read_toml_version(root / rel)
    return json.loads((root / rel).read_text(encoding="utf-8"))["version"]


class SyncUmbrellaVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_target_version_is_max_calver_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.21.2", "b": "2026.6.22", "c": "0.1.0"})
            self.assertEqual(self.module.target_version(root), "2026.6.22")

    def test_sync_updates_all_umbrella_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.22"}, umbrella_version="0.1.0")
            target, changed = self.module.sync(root)
            self.assertEqual(target, "2026.6.22")
            self.assertEqual(set(changed), set(JSON_MANIFESTS) | {"pyproject.toml"})
            for rel in JSON_MANIFESTS:
                self.assertEqual(json.loads((root / rel).read_text())["version"], "2026.6.22")
            pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('version = "2026.6.22"', pyproject)
            # The unrelated ruff target-version line must be left alone.
            self.assertIn('target-version = "py311"', pyproject)

    def test_sync_is_monotonic_and_preserves_head_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.21.2"}, umbrella_version="2026.6.22")
            target, changed = self.module.sync(root)
            # Umbrella head-start (2026.6.22) wins over the older package date.
            self.assertEqual(target, "2026.6.22")
            self.assertEqual(changed, [])

    def test_no_dated_release_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "0.1.0"}, umbrella_version="0.1.0")
            target, changed = self.module.sync(root)
            self.assertIsNone(target)
            self.assertEqual(changed, [])
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "0.1.0")

    def test_check_detects_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.22"}, umbrella_version="0.1.0")
            with mock.patch("sys.stderr"):
                code = self.module.main(["--root", str(root), "--check"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "0.1.0")

    def test_check_passes_when_in_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.22"}, umbrella_version="2026.6.22")
            with mock.patch("sys.stdout"):
                code = self.module.main(["--root", str(root), "--check"])
            self.assertEqual(code, 0)

    def test_main_writes_latest_release_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, {"a": "2026.6.21.2", "b": "2026.6.22"}, umbrella_version="0.1.0")
            with mock.patch("sys.stdout"):
                code = self.module.main(["--root", str(root)])
            self.assertEqual(code, 0)
            for rel in JSON_MANIFESTS:
                self.assertEqual(json.loads((root / rel).read_text())["version"], "2026.6.22")


if __name__ == "__main__":
    unittest.main()
