from __future__ import annotations

import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "chatgpt-pro-review" / "SKILL.md"
TOOL = ROOT / "tool.json"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
AGENT = ROOT / "skills" / "chatgpt-pro-review" / "agents" / "openai.yaml"


class ChatGPTProReviewPackageTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for path in [SKILL, TOOL, PLUGIN, AGENT, ROOT / "README.md", ROOT / "SOURCE.md"]:
            self.assertTrue(path.is_file(), f"missing {path}")

    def test_manifest_names_match(self) -> None:
        tool = json.loads(TOOL.read_text(encoding="utf-8"))
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        self.assertEqual(tool["name"], "chatgpt-pro-review")
        self.assertEqual(plugin["name"], "chatgpt-pro-review")
        self.assertTrue(tool["agent_agnostic"])
        self.assertIn("generic", tool["targets"])

    def test_skill_frontmatter_is_public_safe(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("name: chatgpt-pro-review", text)
        self.assertIn("description: Use when ", text)
        self.assertIn("tags: review, chatgpt, pro, planning, code-review", text)
        self.assertIn("Before submitting private repo context", text)
        self.assertIn("Redact secrets", text)


if __name__ == "__main__":
    unittest.main()
