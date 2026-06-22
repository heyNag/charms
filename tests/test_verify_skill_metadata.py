import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-skill-metadata.py"


def load_module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("verify_skill_metadata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VerifySkillMetadataTests(unittest.TestCase):
    def write_package(self, root, name, *, skill_tags="local, safe", tool_tags=None):
        package_dir = root / "packages" / name
        skill_dir = package_dir / "skills" / name
        skill_dir.mkdir(parents=True)
        tool = {
            "name": name,
            "description": f"{name} description",
            "tags": tool_tags if tool_tags is not None else ["local", "safe"],
            "targets": ["claude", "codex", "generic"],
            "agent_agnostic": True,
            "public": True,
        }
        (package_dir / "tool.json").write_text(json.dumps(tool), encoding="utf-8")
        (skill_dir / "SKILL.md").write_text(
            (
                "---\n"
                f"name: {name}\n"
                f"description: Use when the user needs {name} help.\n"
                f"tags: {skill_tags}\n"
                "---\n"
            ),
            encoding="utf-8",
        )

    def test_package_metadata_accepts_matching_skill_tags(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "ok-skill")

            errors = module.validate_package(root, root / "packages" / "ok-skill" / "tool.json")

        self.assertEqual(errors, [])

    def test_package_metadata_rejects_tag_drift(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "drift-skill", skill_tags="local, other")

            errors = module.validate_package(root, root / "packages" / "drift-skill" / "tool.json")

        self.assertTrue(any("must match tool.json tags" in error for error in errors))

    def test_package_metadata_rejects_non_trigger_description(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "summary-skill")
            skill_path = root / "packages" / "summary-skill" / "skills" / "summary-skill" / "SKILL.md"
            skill_path.write_text(
                "---\n"
                "name: summary-skill\n"
                "description: Summarize something useful.\n"
                "tags: local, safe\n"
                "---\n",
                encoding="utf-8",
            )

            errors = module.validate_package(root, root / "packages" / "summary-skill" / "tool.json")

        self.assertTrue(any("description must start with 'Use when '" in error for error in errors))

    def test_skillignore_requires_dist(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".skillignore").write_text("# empty\n", encoding="utf-8")

            errors = module.validate_skillignore(root)

        self.assertEqual(errors, [".skillignore: must include .dist/"])


if __name__ == "__main__":
    unittest.main()
