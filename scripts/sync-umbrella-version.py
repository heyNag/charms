#!/usr/bin/env python3
"""Sync workspace/umbrella manifest versions to the latest package release date.

The umbrella manifests (package.json, pyproject.toml, and the root Claude/Codex/
Cursor plugin wrappers) carry a single workspace-level version. Per-package
releases are versioned independently by the `Release Skill` workflow, so this
helper keeps the umbrella value aligned with the most recent release.

The target is the maximum UTC date-based (CalVer) version found across all
package plugin manifests AND the current umbrella values. Including the current
umbrella values makes the update monotonic: it never moves a version backward,
so a deliberately set head-start (for example, set ahead of the day's releases)
is preserved until a later release surpasses it. Non-CalVer versions such as the
`0.1.0` bootstrap are ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_metadata import load_json

VERSION_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.\d+)?$")
TOML_VERSION_RE = re.compile(r'^version = "[^"]*"$', re.MULTILINE)

# Workspace-level manifests that carry a single umbrella version.
JSON_MANIFESTS = [
    "package.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
]
TOML_MANIFESTS = ["pyproject.toml"]


def parse_calver_date(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = VERSION_DATE_RE.match(value)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def read_toml_version(path: Path) -> str | None:
    match = TOML_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return match.group(0).split('"')[1] if match else None


def umbrella_versions(root: Path) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for rel in JSON_MANIFESTS:
        value = load_json(root / rel).get("version")
        versions[rel] = value if isinstance(value, str) else None
    for rel in TOML_MANIFESTS:
        versions[rel] = read_toml_version(root / rel)
    return versions


def target_version(root: Path) -> str | None:
    dates: list[tuple[int, int, int]] = []
    for plugin_path in sorted((root / "packages").glob("*/.claude-plugin/plugin.json")):
        date = parse_calver_date(load_json(plugin_path).get("version"))
        if date:
            dates.append(date)
    for value in umbrella_versions(root).values():
        date = parse_calver_date(value)
        if date:
            dates.append(date)
    if not dates:
        return None
    year, month, day = max(dates)
    return f"{year}.{month}.{day}"


def write_json_version(path: Path, version: str) -> bool:
    data = load_json(path)
    if data.get("version") == version:
        return False
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def write_toml_version(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = TOML_VERSION_RE.sub(f'version = "{version}"', text, count=1)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def sync(root: Path) -> tuple[str | None, list[str]]:
    target = target_version(root)
    if target is None:
        return None, []
    changed: list[str] = []
    for rel in JSON_MANIFESTS:
        if write_json_version(root / rel, target):
            changed.append(rel)
    for rel in TOML_MANIFESTS:
        if write_toml_version(root / rel, target):
            changed.append(rel)
    return target, changed


def check(root: Path) -> tuple[str | None, dict[str, str | None]]:
    target = target_version(root)
    if target is None:
        return None, {}
    drifted = {rel: value for rel, value in umbrella_versions(root).items() if value != target}
    return target, drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync umbrella manifest versions.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift without writing; exit 1 if any umbrella version is out of sync.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.check:
        target, drifted = check(root)
        if target is None:
            print("sync-umbrella-version: no dated package releases yet; nothing to check")
            return 0
        if drifted:
            for rel, value in sorted(drifted.items()):
                print(f"error: {rel}: version {value!r} != latest release {target!r}", file=sys.stderr)
            return 1
        print(f"umbrella versions in sync at {target}")
        return 0

    target, changed = sync(root)
    if target is None:
        print("sync-umbrella-version: no dated package releases yet; leaving umbrella versions unchanged")
        return 0
    if changed:
        print(f"synced umbrella versions to {target}: " + ", ".join(changed))
    else:
        print(f"umbrella versions already at {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
