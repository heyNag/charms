"""Offline process and real-Bun/fake-GitHub acceptance for the Codex watcher."""

from contextlib import redirect_stderr, redirect_stdout
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "integrations/pstack/codex"
sys.path.insert(0, str(ROOT / "scripts"))
import pstack_transform as transform  # noqa: E402

spec = importlib.util.spec_from_file_location("watch_pr_supervisor", ADAPTER / "watch_pr/supervisor.py")
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


def executable(path, body):
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path


def assert_gone(test, path):
    test.assertTrue(path.is_file(), f"fixture did not reach its ready handshake: {path}")
    pids = [int(value) for value in path.read_text().split()]
    test.assertGreater(len(pids), 0)
    for pid in pids:
        with test.assertRaises(ProcessLookupError, msg=f"owned process {pid} survived"):
            os.kill(pid, 0)


@unittest.skipUnless(os.name == "posix", "POSIX process ownership")
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ)

    def run_command(self, body, seconds=2, limit=100_000):
        command = executable(self.root / "command", body)
        return supervisor.run([str(command)], self.root, self.env,
                              supervisor.Budget(seconds, limit))

    def test_captures_both_streams_and_exit(self):
        code, out, error = self.run_command(
            "import sys\nprint('hello')\nprint('detail', file=sys.stderr)\nsys.exit(7)\n")
        self.assertEqual((code, out, error), (7, b"hello\n", b"detail\n"))

    def test_deadline_kills_and_reaps_owned_tree(self):
        pids = self.root / "pids"
        self.env["TEST_PIDS"] = str(pids)
        self.env["TEST_CHILD_READY"] = str(self.root / "child-ready")
        started = time.monotonic()
        with self.assertRaises(supervisor.Incomplete) as raised:
            self.run_command('''import os, pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(os.environ['TEST_CHILD_READY']).touch(); time.sleep(60)"])
signal.signal(signal.SIGTERM, signal.SIG_IGN)
while not pathlib.Path(os.environ["TEST_CHILD_READY"]).exists():
    time.sleep(0.01)
open(os.environ["TEST_PIDS"], "w").write(f"{os.getpid()} {child.pid}")
time.sleep(60)
''', seconds=3)
        self.assertEqual(raised.exception.outcome, "DEADLINE")
        self.assertLess(time.monotonic() - started, 7)
        self.assertTrue(pids.is_file(), "deadline expired before the owned tree started")
        if sys.platform.startswith("linux"):
            assert_gone(self, pids)

    def test_leader_exit_cleans_orphan_holding_output_pipe(self):
        pids = self.root / "pids"
        self.env["TEST_PIDS"] = str(pids)
        # POSIX groups cover ordinary descendants. Detached-session adoption is
        # an additional Linux subreaper guarantee, not a portable host promise.
        for detached in ([False, True] if sys.platform.startswith("linux") else [False]):
            with self.subTest(detached=detached):
                started = time.monotonic()
                result = self.run_command('''import os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=DETACHED)
open(os.environ["TEST_PIDS"], "w").write(str(child.pid))
'''.replace("DETACHED", repr(detached)))
                self.assertEqual(result[0], 0)
                self.assertLess(time.monotonic() - started, 2)
                if sys.platform.startswith("linux"):
                    assert_gone(self, pids)

    def test_captured_output_is_bounded(self):
        with self.assertRaises(supervisor.Incomplete) as raised:
            self.run_command("import os\nwhile True: os.write(1, b'x' * 65536)\n", limit=1024)
        self.assertEqual(raised.exception.outcome, "OUTPUT_LIMIT")

    def fake_install(self, mode="okay"):
        source = self.root / "source"
        source.mkdir()
        (source / "package.json").write_text('{"dependencies":{"commander":"14.0.0"}}\n')
        self.env["TEST_INSTALL_STARTED"] = str(self.root / "install-started")
        bun = executable(self.root / "bun", '''import os, pathlib, sys, time
if sys.argv[1:] == ["--version"]:
    print("1.3.13")
else:
    pathlib.Path(os.environ["TEST_INSTALL_STARTED"]).touch()
    if MODE == "hang":
        time.sleep(60)
    path = pathlib.Path("node_modules/commander")
    path.mkdir(parents=True)
    (path / "package.json").write_text('{"version":"14.0.0"}')
'''.replace("MODE", repr(mode)))
        return source, bun

    def test_dependency_install_is_in_total_attempt_budget(self):
        source, bun = self.fake_install("hang")
        with self.assertRaises(supervisor.Incomplete) as raised:
            supervisor.prepare(source, self.root / "cache", str(bun), self.env,
                               supervisor.Budget(3, 100_000))
        self.assertEqual(raised.exception.outcome, "DEADLINE")
        self.assertTrue((self.root / "install-started").is_file(),
                        "deadline must exercise dependency installation, not only interpreter startup")
        self.assertEqual(list((self.root / "cache").glob("*/.ready")), [])
        self.assertFalse((source / "node_modules").exists())

    def test_cache_lock_wait_is_in_total_attempt_budget(self):
        source, bun = self.fake_install()
        budget = supervisor.Budget(2, 100_000)
        key, _ = supervisor.input_manifest(source, str(bun), b"1.3.13\n", budget)
        cache = self.root / "cache"
        cache.mkdir()
        with (cache / f"{key}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(supervisor.fcntl, "flock", wraps=fcntl.flock) as observed:
                with self.assertRaises(supervisor.Incomplete) as raised:
                    supervisor.prepare(source, cache, str(bun), self.env,
                                       supervisor.Budget(3, 100_000))
                self.assertGreater(observed.call_count, 1, "must retry the busy cache lock")
        self.assertEqual(raised.exception.outcome, "DEADLINE")
        self.assertFalse((self.root / "install-started").exists())

    def test_cache_is_external_bound_to_inputs_and_rejects_added_helpers(self):
        source, bun = self.fake_install()
        cache = supervisor.prepare(source, self.root / "cache", str(bun), self.env,
                                   supervisor.Budget(2, 100_000))
        key, rows = supervisor.input_manifest(source, str(bun), b"1.3.13\n",
                                              supervisor.Budget(2, 100_000))
        self.assertTrue(supervisor.cache_valid(cache, key, rows))
        (cache / "shadow.ts").write_text("unexpected executable input")
        self.assertFalse(supervisor.cache_valid(cache, key, rows))
        rebuilt = supervisor.prepare(source, self.root / "cache", str(bun), self.env,
                                     supervisor.Budget(2, 100_000))
        self.assertEqual(rebuilt, cache)
        self.assertFalse((cache / "shadow.ts").exists())
        self.assertFalse((source / "node_modules").exists())
        (source / "package.json").write_text("changed source\n")
        changed, _ = supervisor.input_manifest(source, str(bun), b"1.3.13\n",
                                               supervisor.Budget(2, 100_000))
        self.assertNotEqual(changed, key)

    def test_wall_clock_changes_cannot_extend_budget(self):
        with patch.object(supervisor.time, "time", side_effect=AssertionError("wall clock read")):
            budget = supervisor.Budget(0.02, 1024)
            time.sleep(0.03)
            with self.assertRaises(supervisor.Incomplete) as raised:
                budget.remaining()
        self.assertEqual(raised.exception.outcome, "DEADLINE")

    def test_dependency_receipt_rejects_changed_code_extra_files_and_external_symlinks(self):
        source, bun = self.fake_install()
        cache = supervisor.prepare(source, self.root / "cache", str(bun), self.env,
                                   supervisor.Budget(2, 100_000))
        key, rows = supervisor.input_manifest(source, str(bun), b"1.3.13\n",
                                              supervisor.Budget(2, 100_000))
        manifest = cache / "node_modules/commander/package.json"
        original = manifest.read_bytes()
        manifest.write_text('{"version":"14.0.0","main":"altered.js"}')
        self.assertFalse(supervisor.cache_valid(cache, key, rows))
        manifest.write_bytes(original)
        extra = manifest.parent / "altered.js"
        extra.write_text("unexpected executable input")
        self.assertFalse(supervisor.cache_valid(cache, key, rows))
        extra.unlink()
        self.assertTrue(supervisor.cache_valid(cache, key, rows))
        outside = self.root / "outside-dependencies"
        shutil.move(str(cache / "node_modules"), outside)
        os.symlink(outside, cache / "node_modules")
        self.assertFalse(supervisor.cache_valid(cache, key, rows))
        (cache / "node_modules").unlink()
        (cache / "node_modules").mkdir()
        os.symlink(outside / "commander", cache / "node_modules/commander")
        self.assertFalse(supervisor.cache_valid(cache, key, rows))

    def test_non_regular_cache_receipt_is_rejected_without_opening(self):
        source, bun = self.fake_install()
        cache = supervisor.prepare(source, self.root / "cache", str(bun), self.env,
                                   supervisor.Budget(2, 100_000))
        key, rows = supervisor.input_manifest(source, str(bun), b"1.3.13\n",
                                              supervisor.Budget(2, 100_000))
        receipt = cache / ".dependencies.json"
        receipt.unlink()
        os.mkfifo(receipt)
        self.assertFalse(supervisor.cache_valid(cache, key, rows))


class SupervisorCliTests(unittest.TestCase):
    """Exercise the maintained CLI; only dependency/process I/O is substituted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.payload = self.root / "plugin"
        self.entry = self.payload / "adapters/codex/watch_pr/supervisor.py"
        self.entry.parent.mkdir(parents=True)
        self.entry.write_text("# Disposable payload location for the maintained CLI.\n")
        self.cache = self.root / "cache"
        self.ready = {"wrapperSchemaVersion": 1, "outcome": "UPSTREAM", "complete": True,
                      "upstream": {"schemaVersion": 1, "kind": "READY", "terminal": True,
                                   "exitCode": 0}}

    def invoke(self, argv=(), *, bun="/toolchain/bun", prepare=None, run=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            with (patch.object(supervisor, "__file__", str(self.entry)),
                  patch.object(supervisor.shutil, "which", return_value=bun),
                  patch.object(supervisor, "prepare", return_value=self.cache,
                               side_effect=prepare) as prepared,
                  patch.object(supervisor, "run", side_effect=run) as executed,
                  redirect_stdout(stdout), redirect_stderr(stderr)):
                code = supervisor.main(["--cache-dir", str(self.cache),
                                        "--attempt-timeout", "2", *argv])
        finally:
            for sig, handler in handlers.items():
                self.assertIs(signal.getsignal(sig), handler, "CLI must restore caller handlers")
        return code, stdout.getvalue(), stderr.getvalue(), prepared, executed

    def assert_incomplete(self, result, outcome, code):
        actual, stdout, _, _, _ = result
        self.assertEqual(actual, code)
        self.assertLess(len(stdout.encode()), 4096)
        record = json.loads(stdout)
        self.assertEqual(record["wrapperSchemaVersion"], 1)
        self.assertEqual(record["outcome"], outcome)
        self.assertEqual(record["exitCode"], code)
        self.assertFalse(record["complete"])
        self.assertNotIn("upstream", record)

    def test_missing_runtime_and_cache_inside_plugin_fail_before_execution(self):
        result = self.invoke(bun=None)
        self.assert_incomplete(result, "DEPENDENCY_UNAVAILABLE", 69)
        result[3].assert_not_called()
        result[4].assert_not_called()
        for path in (self.payload, self.payload / "nested/cache"):
            with self.subTest(cache=path):
                result = self.invoke(["--cache-dir", str(path)])
                self.assert_incomplete(result, "INVALID_CONFIGURATION", 64)
                result[3].assert_not_called()
                result[4].assert_not_called()
        self.assertFalse((self.payload / "nested").exists())

    def test_progress_streams_once_and_ready_waits_for_verified_exit(self):
        progress = {"wrapperSchemaVersion": 1, "outcome": "PROGRESS", "complete": False,
                    "upstream": {"kind": "WAITING", "terminal": False}}
        encoded = b"".join((json.dumps(row) + "\n").encode() for row in (progress, self.ready))
        now = [100.0]
        original_env = {key: os.environ.get(key) for key in
                        ("PSTACK_WATCH_REMAINING_MS", "PSTACK_WATCH_OUTPUT_LIMIT",
                         "PSTACK_WATCH_UNTIL_READY")}

        def prepare(source, cache, bun, env, budget):
            self.assertEqual(source, self.payload / "skills/poteto-mode/scripts")
            self.assertEqual(cache, self.cache)
            self.assertEqual(bun, "/toolchain/bun")
            now[0] += 0.4  # Dependency I/O consumes the same total attempt budget.
            budget.charge(64)
            return self.cache

        def run(command, cwd, env, budget, on_stdout):
            self.assertEqual(command, ["/toolchain/bun", str(self.cache / "watch-pr/codex-main.ts"),
                                       "--timeout", "1.5", "--pr", "1"])
            self.assertEqual(cwd, Path.cwd())
            self.assertAlmostEqual(float(env["PSTACK_WATCH_REMAINING_MS"]), 1100)
            self.assertEqual(env["PSTACK_WATCH_OUTPUT_LIMIT"], str(4096 - 64))
            self.assertEqual(env["PSTACK_WATCH_UNTIL_READY"], "0")
            # Chunk boundaries may split records; the terminal is withheld until
            # run() has returned its process cleanup/exit result.
            on_stdout(encoded[:11])
            self.assertEqual(sys.stdout.getvalue(), "")
            on_stdout(encoded[11:])
            self.assertEqual([json.loads(line) for line in sys.stdout.getvalue().splitlines()],
                             [progress])
            return 0, encoded, b"diagnostic from gh\n"

        with patch.object(supervisor.time, "monotonic", side_effect=lambda: now[0]):
            result = self.invoke(["--output-limit", "4096", "--", "--timeout", "1.5",
                                  "--pr", "1"], prepare=prepare, run=run)
        self.assertEqual(result[0], 0)
        self.assertEqual([json.loads(line) for line in result[1].splitlines()], [progress, self.ready])
        self.assertEqual(result[2], "diagnostic from gh\n")
        self.assertEqual(original_env, {key: os.environ.get(key) for key in original_env})

    def test_invalid_terminal_and_exit_mismatch_never_publish_ready(self):
        good = (json.dumps(self.ready) + "\n").encode()
        invalid = json.dumps({**self.ready, "wrapperSchemaVersion": 2}).encode() + b"\n"
        for code, output, outcome in (
            (0, b"", "EXECUTION_ERROR"),
            (0, good + good, "EXECUTION_ERROR"),
            (0, b"not json\n", "EXECUTION_ERROR"),
            (0, invalid, "INVALID_OUTPUT"),
            (0, b"[]\n", "INVALID_OUTPUT"),
            (0, b"42\n", "INVALID_OUTPUT"),
            (0, b"null\n", "INVALID_OUTPUT"),
            (0, b'"READY"\n', "INVALID_OUTPUT"),
            (0, (json.dumps({**self.ready, "upstream": []}) + "\n").encode(), "INVALID_OUTPUT"),
            (125, good, "CLEANUP_FAILED"),
        ):
            with self.subTest(output=output, code=code):
                def run(command, cwd, env, budget, on_stdout):
                    on_stdout(output)
                    return code, output, b""

                self.assert_incomplete(self.invoke(run=run), outcome, 70)

    def test_dependency_failure_and_interrupt_restore_existing_handlers(self):
        failure = self.invoke(prepare=OSError("dependency cache unavailable"))
        self.assert_incomplete(failure, "EXECUTION_ERROR", 70)
        failure[4].assert_not_called()
        saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def caller_handler(*_):
            self.fail("the caller handler must not handle the attempt's interruption")

        try:
            for sig in saved:
                signal.signal(sig, caller_handler)

            def run(command, cwd, env, budget, on_stdout):
                handler = signal.getsignal(signal.SIGTERM)
                self.assertIsNot(handler, caller_handler)
                handler(signal.SIGTERM, None)
                budget.remaining()
                self.fail("interrupted budget must not return a result")

            self.assert_incomplete(self.invoke(run=run), "INTERRUPTED", 130)
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)

    def test_selected_queue_mode_pretty_output_and_zero_timeout_stay_bounded(self):
        record = {"wrapperSchemaVersion": 1, "outcome": "MERGE_READY", "complete": True,
                  "upstream": {"kind": "WAITING", "terminal": False}}

        def run(command, cwd, env, budget, on_stdout):
            self.assertEqual(env["PSTACK_WATCH_UNTIL_READY"], "1")
            self.assertGreater(float(env["PSTACK_WATCH_REMAINING_MS"]), 0)
            self.assertLessEqual(float(env["PSTACK_WATCH_REMAINING_MS"]), 2000)
            output = (json.dumps(record) + "\n").encode()
            on_stdout(output)
            return 0, output, b""

        result = self.invoke(["--until-merge-ready", "--pretty", "--", "--queued-stack",
                              "--stack-prs", "1", "--timeout=0"], run=run)
        self.assertEqual(result[0], 0)
        self.assertEqual(json.loads(result[1]), record)
        self.assertIn('\n  "upstream": {', result[1])

    def test_configuration_usage_errors_do_not_install_or_change_handlers(self):
        for argv in (["--attempt-timeout", "0"], ["--output-limit", "100"],
                     ["--until-merge-ready"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                self.invoke(argv, prepare=AssertionError("must not install"),
                            run=AssertionError("must not launch"))
            self.assertEqual(raised.exception.code, 2)


FAKE_GH = r'''import json, os, pathlib, signal, subprocess, sys, time
args = sys.argv[1:]
mode = os.environ.get("TEST_GH_MODE", "ready")
state_path = pathlib.Path(os.environ["TEST_STATE"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"identities": {}}
with open(os.environ["TEST_CALLS"], "a") as log:
    log.write(json.dumps(args) + "\n")
def save():
    state_path.write_text(json.dumps(state))
def out(value):
    save()
    print(json.dumps(value))
    sys.exit(0)
if mode in {"hang", "leader-exit"}:
    child = subprocess.Popen([sys.executable, "-c", "import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(os.environ['TEST_CHILD_READY']).touch(); time.sleep(60)"])
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while not pathlib.Path(os.environ["TEST_CHILD_READY"]).exists():
        time.sleep(0.01)
    pathlib.Path(os.environ["TEST_PIDS"]).write_text(f"{os.getpid()} {child.pid}")
    if mode == "leader-exit":
        sys.exit(0)
    time.sleep(60)
if mode == "flood":
    while True:
        os.write(1, b"x" * 65536)
if args[:2] == ["pr", "list"]:
    out([{"number": 1, "headRefName": "feature", "baseRefName": "main", "isCrossRepository": False}])
if args[:2] == ["pr", "view"]:
    fields = args[args.index("--json") + 1]
    if fields == "number,url":
        out({"number": 1, "url": "https://github.com/example/repo/pull/1"})
    number = args[2]
    head, base = "a" * 40, "b" * 40
    if state.get("head_changed"):
        head = "c" * 40
    if state.get("base_changed"):
        base = "d" * 40
    merged = mode == "merged"
    facts = {"mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED",
             "headRefOid": head, "baseRefOid": base, "headRefName": "feature", "baseRefName": "main",
             "state": "MERGED" if merged else "OPEN", "mergedAt": "2026-01-01T00:00:00Z" if merged else None,
             "isDraft": False}
    if "baseRefOid" in fields:
        count = state["identities"].get(number, 0) + 1
        state["identities"][number] = count
        if mode == "handoff-head" and count >= 3:
            facts["headRefOid"] = "c" * 40
        if mode == "handoff-base" and count >= 3:
            facts["baseRefOid"] = "d" * 40
        if mode == "missing-base":
            facts["baseRefOid"] = None
    elif mode == "base-during-facts":
        state["base_changed"] = True
    elif mode == "head-during-facts":
        state["head_changed"] = True
    out({field: facts[field] for field in fields.split(",")})
if args[:2] == ["pr", "checks"]:
    if mode == "head-after-checks":
        state["head_changed"] = True
    if mode == "base-after-checks":
        state["base_changed"] = True
    if mode in {"no-checks", "check-pagination"}:
        out([])
    out([{"name": "unit", "state": "SUCCESS", "bucket": "pass", "workflow": "ci", "description": "", "link": ""}])
if args[:2] == ["api", "graphql"]:
    query = next(value for value in args if value.startswith("query="))
    if "query ReviewThreads" in query:
        endless = mode == "thread-pagination"
        value = {"reviewThreads": {"nodes": [], "pageInfo": {"hasNextPage": endless, "endCursor": "again" if endless else None}}}
    elif "query PrCheckRollup" in query:
        if mode == "check-pagination":
            value = {"commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {
                "nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "again"}}}}}]}}
        else:
            value = {"commits": {"nodes": []}}
    elif "query PrCommitStatuses" in query:
        value = {"commits": {"nodes": [{"commit": {"oid": "a" * 40, "statusCheckRollup": {"state": "SUCCESS"}}}]}}
    else:
        raise RuntimeError("unexpected graph query")
    out({"data": {"repository": {"pullRequest": value}}})
raise RuntimeError("unexpected fake-gh invocation")
'''


BUN = os.environ.get("PSTACK_TEST_BUN")


@unittest.skipUnless(BUN and Path(BUN).is_file(), "set PSTACK_TEST_BUN to pinned Bun for fake-gh tests")
class RealWatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.plugin = cls.root / "plugin"
        cls.source = cls.plugin / "skills/poteto-mode/scripts"
        # This exact Claude copy is a test fixture only; production always projects
        # from the canonical source lock. Every changed file still has its SHA guard.
        shutil.copytree(ROOT / "packages/pstack/claude-code/skills/poteto-mode/scripts", cls.source)
        rules = json.loads((ADAPTER / "transforms/rules.json").read_text())
        for relative, rule in rules["files"].items():
            if relative.startswith("skills/poteto-mode/scripts/"):
                target = cls.plugin / relative
                data, _ = transform.apply_edits(relative, target.read_bytes(), rule)
                target.write_bytes(data)
        for name in ("codex-main.ts", "codex-transport.ts"):
            shutil.copyfile(ADAPTER / "watch_pr" / name, cls.source / "watch-pr" / name)
        for name in ("watch_pr/supervisor.py", "providers/process_supervisor.py"):
            target = cls.plugin / "adapters/codex" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ADAPTER / name, target)
        cls.runner = cls.source / "watch-pr/watch-pr"
        cls.bin = cls.root / "bin"
        cls.bin.mkdir()
        os.symlink(str(Path(BUN).resolve()), cls.bin / "bun")
        executable(cls.bin / "gh", FAKE_GH)
        executable(cls.bin / "git", '''import os, pathlib, time
if os.environ.get("TEST_GH_MODE") == "discovery-hang":
    pathlib.Path(os.environ["TEST_DISCOVERY_READY"]).touch()
    time.sleep(60)
print("https://github.com/example/repo.git")
''')
        cls.env = {**os.environ, "PATH": f"{cls.bin}:{os.environ['PATH']}",
                   "PYTHONDONTWRITEBYTECODE": "1"}
        cls.cache = cls.root / "cache"
        cls.prepared = supervisor.prepare(cls.source, cls.cache, str(cls.bin / "bun"), cls.env,
                                          supervisor.Budget(60, 8 * 1024 * 1024))
        cls.source_before = {str(path.relative_to(cls.plugin)): path.read_bytes()
                             for path in cls.plugin.rglob("*") if path.is_file()}

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.cwd = Path(self.case.name)
        self.env = {**self.env, "TEST_STATE": str(self.cwd / "state"),
                    "TEST_CALLS": str(self.cwd / "calls"), "TEST_PIDS": str(self.cwd / "pids"),
                    "TEST_CHILD_READY": str(self.cwd / "child-ready"),
                    "TEST_DISCOVERY_READY": str(self.cwd / "discovery-ready")}

    def command(self, options=(), upstream=(), explicit=True):
        return [sys.executable, str(self.runner), "--cache-dir", str(self.cache),
                "--attempt-timeout", "5", *options, "--",
                *( ["--owner", "example", "--repo", "repo", "--pr", "1"] if explicit else []),
                *upstream]

    def attempt(self, mode="ready", options=(), upstream=(), explicit=True):
        result = subprocess.run(self.command(options, upstream, explicit),
                                env={**self.env, "TEST_GH_MODE": mode}, cwd=self.cwd,
                                text=True, capture_output=True, timeout=20)
        self.assertTrue(result.stdout.strip(), result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        for record in records:
            self.assertEqual(record["wrapperSchemaVersion"], 1)
        self.assertEqual(self.source_before, {str(path.relative_to(self.plugin)): path.read_bytes()
                                             for path in self.plugin.rglob("*") if path.is_file()})
        return result, records

    def test_ready_preserves_raw_verdict_and_binds_actual_revisions(self):
        result, records = self.attempt()
        self.assertEqual(result.returncode, 0, result.stderr)
        final = records[-1]
        self.assertEqual(final["outcome"], "UPSTREAM")
        self.assertEqual(final["upstream"]["kind"], "READY")
        self.assertTrue(final["complete"])
        binding = final["revisionBindings"][0]["identity"]
        self.assertEqual(binding["headRefOid"], "a" * 40)
        self.assertEqual(binding["baseRefOid"], "b" * 40)
        self.assertEqual(json.loads((self.cwd / "state").read_text())["identities"], {"1": 3})

    def test_changed_facts_checks_or_handoff_never_produce_ready(self):
        for mode in ("base-during-facts", "head-during-facts", "head-after-checks",
                     "base-after-checks", "handoff-head", "handoff-base"):
            with self.subTest(mode=mode):
                (self.cwd / "state").unlink(missing_ok=True)
                result, records = self.attempt(mode)
                self.assertEqual(result.returncode, 75, (mode, result.stderr, result.stdout))
                self.assertEqual(records[-1]["outcome"], "STALE_SNAPSHOT")
                self.assertFalse(records[-1]["complete"])
                self.assertFalse(any(r.get("upstream", {}).get("kind") == "READY" for r in records))

    def test_missing_actual_base_is_incomplete(self):
        result, records = self.attempt("missing-base")
        self.assertEqual(result.returncode, 75)
        self.assertEqual(records[-1]["outcome"], "SNAPSHOT_UNAVAILABLE")
        self.assertFalse(records[-1]["complete"])

    def test_status_and_no_checks_keep_source_meanings(self):
        result, records = self.attempt(upstream=["--status-only"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(records[-1]["upstream"]["kind"], "STATUS")
        (self.cwd / "state").unlink()
        result, records = self.attempt("no-checks", upstream=["--status-only", "--max-query-errors", "1"])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(records[-1]["upstream"]["kind"], "BLOCKER")
        self.assertEqual(records[-1]["upstream"]["blocker"]["failure"]["kind"], "checks-unavailable")
        self.assertFalse(records[-1]["complete"])

    def test_queued_ready_is_adapter_outcome_and_complete_requires_observed_merge(self):
        queue = ["--queued-stack", "--stack-prs", "1"]
        result, records = self.attempt(options=["--until-merge-ready"], upstream=queue)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[-1]["outcome"], "MERGE_READY")
        self.assertEqual(records[-1]["upstream"]["kind"], "WAITING")
        self.assertFalse(any(r.get("upstream", {}).get("kind") == "READY" for r in records))
        (self.cwd / "state").unlink()
        result, records = self.attempt("merged", upstream=queue)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[-1]["upstream"]["kind"], "COMPLETE")
        calls = [json.loads(line) for line in (self.cwd / "calls").read_text().splitlines()]
        self.assertFalse(any(call[:2] == ["pr", "merge"] for call in calls))

    def test_no_implicit_queued_handoff_and_zero_timeout_cannot_disable_budget(self):
        result, records = self.attempt(options=["--attempt-timeout", "4"],
            upstream=["--queued-stack", "--stack-prs", "1", "--timeout", "0"])
        self.assertEqual(result.returncode, 124)
        self.assertEqual(records[-1]["outcome"], "DEADLINE")
        self.assertFalse(records[-1]["complete"])
        self.assertTrue(any(r["outcome"] == "PROGRESS"
                            and r.get("upstream", {}).get("kind") == "WAITING"
                            for r in records), "must reach the merge-queue wait before timing out")

    def test_hung_gh_tree_and_leader_exit_are_reaped(self):
        for mode in ("hang", "leader-exit"):
            with self.subTest(mode=mode):
                for name in ("pids", "child-ready"):
                    (self.cwd / name).unlink(missing_ok=True)
                started = time.monotonic()
                result, records = self.attempt(mode, options=["--attempt-timeout", "4"])
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertEqual(records[-1]["outcome"], "DEADLINE")
                self.assertFalse(records[-1]["complete"])
                self.assertLess(time.monotonic() - started, 10)
                self.assertTrue((self.cwd / "pids").is_file(),
                                "deadline must exercise the started gh tree")
                if sys.platform.startswith("linux"):
                    assert_gone(self, self.cwd / "pids")

    def test_discovery_and_unending_pagination_share_attempt_deadline(self):
        for mode in ("discovery-hang", "thread-pagination", "check-pagination"):
            with self.subTest(mode=mode):
                (self.cwd / "state").unlink(missing_ok=True)
                (self.cwd / "calls").unlink(missing_ok=True)
                result, records = self.attempt(mode, options=["--attempt-timeout", "3"],
                                                explicit=mode != "discovery-hang",
                                                upstream=["--pr", "1"] if mode == "discovery-hang" else [])
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertEqual(records[-1]["outcome"], "DEADLINE")
                if mode == "discovery-hang":
                    self.assertTrue((self.cwd / "discovery-ready").is_file())
                else:
                    query = "query ReviewThreads" if mode == "thread-pagination" else "query PrCheckRollup"
                    calls = [json.loads(line) for line in (self.cwd / "calls").read_text().splitlines()]
                    pages = [call for call in calls if any(query in part for part in call)]
                    self.assertGreater(len(pages), 1, "must attempt multiple pages before timing out")

    def test_flood_is_incomplete_output_limit(self):
        result, records = self.attempt("flood", options=["--output-limit", "4096"])
        self.assertEqual(result.returncode, 125, result.stderr)
        self.assertEqual(records[-1]["outcome"], "OUTPUT_LIMIT")
        self.assertFalse(records[-1]["complete"])
        self.assertLess(len(result.stdout), 4096)

    def test_interrupt_kills_and_reaps_owned_gh_tree(self):
        process = subprocess.Popen(self.command(), cwd=self.cwd,
            env={**self.env, "TEST_GH_MODE": "hang"}, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 4
            while not (self.cwd / "pids").exists() and time.monotonic() < until:
                time.sleep(0.02)
            self.assertTrue((self.cwd / "pids").exists())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130, stderr)
            self.assertEqual(json.loads(stdout.splitlines()[-1])["outcome"], "INTERRUPTED")
            if sys.platform.startswith("linux"):
                assert_gone(self, self.cwd / "pids")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_invalid_usage_and_help_are_not_readiness(self):
        result, records = self.attempt(upstream=["--not-an-option"])
        self.assertEqual(result.returncode, 64)
        self.assertEqual(records[-1]["outcome"], "USAGE")
        result, records = self.attempt(upstream=["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(records[-1]["outcome"], "HELP")
        self.assertFalse(records[-1]["complete"])

    def test_cache_cannot_be_placed_inside_installed_plugin(self):
        result, records = self.attempt(options=["--cache-dir", str(self.plugin / "cache")])
        self.assertEqual(result.returncode, 64)
        self.assertEqual(records[-1]["outcome"], "INVALID_CONFIGURATION")
        self.assertFalse((self.plugin / "cache").exists())

    def test_upstream_watcher_suites_and_types_survive_guarded_adaptation(self):
        suite = self.cwd / "suite"
        shutil.copytree(self.source, suite)
        for command in ([str(BUN), "install", "--frozen-lockfile", "--ignore-scripts"],
                        [str(BUN), "test", "watch-pr"], [str(BUN), "run", "typecheck"]):
            with self.subTest(command=command):
                result = subprocess.run(command, cwd=suite, env=self.env,
                                        text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
