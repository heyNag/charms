"""Time-limited execution of the external tools watch-video runs.

Every yt-dlp, ffmpeg and ffprobe call has a limit. Without one, a stalled
download, a stream that never ends, or a decoder stuck on a damaged file holds
the run open, and with it the agent that waits for the report.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
from pathlib import Path


STEP_TIMEOUT_ENV = "WATCH_VIDEO_PROCESS_TIMEOUT"
# One download, extraction or encode. Generous enough for a multi-hour video.
DEFAULT_STEP_TIMEOUT = 1800.0
MAX_STEP_TIMEOUT = 24 * 3600.0
# Metadata reads (ffprobe, `ffmpeg -h`, the yt-dlp probe) never need that long.
PROBE_TIMEOUT = 180.0
_REAP_SECONDS = 5.0

_configured: float | None = None


class CommandTimeout(RuntimeError):
    """An external tool passed its time limit and was stopped.

    The message holds the tool name and the limit only, never its arguments
    or output, so it is safe to store in a report.
    """

    def __init__(self, tool: str, seconds: float) -> None:
        super().__init__(f"{tool} did not finish within {seconds:g} seconds and was stopped")
        self.tool = tool
        self.seconds = seconds


def parse_timeout(value: object, label: str) -> float:
    """Validate a per-step limit in seconds."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = math.nan
    if isinstance(value, bool) or not math.isfinite(seconds) or not 0 < seconds <= MAX_STEP_TIMEOUT:
        raise ValueError(f"{label} must be a number of seconds between 0 and {MAX_STEP_TIMEOUT:g}")
    return seconds


def configure(step_timeout: float | None) -> None:
    """Set the per-step limit for this process; None returns to the default."""
    global _configured
    _configured = None if step_timeout is None else parse_timeout(step_timeout, "process timeout")


def step_timeout() -> float:
    """Limit for one download, extraction or encode."""
    if _configured is not None:
        return _configured
    raw = (os.environ.get(STEP_TIMEOUT_ENV) or "").strip()
    return parse_timeout(raw, STEP_TIMEOUT_ENV) if raw else DEFAULT_STEP_TIMEOUT


def probe_timeout() -> float:
    """Limit for a metadata read; never longer than the step limit."""
    return min(PROBE_TIMEOUT, step_timeout())


def _tool_name(cmd: list[str]) -> str:
    return Path(str(cmd[0])).name if cmd else "command"


def run(cmd: list[str], *, timeout: float | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Run one tool that starts no helpers of its own (ffmpeg, ffprobe, git).

    Takes subprocess.run's keyword arguments. Raises CommandTimeout once the
    limit passes; subprocess.run has stopped and reaped the tool by then.
    """
    limit = step_timeout() if timeout is None else timeout
    try:
        return subprocess.run(cmd, check=False, timeout=limit, **kwargs)
    except subprocess.TimeoutExpired:
        raise CommandTimeout(_tool_name(cmd), limit) from None


def _descendants(pid: int) -> list[int]:
    """List the live processes started, directly or not, by pid."""
    try:
        # One -o per column is the portable form: after "name=", BSD ps reads
        # the rest of the argument, commas included, as the column heading.
        listing = subprocess.run(
            ["ps", "-A", "-o", "pid=", "-o", "ppid="],
            capture_output=True, text=True, check=False, timeout=_REAP_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in listing.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found: list[int] = []
    pending = [pid]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child)
    return found


def _signal(pid: int, number: int) -> None:
    try:
        os.kill(pid, number)
    except OSError:
        pass


def _stop_tree(process: subprocess.Popen) -> None:
    """Stop a tool together with the helpers it started.

    yt-dlp runs ffmpeg to merge formats and to download a section. Stopping
    yt-dlp alone would leave that ffmpeg writing to disk with nobody waiting.
    The tool is frozen first, so it cannot start another helper while the
    process table is read. It stays in the caller's process group throughout,
    so a host that stops the whole group still reaches every process.
    """
    _signal(process.pid, signal.SIGSTOP)
    for pid in reversed(_descendants(process.pid)):
        _signal(pid, signal.SIGKILL)
    process.kill()


def run_tree(cmd: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a tool that may start helpers (yt-dlp) and capture its UTF-8 output.

    Raises CommandTimeout once the limit passes, after stopping the tool and
    everything it started.
    """
    limit = step_timeout() if timeout is None else timeout
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        # Explicit UTF-8 keeps yt-dlp/ffmpeg output deterministic across locales.
        text=True, encoding="utf-8", errors="replace",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            _stop_tree(process)
            try:
                process.communicate(timeout=_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                # A helper that survived still holds the pipes; stop reading.
                pass
            raise CommandTimeout(_tool_name(cmd), limit) from None
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
