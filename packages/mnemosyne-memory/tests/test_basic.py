from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "mnemosyne-memory" / "SKILL.md"
PLUGIN = ROOT / "plugin.json"


class MnemosyneMemoryPackageTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for path in [SKILL, PLUGIN, ROOT / "README.md", ROOT / "LICENSE"]:
            self.assertTrue(path.is_file(), f"missing {path}")

    def test_plugin_manifest(self) -> None:
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        self.assertEqual(
            plugin["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(plugin["name"], "mnemosyne-memory")
        self.assertIn("mcp", plugin["keywords"])
        self.assertFalse((ROOT / "mcp.json").exists())

    def test_skill_encodes_continuity_and_safety_contract(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]

        self.assertIn("name: mnemosyne-memory", frontmatter)
        self.assertIn("description: Use when ", frontmatter)
        self.assertIn("license: MIT", frontmatter)
        self.assertIn("compatibility:", frontmatter)
        self.assertIn("[project:<key>] HANDOFF", text)
        self.assertIn("Before every write, search", text)
        self.assertIn("Never automatically run:", text)
        self.assertIn("consolidation or `sleep`", text)
        self.assertIn("Never hard-delete or `forget`", text)
        self.assertIn("Let the configured MCP launcher choose the bank", text)

    def test_skill_is_public_and_profile_agnostic(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        for private_value in ["/Users/", "personal bank", "work bank", "nboddu"]:
            self.assertNotIn(private_value, text)

if __name__ == "__main__":
    unittest.main()
