"""fetch_bookmarks_bird.sh builds the right bird command and passes its result on.

A fake `bird` on PATH prints the arguments it was given, so no test reaches X
or a browser's cookies.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from test_basic import SCRIPTS  # noqa: E402

SCRIPT = SCRIPTS / "fetch_bookmarks_bird.sh"
BASH = shutil.which("bash")
# Prints one argument to a line, then whatever the test asked for.
FAKE_BIRD = """#!/bin/sh
for argument in "$@"; do
  printf '%s\\n' "$argument"
done
if [ -n "${FAKE_BIRD_STDERR:-}" ]; then
  printf '%s\\n' "$FAKE_BIRD_STDERR" >&2
fi
exit "${FAKE_BIRD_STATUS:-0}"
"""


@unittest.skipUnless(BASH, "bash is not installed")
class BirdScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # PATH holds bash and nothing else, so only a bird placed here is found.
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()
        (self.bin / "bash").symlink_to(BASH)

    def install_bird(self) -> None:
        bird = self.bin / "bird"
        bird.write_text(FAKE_BIRD, encoding="utf-8")
        bird.chmod(0o755)

    def run_script(self, *argv: str, **environment: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(SCRIPT), *argv],
            env={"PATH": str(self.bin), **environment},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def bird_arguments(self, *argv: str) -> list[str]:
        self.install_bird()
        result = self.run_script(*argv)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout.splitlines()

    def test_the_script_can_be_run_directly_as_documented(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertEqual(SCRIPT.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env bash")

    def test_no_arguments_fetch_twenty_five_bookmarks_as_json(self) -> None:
        self.assertEqual(self.bird_arguments(), ["bookmarks", "--json", "--plain", "-n", "25"])

    def test_count_becomes_birds_short_option(self) -> None:
        for argv in (("--count", "7"), ("--count=7",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.bird_arguments(*argv), ["bookmarks", "--json", "--plain", "-n", "7"])

    def test_other_arguments_reach_bird_unchanged_and_in_order(self) -> None:
        self.assertEqual(self.bird_arguments("--all"), ["bookmarks", "--json", "--plain", "--all"])
        self.assertEqual(
            self.bird_arguments("--folder-id", "123", "--count", "5", "--chrome-profile", "Profile 2"),
            ["bookmarks", "--json", "--plain", "--folder-id", "123", "-n", "5", "--chrome-profile", "Profile 2"],
        )

    def test_count_without_a_value_stops_before_bird_runs(self) -> None:
        self.install_bird()

        result = self.run_script("--all", "--count")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "error: --count requires a value\n")

    def test_a_missing_bird_is_reported_with_a_fix(self) -> None:
        result = self.run_script("--count", "5")

        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "error: bird is not installed",
                "fix: install Bird from https://bird.fast/ or use your managed toolchain",
            ],
        )

    def test_birds_failure_and_message_are_passed_on(self) -> None:
        self.install_bird()

        result = self.run_script(
            "--count", "5", FAKE_BIRD_STATUS="1", FAKE_BIRD_STDERR="Failed to fetch bookmarks: HTTP 401"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Failed to fetch bookmarks: HTTP 401\n")
        self.assertEqual(result.stdout.splitlines(), ["bookmarks", "--json", "--plain", "-n", "5"])


if __name__ == "__main__":
    unittest.main()
