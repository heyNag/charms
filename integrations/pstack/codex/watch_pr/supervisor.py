#!/usr/bin/env python3
"""Bound a watcher attempt, including dependency setup and every child process."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable

sys.dont_write_bytecode = True
INSTALL_ARGS = ["install", "--frozen-lockfile", "--ignore-scripts", "--production"]


class Incomplete(Exception):
    def __init__(self, outcome: str, detail: str, code: int):
        super().__init__(detail)
        self.outcome, self.code = outcome, code


class Budget:
    def __init__(self, seconds: float, output_limit: int):
        self.deadline = time.monotonic() + seconds
        self.limit = output_limit
        self.bytes = 0
        self.interrupted = False

    def remaining(self) -> float:
        if self.interrupted:
            raise Incomplete("INTERRUPTED", "watcher attempt interrupted", 130)
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Incomplete("DEADLINE", "watcher monotonic attempt deadline expired", 124)
        return left

    def charge(self, count: int) -> None:
        self.bytes += count
        if self.bytes > self.limit:
            raise Incomplete("OUTPUT_LIMIT", "watcher captured-output budget exhausted", 125)


def terminate_group(process: subprocess.Popen, supervised: bool = False) -> None:
    """Reap the direct child and stop all descendants, including after parent exit."""
    if supervised:
        # The dedicated Linux subreaper owns a separate command process group.
        # Give it time to kill/reap that tree; killing the wrapper first loses ownership.
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
            raise Incomplete("CLEANUP_FAILED", "watcher descendant cleanup is unverified", 70)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    limit = time.monotonic() + 0.25
    while process.poll() is None and time.monotonic() < limit:
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise Incomplete("CLEANUP_FAILED", "watcher process did not terminate", 70)


def run(command: list[str], cwd: Path, env: dict[str, str], budget: Budget,
        on_stdout: Callable[[bytes], None] | None = None) -> tuple[int, bytes, bytes]:
    budget.remaining()
    supervised = sys.platform.startswith("linux")
    if supervised:
        helper = Path(__file__).resolve().parents[1] / "providers/process_supervisor.py"
        if not helper.is_file():
            raise Incomplete("INVALID_RUNTIME", "watcher process supervisor is missing", 70)
        command = [sys.executable, str(helper), "--", *command]
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            assert pipe is not None
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map():
            left = budget.remaining()
            for key, _ in selector.select(min(left, 0.05)):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                budget.charge(len(chunk))
                output[key.data].extend(chunk)
                if key.data == "stdout" and on_stdout is not None:
                    on_stdout(chunk)
            # Descendants cannot keep the attempt alive after its root exits.
            if process.poll() is not None:
                terminate_group(process, supervised)
        code = process.wait(timeout=max(0.01, budget.remaining()))
        return code, bytes(output["stdout"]), bytes(output["stderr"])
    finally:
        selector.close()
        terminate_group(process, supervised)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise Incomplete("INVALID_RUNTIME", "watcher source must be a real directory", 70)
    result = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in {"node_modules", "__pycache__"})
        for name in dirs:
            if (Path(current) / name).is_symlink():
                raise Incomplete("INVALID_RUNTIME", "symlink in watcher source", 70)
        for name in sorted(names):
            path = Path(current) / name
            if path.suffix == ".pyc":
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise Incomplete("INVALID_RUNTIME", "non-regular watcher source", 70)
            result.append(path)
    return result


def input_manifest(source: Path, bun: str, version: bytes, budget: Budget) -> tuple[str, list[dict]]:
    rows = []
    for path in files(source):
        budget.remaining()
        rows.append({"path": path.relative_to(source).as_posix(),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "size": path.stat().st_size,
                     "mode": stat.S_IMODE(path.stat().st_mode)})
    identity = {"files": rows, "install_args": INSTALL_ARGS, "bun": str(Path(bun).resolve()),
                "bun_version": version.decode("utf-8").strip(),
                "platform": platform.system(), "machine": platform.machine()}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return key, rows


def dependency_manifest(root: Path, budget: Budget | None = None) -> list[dict]:
    """Inventory a frozen install without following directory or external symlinks."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("dependency root must be a real directory")
    rows, total = [], 0
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            if budget:
                budget.remaining()
            path = Path(current) / name
            info = path.lstat()
            row = {"path": path.relative_to(root).as_posix(),
                   "mode": stat.S_IMODE(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                if name in dirs or Path(target).is_absolute() or not resolved.is_relative_to(root):
                    raise ValueError("dependency symlink escapes or replaces a directory")
                if not resolved.is_file():
                    raise ValueError("dependency symlink target is not a file")
                row.update(kind="symlink", target=target)
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind="directory")
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_size > 128 * 1024 * 1024 or total > 512 * 1024 * 1024:
                    raise ValueError("dependency tree exceeds validation budget")
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        if budget:
                            budget.remaining()
                        digest.update(chunk)
                row.update(kind="file", size=info.st_size, sha256=digest.hexdigest())
            else:
                raise ValueError("non-regular dependency")
            rows.append(row)
        dirs.sort()
    return sorted(rows, key=lambda row: row["path"])


def cache_valid(cache: Path, key: str, rows: list[dict], budget: Budget | None = None) -> bool:
    if not cache.is_dir() or cache.is_symlink():
        return False
    try:
        ready = cache / ".ready"
        receipt = cache / ".dependencies.json"
        if not stat.S_ISREG(ready.lstat().st_mode) or ready.stat().st_size != len(key) * 2 + 2:
            return False
        if not stat.S_ISREG(receipt.lstat().st_mode) or receipt.stat().st_size > 2 * 1024 * 1024:
            return False
        receipt_data = receipt.read_bytes()
        receipt_hash = hashlib.sha256(receipt_data).hexdigest()
        if ready.read_text() != f"{key}\n{receipt_hash}\n":
            return False
        installed = json.loads(receipt_data)
        if installed != {"schema_version": 1, "input_key": key,
                          "files": dependency_manifest(cache / "node_modules", budget)}:
            return False
        manifest = cache / "node_modules/commander/package.json"
        if manifest.stat().st_size > 1024 * 1024:
            return False
        commander = json.loads(manifest.read_text())
        if commander.get("version") != "14.0.0":
            return False
        actual = {path.relative_to(cache).as_posix() for path in files(cache)}
        if actual != {".ready", ".dependencies.json", *(row["path"] for row in rows)}:
            return False
        for row in rows:
            path = cache / row["path"]
            if path.is_symlink() or not path.is_file():
                return False
            if path.stat().st_size != row["size"]:
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                return False
            if stat.S_IMODE(path.stat().st_mode) != row["mode"]:
                return False
        return True
    except (OSError, ValueError, Incomplete):
        return False


def prepare(source: Path, cache_base: Path, bun: str, env: dict[str, str], budget: Budget) -> Path:
    code, version, _ = run([bun, "--version"], source, env, budget)
    if code:
        raise Incomplete("DEPENDENCY_UNAVAILABLE", "Bun version probe failed", 69)
    key, rows = input_manifest(source, bun, version, budget)
    cache_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if cache_base.is_symlink():
        raise Incomplete("INVALID_CONFIGURATION", "cache root cannot be a symlink", 64)
    cache = cache_base / key
    lock_path = cache_base / f"{key}.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        while True:
            budget.remaining()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.05, budget.remaining()))
        if cache_valid(cache, key, rows, budget):
            return cache
        staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=cache_base))
        try:
            for row in rows:
                budget.remaining()
                destination = staging / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / row["path"], destination)
                destination.chmod(row["mode"])
            code, _, _ = run([bun, *INSTALL_ARGS], staging, env, budget)
            if code:
                raise Incomplete("DEPENDENCY_UNAVAILABLE", "locked watcher dependency install failed", 69)
            receipt = json.dumps({"schema_version": 1, "input_key": key,
                                  "files": dependency_manifest(staging / "node_modules", budget)},
                                 sort_keys=True, separators=(",", ":")).encode()
            (staging / ".dependencies.json").write_bytes(receipt)
            (staging / ".ready").write_text(f"{key}\n{hashlib.sha256(receipt).hexdigest()}\n")
            if not cache_valid(staging, key, rows, budget):
                raise Incomplete("DEPENDENCY_UNAVAILABLE", "watcher cache failed validation", 69)
            if cache.exists():
                if cache.is_symlink():
                    raise Incomplete("INVALID_CONFIGURATION", "watcher cache entry is a symlink", 64)
                shutil.rmtree(cache)
            os.replace(staging, cache)
            return cache
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def positive(value: str) -> float:
    result = float(value)
    if not 0 < result <= 86400:
        raise argparse.ArgumentTypeError("attempt timeout must be > 0 and <= 86400 seconds")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--attempt-timeout", type=positive, default=900.0,
                        help="Total monotonic budget including setup; default 900 seconds.")
    parser.add_argument("--output-limit", type=int, default=8 * 1024 * 1024,
                        help="Captured-output limit in bytes; default 8 MiB.")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
                        / "pstack/watch-pr")
    parser.add_argument("--until-merge-ready", action="store_true",
                        help="Babysit only: stop at a verified merge-queue wait, without merging.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the wrapper records.")
    args, upstream = parser.parse_known_args(argv)
    if upstream[:1] == ["--"]:
        upstream = upstream[1:]
    if not 1024 <= args.output_limit <= 64 * 1024 * 1024:
        parser.error("output limit must be between 1024 bytes and 64 MiB")
    if args.until_merge_ready and "--queued-stack" not in upstream:
        parser.error("--until-merge-ready requires --queued-stack")
    # A source polling timeout also bounds setup; zero never disables the outer bound.
    for index, arg in enumerate(upstream):
        timeout = arg.partition("=")[2] if arg.startswith("--timeout=") else (
            upstream[index + 1] if arg == "--timeout" and index + 1 < len(upstream) else None)
        if timeout is not None:
            try:
                seconds = float(timeout)
                if seconds > 0:
                    args.attempt_timeout = min(args.attempt_timeout, seconds)
            except ValueError:
                pass  # The unchanged source CLI produces the usage verdict.
    budget = Budget(args.attempt_timeout, args.output_limit)
    saved_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        saved_handlers[sig] = signal.signal(sig, lambda *_: setattr(budget, "interrupted", True))
    try:
        root = Path(__file__).resolve().parents[3]
        source = root / "skills/poteto-mode/scripts"
        cache_base = args.cache_dir.resolve()
        if cache_base == root or cache_base.is_relative_to(root):
            raise Incomplete("INVALID_CONFIGURATION", "watcher cache must be outside the plugin", 64)
        bun = shutil.which("bun")
        if bun is None:
            raise Incomplete("DEPENDENCY_UNAVAILABLE", "Bun is required for the pstack watcher", 69)
        env = dict(os.environ)
        cache = prepare(source, cache_base, bun, env, budget)
        env["PSTACK_WATCH_REMAINING_MS"] = str(budget.remaining() * 1000)
        env["PSTACK_WATCH_OUTPUT_LIMIT"] = str(max(1, budget.limit - budget.bytes))
        env["PSTACK_WATCH_UNTIL_READY"] = "1" if args.until_merge_ready else "0"
        pending = bytearray()

        def progress(chunk: bytes) -> None:
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, tail = pending.partition(b"\n")
                pending[:] = tail
                record = json.loads(line)
                if not isinstance(record, dict) or record.get("wrapperSchemaVersion") != 1:
                    raise Incomplete("INVALID_OUTPUT", "watcher emitted an unbound record", 70)
                if record.get("outcome") == "PROGRESS":
                    print(json.dumps(record, indent=2 if args.pretty else None), flush=True)

        code, output, stderr = run([bun, str(cache / "watch-pr/codex-main.ts"), *upstream],
                                   Path.cwd(), env, budget, on_stdout=progress)
        # The runner emits only wrapper records, keeping upstream verdicts nested and unchanged.
        final = []
        for line in output.splitlines():
            record = json.loads(line)
            if not isinstance(record, dict) or record.get("wrapperSchemaVersion") != 1:
                raise Incomplete("INVALID_OUTPUT", "watcher emitted an unbound record", 70)
            if record.get("outcome") == "PROGRESS":
                continue
            final.append(record)
        if stderr:
            sys.stderr.write(stderr.decode("utf-8", errors="replace"))
        if len(final) != 1:
            raise Incomplete("EXECUTION_ERROR", "watcher exited without one final result", code or 70)
        record = final[0]
        if record.get("outcome") == "UPSTREAM" and not isinstance(record.get("upstream"), dict):
            raise Incomplete("INVALID_OUTPUT", "watcher upstream verdict must be an object", 70)
        expected_code = record.get("exitCode", 0) if record.get("outcome") != "UPSTREAM" else (
            record.get("upstream", {}).get("exitCode"))
        if code != expected_code:
            raise Incomplete("CLEANUP_FAILED", "watcher result and supervised exit disagree", 70)
        print(json.dumps(record, indent=2 if args.pretty else None))
        return code
    except Incomplete as failure:
        print(json.dumps({"wrapperSchemaVersion": 1, "outcome": failure.outcome,
                          "complete": False, "detail": str(failure), "exitCode": failure.code}))
        return failure.code
    except (OSError, ValueError) as error:
        print(json.dumps({"wrapperSchemaVersion": 1, "outcome": "EXECUTION_ERROR",
                          "complete": False, "detail": str(error), "exitCode": 70}))
        return 70
    finally:
        for sig, handler in saved_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
