#!/usr/bin/env python3
"""Read or advance the UTC CalVer version of one Agent Plugin manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import stat
import sys


PLUGIN_NAME_RE = re.compile(
    r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$"
)
CALVER_RE = re.compile(
    r"^(?P<year>[0-9]{4})\."
    r"(?P<month>[1-9]|1[0-2])\."
    r"(?P<day>[1-9]|[12][0-9]|3[01])"
    r"(?:\.(?P<sequence>[1-9][0-9]*))?$"
)
VERSION_MODES = ("current", "date")


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def parse_version(value: str) -> tuple[dt.date, int | None]:
    match = CALVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"version is not UTC CalVer YYYY.M.D[.N]: {value!r}")
    try:
        version_date = dt.date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError as exc:
        raise ValueError(f"version contains an invalid calendar date: {value!r}") from exc
    sequence = match.group("sequence")
    return version_date, int(sequence) if sequence is not None else None


def base_version(release_date: dt.date) -> str:
    return f"{release_date.year:04d}.{release_date.month}.{release_date.day}"


def next_version(current: str, mode: str, release_date: dt.date | None = None) -> str:
    current_date, current_sequence = parse_version(current)
    if mode == "current":
        return current
    if mode != "date":
        raise ValueError(f"unsupported version mode: {mode!r}")

    release_date = release_date or utc_today()
    if release_date < current_date:
        raise ValueError(
            f"release date {release_date.isoformat()} precedes current version date "
            f"{current_date.isoformat()}"
        )
    base = base_version(release_date)
    if release_date == current_date:
        sequence = 1 if current_sequence is None else current_sequence + 1
        return f"{base}.{sequence}"
    return base


def package_plugin_path(root: pathlib.Path, package: str) -> pathlib.Path:
    if PLUGIN_NAME_RE.fullmatch(package) is None:
        raise ValueError(f"invalid plugin name: {package!r}")
    return root / "packages" / package / "plugin.json"


def load_plugin(path: pathlib.Path) -> dict:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing Agent Plugin manifest: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"Agent Plugin manifest must be a regular file, not a symlink: {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Agent Plugin manifest must be a JSON object: {path}")
    return data


def write_plugin(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def running_in_release_workflow(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_WORKFLOW") == "Release Plugin"
        and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    )


def update_package(
    root: pathlib.Path,
    package: str,
    mode: str,
    release_date: dt.date | None,
    dry_run: bool,
) -> str:
    path = package_plugin_path(root, package)
    for directory in (root / "packages", path.parent):
        try:
            directory_mode = directory.lstat().st_mode
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"missing plugin directory: {directory}") from exc
        if stat.S_ISLNK(directory_mode) or not stat.S_ISDIR(directory_mode):
            raise ValueError(f"plugin directory must be a real directory: {directory}")
    data = load_plugin(path)
    manifest_name = data.get("name")
    if manifest_name != package:
        raise ValueError(f"{path} name is {manifest_name!r}, expected {package!r}")

    current = data.get("version")
    if not isinstance(current, str) or not current:
        raise ValueError(f"{path} must contain a non-empty string version")

    version = next_version(current, mode, release_date)
    if mode == "date" and not dry_run:
        data["version"] = version
        write_plugin(path, data)
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="Plugin package name under packages/")
    parser.add_argument(
        "--mode",
        choices=VERSION_MODES,
        default="date",
        help="Version action. 'current' publishes without changing the manifest.",
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        help="Override the UTC release date for tests, in YYYY-MM-DD.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resulting version without changing the manifest.",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    writes_manifest = args.mode == "date" and not args.dry_run
    if writes_manifest and not running_in_release_workflow():
        print(
            "error: plugin versions are changed only by the GitHub Actions "
            "`Release Plugin` workflow. Use --dry-run locally.",
            file=sys.stderr,
        )
        return 1

    try:
        version = update_package(
            args.root.resolve(),
            args.package,
            mode=args.mode,
            release_date=args.date,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
