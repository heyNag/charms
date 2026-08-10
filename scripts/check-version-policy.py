#!/usr/bin/env python3
"""Reject Agent Plugin version changes outside the Release Plugin workflow."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


ZERO_SHA = "0" * 40
POLICY_PATH = "scripts/check-version-policy.py"
RELEASE_ACTOR = "github-actions[bot]"
DATE_VERSION_INITIALIZATION_BASE = "e2294e31377269b9a50f3779a8754d83643e6786"
DATE_VERSION_INITIALIZATION = {
    f"packages/{package}/plugin.json": ("1.0.0", "2026.8.10")
    for package in (
        "chatgpt-pro-review",
        "codex-reset-credit",
        "mnemosyne-memory",
        "watch-video",
        "x-bookmarks",
    )
}


def run_git(root: pathlib.Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def rev_exists(root: pathlib.Path, rev: str) -> bool:
    if not rev or rev == ZERO_SHA:
        return False
    return run_git(root, ["cat-file", "-e", f"{rev}^{{commit}}"], check=False).returncode == 0


def changed_files(root: pathlib.Path, base: str, head: str) -> list[str]:
    if not rev_exists(root, base):
        return []
    if not rev_exists(root, head):
        raise ValueError(f"head revision is not available: {head}")
    result = run_git(root, ["diff", "--name-only", base, head, "--", "packages"])
    return [line for line in result.stdout.splitlines() if line]


def json_at(root: pathlib.Path, rev: str, path: str) -> dict | None:
    result = run_git(root, ["show", f"{rev}:{path}"], check=False)
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError(f"{path} at {rev} is not a JSON object")
    return data


def path_exists_at(root: pathlib.Path, rev: str, path: str) -> bool:
    return run_git(root, ["cat-file", "-e", f"{rev}:{path}"], check=False).returncode == 0


def is_package_manifest(path: str) -> bool:
    parts = pathlib.PurePosixPath(path).parts
    return len(parts) == 3 and parts[0] == "packages" and parts[2] == "plugin.json"


def plugin_version_change_records(
    root: pathlib.Path,
    base: str,
    head: str,
) -> list[tuple[str, object, object]]:
    changes: list[tuple[str, object, object]] = []
    for path in changed_files(root, base, head):
        if not is_package_manifest(path):
            continue
        before = json_at(root, base, path)
        after = json_at(root, head, path)
        if before is None or after is None:
            continue
        if before.get("version") != after.get("version"):
            changes.append((path, before.get("version"), after.get("version")))
    return changes


def plugin_version_changes(root: pathlib.Path, base: str, head: str) -> list[str]:
    return [
        f"{path}: {before} -> {after}"
        for path, before, after in plugin_version_change_records(root, base, head)
    ]


def is_date_version_initialization(
    base: str,
    records: list[tuple[str, object, object]],
) -> bool:
    actual = {path: (before, after) for path, before, after in records}
    return base == DATE_VERSION_INITIALIZATION_BASE and actual == DATE_VERSION_INITIALIZATION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base commit SHA")
    parser.add_argument("--head", required=True, help="Head commit SHA")
    parser.add_argument("--actor", required=True, help="GitHub actor for the change")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if rev_exists(root, args.base) and not path_exists_at(root, args.base, POLICY_PATH):
        print("version policy skipped: policy was not present at the base revision")
        return 0

    records = plugin_version_change_records(root, args.base, args.head)
    if not records:
        print("version policy passed")
        return 0

    if args.actor == RELEASE_ACTOR:
        print("version policy passed: release bot changed package versions")
        return 0

    if is_date_version_initialization(args.base, records):
        print("version policy passed: initialized UTC date versions")
        return 0

    print(
        "error: Agent Plugin versions may only change through the GitHub Actions "
        "Release Plugin workflow",
        file=sys.stderr,
    )
    for path, before, after in records:
        print(f"error: {path}: {before} -> {after}", file=sys.stderr)
    print(
        "fix: revert the version edits and run the manual Release Plugin workflow "
        "from GitHub Actions",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
