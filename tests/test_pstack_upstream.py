"""The upstream test runner confines writes and never enables fixture replacement."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class UpstreamTestRunnerTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "pstack_upstream_tests", ROOT / "scripts/test-pstack-upstream.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bundle = self.root / "packages/pstack"
        self.write("packages/pstack/codex/skills/statechart/scripts/test/a.test.ts", "fixture\n")
        self.write("packages/pstack/codex/skills/poteto-mode/scripts/bun.lock", "lock\n")
        self.write("packages/pstack/claude-code/README.md", "unaltered\n")
        self.write("integrations/pstack/test-toolchain/package.json", "{}\n")
        self.modules = self.root / "tools/node_modules"
        self.write("tools/node_modules/.bin/bun", "executable-placeholder\n")

    def write(self, path, body):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        return target

    def invoke(self, *args):
        with patch.object(sys, "argv", ["test", "--root", str(self.root), *args]):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return self.module.main()

    def test_test_writes_are_disposable_and_update_environment_is_removed(self):
        original = self.module.identity(self.bundle)
        calls = []

        def execute(command, cwd, env, timeout=900):
            self.assertNotIn("STATECHART_UPDATE", env)
            self.assertNotIn("TLA2TOOLS", env)
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            if "unittest" in command:
                self.assertEqual(env["PSTACK_TEST_BUN"], str(self.modules / ".bin/bun"))
                calls.append(command)
                return
            self.assertFalse(cwd.is_relative_to(self.bundle))
            (cwd / "fixture-write.txt").write_text("test writes here")
            calls.append(command)

        with patch.dict(os.environ, {"STATECHART_UPDATE": "1", "TLA2TOOLS": "wrong.jar"}):
            with patch.object(self.module, "run", side_effect=execute):
                with patch.object(self.module.subprocess, "check_output", return_value="1.3.13\n"):
                    self.assertEqual(self.invoke("--toolchain", str(self.modules)), 0)
        self.assertEqual(self.module.identity(self.bundle), original)
        self.assertEqual(len(calls), 5)
        self.assertIn("--frozen-lockfile", calls[1])
        self.assertIn("watch-pr", calls[2])

    def test_mutation_is_reported_even_when_test_command_fails(self):
        def execute(*args, **kwargs):
            self.write("packages/pstack/claude-code/README.md", "modified")
            raise ValueError("test failed")

        with patch.object(self.module, "run", side_effect=execute):
            with patch.object(self.module.subprocess, "check_output", return_value="1.3.13\n"):
                with self.assertRaisesRegex(RuntimeError, "authoritative bundle"):
                    self.invoke("--toolchain", str(self.modules))

    def test_missing_dependency_selection_and_wrong_tlc_fail_before_execution(self):
        with patch.object(self.module, "run") as run:
            with self.assertRaises(SystemExit):
                self.invoke()
            jar = self.write("wrong.jar", "not the locked tool")
            with self.assertRaises(SystemExit):
                self.invoke("--toolchain", str(self.modules), "--tlc", str(jar))
            with self.assertRaises(SystemExit):
                self.invoke("--toolchain", str(self.modules), "--install")
            run.assert_not_called()

    def test_wrong_bun_and_missing_test_closure_fail(self):
        with patch.object(self.module.subprocess, "check_output", return_value="9.0.0\n"):
            with self.assertRaises(SystemExit):
                self.invoke("--toolchain", str(self.modules))
        (self.bundle / "codex/skills/statechart/scripts/test/a.test.ts").unlink()
        with patch.object(self.module.subprocess, "check_output", return_value="1.3.13\n"):
            with self.assertRaisesRegex(RuntimeError, "closure"):
                self.invoke("--toolchain", str(self.modules))

    def test_install_is_limited_to_temporary_toolchain(self):
        def execute(command, cwd, env, timeout=900):
            if "unittest" not in command:
                self.assertFalse(cwd.is_relative_to(self.root))
            if command[0] == "npm":
                target = cwd / "node_modules/.bin/bun"
                target.parent.mkdir(parents=True)
                target.write_text("installed-tool")

        with patch.object(self.module, "run", side_effect=execute):
            with patch.object(self.module.subprocess, "check_output", return_value="1.3.13\n"):
                self.assertEqual(self.invoke("--install"), 0)

    def test_real_command_status_and_bounded_timeout_are_preserved(self):
        self.module.run([sys.executable, "-c", "pass"], self.root, dict(os.environ), timeout=3)
        with self.assertRaises(subprocess.CalledProcessError) as failed:
            self.module.run([sys.executable, "-c", "raise SystemExit(7)"],
                            self.root, dict(os.environ), timeout=3)
        self.assertEqual(failed.exception.returncode, 7)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.module.run([sys.executable, "-c", "import time; time.sleep(30)"],
                            self.root, dict(os.environ), timeout=0.2)


if __name__ == "__main__":
    unittest.main()
