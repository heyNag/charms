"""Run one command under a dedicated Linux subreaper, without SDK activation.

Usage: python process_supervisor.py -- COMMAND [ARG ...]
The command inherits stdin/stdout/stderr/environment and gets its own session.
This process continuously reaps adopted descendants and fences remaining work
before returning the command's status. Callers own wall-clock/output budgets.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

TERM_GRACE = 0.15
CLEANUP_LIMIT = 2.0


def _children() -> list[int]:
    parent = os.getpid()
    try:
        return [int(value) for value in Path(
            f"/proc/self/task/{parent}/children"
        ).read_text().split()]
    except FileNotFoundError:
        # Some container kernels omit CONFIG_CHECKPOINT_RESTORE's children file.
        # Read only PID/parent metadata, never another process's environment.
        children = []
        with os.scandir("/proc") as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                try:
                    fields = Path(entry.path, "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[1]) == parent:
                        children.append(int(entry.name))
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
        return children


def _signal(pid: int, number: int, *, group: bool = False) -> None:
    try:
        if group:
            os.killpg(pid, number)
        else:
            os.kill(pid, number)
    except ProcessLookupError:
        pass


def supervise(command: list[str]) -> int:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("owned descendant reaping requires Linux")
    if not command:
        raise ValueError("a command is required")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot enable the private child subreaper")
    received = []

    def stop(number, _frame):
        if not received:
            received.append(number)

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, stop)
    child = subprocess.Popen(command, start_new_session=True)
    terminal = None
    stopping = None
    try:
        while True:
            # Leave the root zombie unreaped while using its process-group ID.
            # This prevents its ID being recycled into an unrelated group.
            if terminal is None:
                terminal = os.waitid(os.P_PID, child.pid,
                                     os.WEXITED | os.WNOWAIT | os.WNOHANG)
            now = time.monotonic()
            if stopping is None and (terminal is not None or received):
                stopping = now
            children = _children()
            if stopping is not None:
                number = signal.SIGKILL if now - stopping >= TERM_GRACE else (
                    received[0] if received else signal.SIGTERM
                )
                _signal(child.pid, number, group=True)
                # Orphans which created their own session are still our adopted
                # children. Their unreaped parent-owned PID cannot be reused.
                for pid in children:
                    if pid != child.pid:
                        _signal(pid, number)
            for pid in children:
                if pid != child.pid:
                    os.waitpid(pid, os.WNOHANG)
            if terminal is not None and _children() == [child.pid]:
                _, status = os.waitpid(child.pid, 0)
                child.returncode = os.waitstatus_to_exitcode(status)
                if received:
                    return 128 + received[0]
                return child.returncode if child.returncode >= 0 else 128 - child.returncode
            if stopping is not None and now - stopping >= CLEANUP_LIMIT:
                # Do not certify a stuck/uninterruptible descendant as cleaned.
                raise RuntimeError("owned descendants did not finish cleanup")
            time.sleep(0.005)
    finally:
        if child.returncode is None:
            _signal(child.pid, signal.SIGKILL, group=True)
            for pid in _children():
                _signal(pid, signal.SIGKILL)
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == child.pid:
                    child.returncode = os.waitstatus_to_exitcode(status)
                if pid == 0:
                    time.sleep(0.005)


def main(argv: list[str] | None = None) -> int:
    command = list(sys.argv[1:] if argv is None else argv)
    if command[:1] == ["--"]:
        command.pop(0)
    try:
        return supervise(command)
    except (OSError, ValueError, RuntimeError):
        # Never print the command, its environment or its input.
        print("pstack process supervision failed; cleanup is unverified", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
