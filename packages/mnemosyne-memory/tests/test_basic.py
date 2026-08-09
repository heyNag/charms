from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "mnemosyne-memory" / "SKILL.md"
TOOL = ROOT / "tool.json"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
AGENT = ROOT / "skills" / "mnemosyne-memory" / "agents" / "openai.yaml"


class MnemosyneMemoryPackageTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for path in [SKILL, TOOL, PLUGIN, AGENT, ROOT / "README.md", ROOT / "SOURCE.md"]:
            self.assertTrue(path.is_file(), f"missing {path}")

    def test_manifest_names_and_targets_match(self) -> None:
        tool = json.loads(TOOL.read_text(encoding="utf-8"))
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        self.assertEqual(tool["name"], "mnemosyne-memory")
        self.assertEqual(plugin["name"], "mnemosyne-memory")
        self.assertRegex(
            plugin["version"],
            r"^(?:0\.1\.0|\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?)$",
        )
        self.assertTrue(tool["agent_agnostic"])
        self.assertFalse(tool["has_mcp"])
        self.assertIn("generic", tool["targets"])

    def test_skill_encodes_continuity_and_safety_contract(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("name: mnemosyne-memory", text)
        self.assertIn("description: Use when ", text)
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

    def test_openai_metadata_declares_mnemosyne_dependency(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        self.assertIn('display_name: "Mnemosyne Memory"', text)
        self.assertIn("$mnemosyne-memory", text)
        self.assertIn('value: "mnemosyne"', text)
        self.assertIn("allow_implicit_invocation: true", text)


if __name__ == "__main__":
    unittest.main()
