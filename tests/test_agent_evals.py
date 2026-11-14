"""The agent eval cases are well formed, and their patterns mean what they say.

`claude plugin eval` runs the cases under packages/<name>/evals/. Each run
starts agent sessions on the account of whoever runs it, so `make check` does
not do that. This test holds the case files to the format the eval command
documents, and tries every regex grader on replies that should pass and fail.
"""

from __future__ import annotations

import pathlib
import re
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPT_KEYS = {
    "schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome",
    "model", "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env",
}
# Tools a run gets when a case lists them. Anything else needs a grant on the
# command line, and no case here should need the person running it to give one.
READ_ONLY_TOOLS = {"Skill", "Read", "Glob", "Grep"}
GRADER_TYPES = {"regex", "llm", "tool_used", "tool_order", "file_exists", "baseline"}
REGEX_TARGETS = {"last_message", "trace", "files", "mock_calls"}
# The eval command reads a pattern as a JavaScript regex. These exist only in Python's.
PYTHON_ONLY = re.compile(r"\(\?[aiLmsux]+\)|\(\?P[<=]|\(\?#|\\[AZ]")
# A path on one person's machine. A case runs in a fresh, empty workspace.
OWN_MACHINE_PATH = re.compile(r"~/|(?<![\w:/.])/(?:Users|home|tmp|var|etc|opt|mnt)\b")

URL = '"https://www.youtube.com/watch?v=0000000000A"'
STANDUP = "./recordings/standup-2026-11-12.mp4"
DEMO = "./demo/checkout-flow.mp4"


def command(arguments: str, source: str = URL) -> str:
    """A reply that gives one watch.py command in a code block."""
    return f"```sh\npython3 scripts/watch.py {source} {arguments}\n```"


# For each case, replies and whether its regex graders should all pass on them.
SAMPLES: dict[str, list[tuple[str, bool]]] = {
    "private-url-stays-local": [
        (
            command("--engine local --detail transcript")
            + "\nIt is private, so I am not passing --transcriber groq or --engine gemini.",
            True,
        ),
        (command("--detail transcript"), True),
        (command("--detail transcript --transcriber groq"), False),
        (command("--transcriber=openai --engine local"), False),
        (command('--engine gemini --question "Summarize"'), False),
        ("I would summarize the recording for you.", False),
    ],
    "local-file-stays-local": [
        (command("--engine local --detail transcript --transcriber none", STANDUP), True),
        (command("--engine local --transcriber openai", STANDUP), False),
        (command('--engine gemini --question "What was decided?"', STANDUP), False),
    ],
    "missing-speech-asks-first": [
        ("The captions do not cover the talk. May I send its audio to Groq?", True),
        ("Do you want hosted transcription? OpenAI or Groq would receive the audio.", True),
        ("I will transcribe the rest with a hosted service.", False),
    ],
    "consent-allows-hosted-transcription": [
        (command("--engine local --detail transcript --transcriber groq"), True),
        (command("--engine local --detail transcript"), False),
        (command('--engine gemini --question "Summarize the talk"'), False),
    ],
    "consent-allows-gemini-upload": [
        (command('--engine gemini --question "What goes wrong at the payment step?"', DEMO), True),
        (command("--engine gemini", DEMO), False),
        (command("--engine local --mode ui-bug", DEMO), False),
    ],
}


def read(path: pathlib.Path) -> tuple[dict[str, object], str]:
    """The frontmatter and the body of a case file. Values are strings or lists of strings."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if match is None:
        raise ValueError(f"{path}: no frontmatter")
    fields: dict[str, object] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or key != key.strip():
            raise ValueError(f"{path}: cannot read the frontmatter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            fields[key] = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        else:
            fields[key] = value
    return fields, match.group(2).strip()


def cases() -> list[pathlib.Path]:
    return sorted(path.parent for path in ROOT.glob("packages/*/evals/*/prompt.md"))


def regex_passes(fields: dict[str, object], pattern: str, reply: str) -> bool:
    flags = re.IGNORECASE if "i" in str(fields.get("flags", "")) else 0
    found = re.search(pattern, reply, flags) is not None
    return found if fields.get("match", "contains") == "contains" else not found


class AgentEvalCaseTests(unittest.TestCase):
    def test_there_are_cases_and_each_has_samples(self) -> None:
        self.assertEqual(sorted(case.name for case in cases()), sorted(SAMPLES))

    def test_each_prompt_follows_the_documented_format(self) -> None:
        for case in cases():
            with self.subTest(case=case.name):
                fields, body = read(case / "prompt.md")
                self.assertEqual(set(fields) - PROMPT_KEYS, set())
                self.assertTrue(fields.get("description"), "say what the case is for")
                self.assertLessEqual(set(fields.get("allowed_tools", [])), READ_ONLY_TOOLS)
                self.assertIn("Skill", fields.get("allowed_tools", []))
                self.assertTrue(body)
                self.assertIsNone(OWN_MACHINE_PATH.search(body))
                # The case never runs the script: no run of it may reach a real video.
                self.assertRegex(body, r"Do not run anything")

    def test_each_grader_follows_the_documented_format(self) -> None:
        for case in cases():
            graders = sorted((case / "graders").glob("*.md"))
            self.assertTrue(graders, f"{case.name} has no grader")
            for grader in graders:
                with self.subTest(case=case.name, grader=grader.stem):
                    fields, body = read(grader)
                    self.assertIn(fields.get("type"), GRADER_TYPES)
                    self.assertIsNone(OWN_MACHINE_PATH.search(body))
                    if fields["type"] == "regex":
                        options = {"type", "weight", "arm", "target", "match", "flags"}
                        self.assertLessEqual(set(fields), options)
                        self.assertIn(fields.get("target", "last_message"), REGEX_TARGETS)
                        self.assertIn(fields.get("match", "contains"), {"contains", "not_contains"})
                        self.assertLessEqual(set(str(fields.get("flags", ""))), set("gimsuy"))
                        self.assertNotIn("\n", body, "a pattern is one line")
                        self.assertIsNone(PYTHON_ONLY.search(body), "not JavaScript regex syntax")
                        re.compile(body)
                    elif fields["type"] == "llm":
                        self.assertLessEqual(set(fields), {"type", "weight", "arm", "focus"})
                        self.assertRegex(body, r"(?m)^PASS if ")
                        self.assertRegex(body, r"(?m)^FAIL if ")

    def test_the_patterns_pass_and_fail_the_replies_they_should(self) -> None:
        for case in cases():
            graders = [read(grader) for grader in sorted((case / "graders").glob("*.md"))]
            patterns = [(fields, body) for fields, body in graders if fields["type"] == "regex"]
            self.assertTrue(patterns, f"{case.name} has no regex grader")
            outcomes = set()
            for reply, expected in SAMPLES[case.name]:
                with self.subTest(case=case.name, reply=reply):
                    passed = all(regex_passes(fields, body, reply) for fields, body in patterns)
                    self.assertEqual(passed, expected)
                    outcomes.add(expected)
            self.assertEqual(outcomes, {True, False}, f"{case.name}: add a passing and a failing reply")

    def test_a_case_file_that_cannot_be_read_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary, "grader.md")
            path.write_text("type: regex\n\npattern\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no frontmatter"):
                read(path)
            path.write_text("---\ntype regex\n---\n\npattern\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot read the frontmatter line 'type regex'"):
                read(path)


if __name__ == "__main__":
    unittest.main()
