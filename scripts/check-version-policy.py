#!/usr/bin/env python3
"""Reject package version bumps outside the Release Skill workflow."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


ZERO_SHA = "0" * 40
PLUGIN_SUFFIX = "/.claude-plugin/plugin.json"
POLICY_PATH = "scripts/check-version-policy.py"
RELEASE_ACTOR = "github-actions[bot]"


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


def plugin_version_changes(root: pathlib.Path, base: str, head: str) -> list[str]:
    changes: list[str] = []
    for path in changed_files(root, base, head):
        if not path.startswith("packages/") or not path.endswith(PLUGIN_SUFFIX):
            continue
        before = json_at(root, base, path)
        after = json_at(root, head, path)
        if before is None or after is None:
            continue
        if before.get("version") != after.get("version"):
            changes.append(f"{path}: {before.get('version')} -> {after.get('version')}")
    return changes


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

    changes = plugin_version_changes(root, args.base, args.head)
    if not changes:
        print("version policy passed")
        return 0

    if args.actor == RELEASE_ACTOR:
        print("version policy passed: release bot changed package versions")
        return 0

    print("error: package plugin versions may only change through the GitHub Actions Release Skill workflow", file=sys.stderr)
    for change in changes:
        print(f"error: {change}", file=sys.stderr)
    print("fix: revert the version edits and run the manual Release Skill workflow from GitHub Actions", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
