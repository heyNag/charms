"""List and remove old watch-video run folders.

A run folder keeps downloaded media, audio, frames and transcripts, and nothing
removes it once the run is over. This module finds the folders under a run root
that have not changed for a given time and, when asked, deletes them.

It only ever touches a folder it recognises as a run: a real directory directly
inside the run root, named the way watch.py names runs, that either carries the
run's own record for the source in its name or holds nothing except files a run
creates. Anything else, and every symbolic link, is left alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from datetime import datetime
from pathlib import Path


# watch.py's safe_run_id: <date>-<time>-<slug>-<first 8 hex digits of the
# source's SHA-1>, plus -NN when that name was already taken.
RUN_NAME = re.compile(r"^(\d{8}-\d{6})-[A-Za-z0-9._-]+-([0-9a-f]{8})(?:-\d{2})?$")
# What a run creates at the top of its folder. A folder whose record is
# missing counts as an unfinished run only when it holds nothing else.
RUN_FILES = frozenset({
    "analysis.json", "audio.mp3", "audio.wav", "batch.json", "evidence.json",
    "groq_transcript.raw.json", "local_analysis.json", "local_analysis.md",
    "local_analysis.tmp", "local_transcript.raw.json", "metadata.json",
    "native_captions.json", "openai_transcript.raw.json", "report.md",
    "supporting_transcripts.json", "transcript.json", "transcript.md",
})
RUN_FOLDERS = frozenset({"audio_chunks", "frames", "local_analysis", "media", "videos"})
RECORD_FILES = ("metadata.json", "batch.json")
MAX_RECORD_BYTES = 16 * 1024 * 1024
DEFAULT_AGE = "7d"
# A run that changed within the last hour may still be going.
MIN_AGE_SECONDS = 3600
AGE_UNITS = {"h": 3600, "d": 24 * 3600, "w": 7 * 24 * 3600}


def parse_age(value: str) -> int:
    """Seconds for an age such as 12h, 7d or 2w."""
    match = re.fullmatch(r"(\d+)([hdw])", str(value).strip().lower())
    if not match:
        raise ValueError("--older-than takes a whole number and a unit: 12h, 7d or 2w")
    seconds = int(match.group(1)) * AGE_UNITS[match.group(2)]
    if seconds < MIN_AGE_SECONDS:
        raise ValueError(
            "--older-than must be at least 1h: a run that changed in the last hour "
            "may still be going"
        )
    return seconds


def _started(name: str) -> float | None:
    """When the run began, read from the timestamp that starts its name."""
    match = RUN_NAME.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _record_digest(path: Path) -> str | None:
    """The name digest of the source recorded in metadata.json or batch.json."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        source = data.get("source") if isinstance(data, dict) else None
        if not isinstance(source, str):
            return None
        # The same digest watch.py's safe_run_id puts in the folder name.
        return hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    except (OSError, ValueError):
        return None


def run_kind(folder: Path) -> str | None:
    """Say what kind of run a folder is, or None when it is not recognisably one.

    "recorded": the folder's record names a source whose digest is the one in
    the folder name, so watch.py created this folder for that source.
    "unfinished": no such record, and nothing inside but run artifacts, as a
    run leaves behind when it fails or is stopped early.
    """
    match = RUN_NAME.match(folder.name)
    if not match or _started(folder.name) is None:
        return None
    try:
        if not stat.S_ISDIR(folder.lstat().st_mode):
            return None
        entries = list(os.scandir(folder))
    except OSError:
        return None
    for record in RECORD_FILES:
        if _record_digest(folder / record) == match.group(2):
            return "recorded"
    for entry in entries:
        try:
            if entry.is_symlink():
                return None
            known = RUN_FOLDERS if entry.is_dir(follow_symlinks=False) else RUN_FILES
        except OSError:
            return None
        if entry.name not in known:
            return None
    return "unfinished"


def _measure(folder: Path) -> tuple[int, float]:
    """Total size of the files in a folder, and the time of the latest change."""
    total = 0
    try:
        latest = folder.lstat().st_mtime
    except OSError:
        latest = 0.0
    for current, folders, files in os.walk(folder, followlinks=False):
        for name in (*folders, *files):
            try:
                info = os.lstat(os.path.join(current, name))
            except OSError:
                continue
            latest = max(latest, info.st_mtime)
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total, latest


