"""The Python floor is checked in one place, before any command does its work."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parent / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doctor  # noqa: E402
import python_floor  # noqa: E402

# Starts a command the way python3 would, and reports Python 3.8 from the
# moment the command imports python_floor. Exits 3 when the command loaded
# another module of the skill before the floor check.
OLD_PYTHON_DRIVER = """
import builtins, os, runpy, sys
script = sys.argv[1]
folder = os.path.dirname(script)
siblings = {name[:-3] for name in os.listdir(folder) if name.endswith(".py")}
real_import = builtins.__import__
def old_python(name, *args, **kwargs):
    if name == "python_floor":
        early = sorted((siblings - {"python_floor"}) & set(sys.modules))
        if early:
            print("loaded before the floor check: " + ", ".join(early), file=sys.stderr)
            raise SystemExit(3)
        sys.version_info = (3, 8, 20, "final", 0)
    return real_import(name, *args, **kwargs)
builtins.__import__ = old_python
sys.path.insert(0, folder)
sys.argv = [script, "--help"]
runpy.run_path(script, run_name="__main__")
"""
MAIN_GUARD = re.compile(r"""^if __name__ == ["']__main__["']:""", re.MULTILINE)


def commands() -> list[Path]:
    """Every script a user or agent can run directly."""
    return sorted(
        path for path in SCRIPTS.glob("*.py")
        if MAIN_GUARD.search(path.read_text(encoding="utf-8"))
    )


class FloorTests(unittest.TestCase):
    def test_floor_is_python_3_9(self):
        self.assertEqual(python_floor.MIN_PYTHON, (3, 9))
        self.assertEqual(python_floor.version_text(), "3.9")

    def test_supported_interpreters_pass(self):
        for version in [(3, 9, 0), (3, 9, 6), (3, 11, 9), (3, 15, 2), (4, 0, 0)]:
            with self.subTest(version=version):
                self.assertIsNone(python_floor.problem(version))
                python_floor.require(version)
        self.assertIsNone(python_floor.problem())
        self.assertIsNone(python_floor.problem(sys.version_info))

    def test_older_interpreters_stop_with_one_line(self):
        for version in [(3, 8, 20), (3, 7, 17), (3, 6, 15), (2, 7, 18)]:
            with self.subTest(version=version):
                message = python_floor.problem(version)
                self.assertEqual(message, (
                    f"watch-video needs Python 3.9 or newer, but {sys.executable} is Python "
                    f"{'.'.join(map(str, version))}. Run the script with a newer python3."
                ))
                self.assertNotIn("\n", message)
                with self.assertRaises(SystemExit) as stopped:
                    python_floor.require(version)
                self.assertEqual(stopped.exception.code, message)

    def test_doctor_reports_against_the_same_floor(self):
        self.assertEqual(doctor.check_python_version((3, 9, 6)), {
            "name": "python", "ok": True, "version": "3.9.6", "message": "ok",
            "fix": "Use Python 3.9 or newer.",
        })
        self.assertEqual(doctor.check_python_version((3, 8, 20)), {
            "name": "python", "ok": False, "version": "3.8.20",
            "message": "Python 3.9+ required", "fix": "Use Python 3.9 or newer.",
        })
        self.assertTrue(doctor.check_python_version()["ok"])


class CommandTests(unittest.TestCase):
    def test_every_command_is_covered(self):
        self.assertEqual([path.name for path in commands()], [
            "doctor.py", "extract_frames.py", "groq_transcribe.py", "local_analyze.py",
            "setup_local.py", "watch.py",
        ])

    def test_commands_stop_on_an_old_python_before_loading_the_skill(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        for script in commands():
            with self.subTest(command=script.name):
                result = subprocess.run(
                    [sys.executable, "-c", OLD_PYTHON_DRIVER, str(script)],
                    capture_output=True, text=True, env=env, timeout=60,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertRegex(result.stderr, (
                    r"^watch-video needs Python 3\.9 or newer, but \S.* is Python 3\.8\.20\. "
                    r"Run the script with a newer python3\.\n$"
                ))
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
