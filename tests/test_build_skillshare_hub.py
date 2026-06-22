import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-skillshare-hub.py"


def load_builder():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("build_skillshare_hub", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildSkillshareHubTests(unittest.TestCase):
    def write_package(self, root, name, *, public=True, targets=None, tags=None, version="2026.6.21"):
        package_dir = root / "packages" / name
        plugin_dir = package_dir / ".claude-plugin"
        skill_dir = package_dir / "skills" / name
        plugin_dir.mkdir(parents=True)
        skill_dir.mkdir(parents=True)
        tool = {
            "name": name,
            "description": f"{name} description",
            "targets": targets if targets is not None else ["claude", "codex", "generic"],
            "agent_agnostic": True,
            "public": public,
        }
        if tags is not None:
            tool["tags"] = tags
        (package_dir / "tool.json").write_text(json.dumps(tool), encoding="utf-8")
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        tag_line = ", ".join(tags or [])
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    f"name: {name}",
                    f"description: {name} skill description from frontmatter",
                    f"tags: {tag_line}",
                    "---",
                    "",
                    f"# {name}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def test_build_index_uses_canonical_package_sources(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "zeta", tags=["local", "video"])
            self.write_package(root, "alpha", tags=["codex"])
            self.write_package(root, "private-skill", public=False)

            index = builder.build_index(root)

        self.assertEqual(index["schemaVersion"], 1)
        self.assertEqual(index["generatedAt"], "2026-06-21T00:00:00Z")
        self.assertEqual(index["sourcePath"], "heyNag/agent-tools")
        self.assertEqual([skill["name"] for skill in index["skills"]], ["alpha", "zeta"])
        self.assertEqual(index["skills"][0]["source"], "packages/alpha/skills/alpha")
        self.assertNotIn("skill", index["skills"][0])
        self.assertEqual(index["skills"][0]["description"], "alpha skill description from frontmatter")
        self.assertNotIn("generated", index["skills"][1]["source"])

    def test_generated_at_uses_latest_date_version(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "older", version="2026.6.20")
            self.write_package(root, "newer", version="2026.6.21.2")

            index = builder.build_index(root)

        self.assertEqual(index["generatedAt"], "2026-06-21T00:00:00Z")

    def test_frontmatter_tags_are_used_for_skillshare_hub(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "searchy", tags=["zebra", "alpha", "alpha"])

            index = builder.build_index(root)

        self.assertEqual(index["skills"][0]["tags"], ["alpha", "zebra"])

    def test_frontmatter_name_must_match_manifest(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.write_package(root, "actual", tags=["local"])
            (root / "packages" / "actual" / "skills" / "actual" / "SKILL.md").write_text(
                "---\nname: wrong\ndescription: Wrong.\ntags: local\n---\n",
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                builder.build_index(root)


if __name__ == "__main__":
    unittest.main()