def find_runs(root: Path, older_than: int, *, now: float | None = None) -> dict[str, object]:
    """Sort what is inside a run root into old runs, newer runs and everything else.

    A run's age counts from its latest change: the newest modification time
    anywhere inside it, or its start time when that is later.
    """
    current_time = time.time() if now is None else now
    root = Path(root).expanduser()
    result: dict[str, object] = {
        "root": str(root), "older_than_seconds": older_than, "runs": [],
        "kept_newer": 0, "not_runs": 0, "error": None,
    }
    if not root.is_dir():
        return result
    try:
        children = sorted(root.iterdir(), key=lambda child: child.name)
    except OSError as exc:
        result["error"] = f"could not read {root}: {exc.strerror or exc}"
        return result
    runs: list[dict[str, object]] = []
    for child in children:
        kind = run_kind(child)
        if kind is None:
            result["not_runs"] += 1
            continue
        size, latest = _measure(child)
        age = current_time - max(latest, _started(child.name) or 0.0)
        if age < older_than:
            result["kept_newer"] += 1
            continue
        runs.append({
            "name": child.name, "path": str(child), "kind": kind,
            "size_bytes": size, "age_seconds": int(age), "removed": False, "error": None,
        })
    result["runs"] = runs
    return result


def prune(
    root: Path, older_than: int, *, delete: bool = False, now: float | None = None,
) -> dict[str, object]:
    """List the old runs under a run root, and delete them when asked to."""
    result = find_runs(root, older_than, now=now)
    result["delete"] = delete
    if delete:
        for run in result["runs"]:
            folder = Path(str(run["path"]))
            # Look again just before deleting: the folder may have changed.
            if run_kind(folder) is None:
                run["error"] = "no longer looks like a run folder"
                continue
            try:
                shutil.rmtree(folder)
                run["removed"] = True
            except OSError as exc:
                run["error"] = exc.strerror or str(exc)
    result["ok"] = result["error"] is None and not any(run["error"] for run in result["runs"])
    return result


def size_text(size: int) -> str:
    megabytes = size / (1024 * 1024)
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB"
    return f"{megabytes:.1f} MB" if megabytes < 10 else f"{megabytes:.0f} MB"


def age_text(seconds: float) -> str:
    hours = int(seconds // 3600)
    if hours < 48:
        return f"{hours} hour{'' if hours == 1 else 's'}"
    return f"{hours // 24} days"


def report(result: dict[str, object]) -> str:
    """The text a person or agent reads after doctor.py --prune."""
    runs = list(result["runs"])
    limit = age_text(float(result["older_than_seconds"]))
    lines = ["Watch Video Doctor: prune", "", f"Run folders under {result['root']} unchanged for {limit}:", ""]
    if result["error"]:
        lines.append(f"- error: {result['error']}")
    elif not runs:
        lines.append("- none")
    for run in runs:
        prefix = "removed " if run["removed"] else "could not remove " if run["error"] else ""
        detail = f"{size_text(int(run['size_bytes']))}, unchanged for {age_text(float(run['age_seconds']))}"
        if run["kind"] == "unfinished":
            detail += ", unfinished run"
        if run["error"]:
            detail += f", {run['error']}"
        lines.append(f"- {prefix}{run['name']}: {detail}")
    lines.append("")
    total = sum(int(run["size_bytes"]) for run in runs)
    if runs and not result["delete"]:
        lines.append(
            f"{len(runs)} run folder(s), {size_text(total)}. Nothing was deleted. "
            "Run the command again with --delete to remove them."
        )
    elif runs:
        removed = [run for run in runs if run["removed"]]
        freed = sum(int(run["size_bytes"]) for run in removed)
        line = f"Removed {len(removed)} run folder(s), {size_text(freed)}."
        if len(removed) < len(runs):
            line += f" {len(runs) - len(removed)} could not be removed."
        lines.append(line)
    left = []
    if result["kept_newer"]:
        left.append(f"{result['kept_newer']} newer run folder(s)")
    if result["not_runs"]:
        left.append(f"{result['not_runs']} item(s) that are not watch-video runs")
    if left:
        lines.append("Left alone: " + " and ".join(left) + ".")
    return "\n".join(lines).rstrip() + "\n"
