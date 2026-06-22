#!/usr/bin/env python3
"""Bump a package plugin version to the next UTC CalVer release string."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys


VERSION_RE = re.compile(
    r"^(?P<year>\d{4})\.(?P<month>[1-9]|1[0-2])\.(?P<day>[1-9]|[12]\d|3[01])"
    r"(?:\.(?P<sequence>[1-9]\d*))?$"
)
PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_date(value: str | None) -> dt.date:
    if value is None:
        return utc_today()
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def base_version(release_date: dt.date) -> str:
    return f"{release_date.year}.{release_date.month}.{release_date.day}"


def next_version(current: str, release_date: dt.date) -> str:
    base = base_version(release_date)
    if current == base:
        return f"{base}.1"

    match = VERSION_RE.match(current)
    if match:
        current_base = ".".join(
            [match.group("year"), str(int(match.group("month"))), str(int(match.group("day")))]
        )
        if current_base == base and match.group("sequence"):
            return f"{base}.{int(match.group('sequence')) + 1}"

    return base


def package_plugin_path(root: pathlib.Path, package: str) -> pathlib.Path:
    if not PACKAGE_RE.match(package):
        raise ValueError(f"invalid package name: {package!r}")
    return root / "packages" / package / ".claude-plugin" / "plugin.json"


def load_plugin(path: pathlib.Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"missing plugin metadata: {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"plugin metadata must be a JSON object: {path}")
    return data


def write_plugin(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def running_in_release_workflow(env: dict[str, str] | None = None) -> bool:
    env = env or os.environ
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_WORKFLOW") == "Release Skill"
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    )


def bump_package(root: pathlib.Path, package: str, release_date: dt.date, dry_run: bool) -> str:
    path = package_plugin_path(root, package)
    data = load_plugin(path)
    manifest_name = data.get("name")
    if manifest_name != package:
        raise ValueError(f"{path} name is {manifest_name!r}, expected {package!r}")

    current = data.get("version")
    if not isinstance(current, str) or not current:
        raise ValueError(f"{path} must contain a non-empty string version")

    new_version = next_version(current, release_date)
    if not dry_run:
        data["version"] = new_version
        write_plugin(path, data)
    return new_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bump packages/<name>/.claude-plugin/plugin.json to the next UTC date-based "
            "version. Same-day releases use .1, .2, and so on."
        )
    )
    parser.add_argument("package", help="Package name under packages/")
    parser.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Override release date for testing, in YYYY-MM-DD. Defaults to UTC today.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the next version without writing")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not running_in_release_workflow():
        print(
            "error: package versions are bumped only by the GitHub Actions "
            "`Release Skill` workflow. Use --dry-run locally.",
            file=sys.stderr,
        )
        return 1

    release_date = args.date or utc_today()
    try:
        new_version = bump_package(args.root.resolve(), args.package, release_date, args.dry_run)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
