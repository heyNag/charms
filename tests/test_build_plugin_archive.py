import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-plugin-archive.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_plugin_archive", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_plugin(root: pathlib.Path, version: str = "2026.8.10") -> pathlib.Path:
    package = root / "packages" / "demo-plugin"
    skill = package / "skills" / "demo-plugin"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (package / "plugin.json").write_text(
        json.dumps({"name": "demo-plugin", "version": version}) + "\n",
        encoding="utf-8",
    )
    (package / "README.md").write_text("# Demo\n", encoding="utf-8")
    (package / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (package / "SOURCE.md").write_text("not distributed\n", encoding="utf-8")
    (package / "tests").mkdir()
    (package / "tests" / "test_demo.py").write_text("pass\n", encoding="utf-8")
    (skill / "SKILL.md").write_text("---\nname: demo-plugin\n---\n", encoding="utf-8")
    executable = scripts / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return package


class BuildPluginArchiveTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_builds_deterministic_allowlisted_archive_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_plugin(root)
            output = root / "artifacts"

            first = self.module.build_archive(root, "demo-plugin", output)
            first_bytes = first.archive.read_bytes()
            second = self.module.build_archive(root, "demo-plugin", output)

            self.assertEqual(first.archive.name, "demo-plugin-agent-plugin-v2026.8.10.zip")
            self.assertEqual(
                first.checksum.name,
                "demo-plugin-agent-plugin-v2026.8.10.zip.sha256",
            )
            self.assertEqual(first_bytes, second.archive.read_bytes())
            digest = hashlib.sha256(first_bytes).hexdigest()
            self.assertEqual(first.checksum.read_text(encoding="utf-8"), f"{digest}  {first.archive.name}\n")

            with zipfile.ZipFile(first.archive) as handle:
                self.assertEqual(
                    handle.namelist(),
                    [
                        "demo-plugin/LICENSE",
                        "demo-plugin/README.md",
                        "demo-plugin/plugin.json",
                        "demo-plugin/skills/demo-plugin/SKILL.md",
                        "demo-plugin/skills/demo-plugin/scripts/run.sh",
                    ],
                )
                mode = handle.getinfo("demo-plugin/skills/demo-plugin/scripts/run.sh").external_attr >> 16
                self.assertEqual(mode & 0o777, 0o755)
                self.assertIsNone(handle.testzip())

    def test_includes_optional_mcp_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            (package / "mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")

            result = self.module.build_archive(root, "demo-plugin", root / "artifacts")

            with zipfile.ZipFile(result.archive) as handle:
                self.assertIn("demo-plugin/mcp.json", handle.namelist())

    def test_requires_package_license(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            (package / "LICENSE").unlink()

            with self.assertRaisesRegex(FileNotFoundError, "missing required file"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_requires_package_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            (package / "README.md").unlink()

            with self.assertRaisesRegex(FileNotFoundError, "missing required file"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_symlink_inside_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            os.symlink(outside, package / "skills/demo-plugin/link.txt")

            with self.assertRaisesRegex(ValueError, "symlinks are not allowed"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_symlinked_top_level_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            (package / "README.md").unlink()
            os.symlink(root / "LICENSE", package / "README.md")

            with self.assertRaisesRegex(ValueError, "symlinks are not allowed"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_symlinked_packages_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            source_root = base / "source"
            make_plugin(source_root)
            wrapper_root = base / "wrapper"
            wrapper_root.mkdir()
            os.symlink(source_root / "packages", wrapper_root / "packages")

            with self.assertRaisesRegex(ValueError, "symlinks are not allowed"):
                self.module.build_archive(wrapper_root, "demo-plugin", base / "artifacts")

    def test_rejects_special_file_inside_skills(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("named pipes are not supported on this platform")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            os.mkfifo(package / "skills/demo-plugin/input.pipe")

            with self.assertRaisesRegex(ValueError, "must be a regular file"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_backslash_in_archive_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)
            (package / "skills/demo-plugin/..\\escape.txt").write_text(
                "unsafe on Windows\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "backslashes are not allowed"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_unsafe_and_unicode_colliding_archive_names(self):
        for archive_name in [
            "demo-plugin//file",
            "demo-plugin/./file",
            "demo-plugin/bad\nfile",
            "demo-plugin/CON.txt",
            "demo-plugin/COM1",
            "demo-plugin/bad:name",
            "demo-plugin/trailing.",
            "demo-plugin/trailing ",
        ]:
            with self.subTest(archive_name=archive_name), self.assertRaises(ValueError):
                self.module.normalized_archive_key(archive_name)
        self.assertEqual(
            self.module.normalized_archive_key("demo-plugin/caf\N{LATIN SMALL LETTER E WITH ACUTE}.txt"),
            self.module.normalized_archive_key("demo-plugin/cafe\N{COMBINING ACUTE ACCENT}.txt"),
        )

    def test_rejects_invalid_manifest_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_plugin(root, version="2026.2.30")

            with self.assertRaisesRegex(ValueError, "invalid calendar date"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_plugin(root, version="２０２６.8.10")

            with self.assertRaisesRegex(ValueError, "UTC CalVer"):
                self.module.build_archive(root, "demo-plugin", root / "artifacts")

    def test_rejects_output_directory_inside_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            package = make_plugin(root)

            with self.assertRaisesRegex(ValueError, "outside the plugin root"):
                self.module.build_archive(root, "demo-plugin", package / "artifacts")


if __name__ == "__main__":
    unittest.main()
