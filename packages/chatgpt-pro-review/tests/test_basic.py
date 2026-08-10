from __future__ import annotations

import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "chatgpt-pro-review" / "SKILL.md"
PLUGIN = ROOT / "plugin.json"


class ChatGPTProReviewPackageTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for path in [SKILL, PLUGIN, ROOT / "README.md", ROOT / "LICENSE"]:
            self.assertTrue(path.is_file(), f"missing {path}")

    def test_plugin_manifest(self) -> None:
        plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

        self.assertEqual(
            plugin["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(plugin["name"], "chatgpt-pro-review")
        self.assertIn("code-review", plugin["keywords"])

    def test_skill_frontmatter_is_public_safe(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]

        self.assertIn("name: chatgpt-pro-review", frontmatter)
        self.assertIn("description: Use when ", frontmatter)
        self.assertIn("license: MIT", frontmatter)
        self.assertIn("compatibility:", frontmatter)
        self.assertIn("Before submitting private repo context", text)
        self.assertIn("Redact secrets", text)


if __name__ == "__main__":
    unittest.main()
