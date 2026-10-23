#!/usr/bin/env python3
"""Advance the semantic version of one Agent Plugin manifest."""

from __future__ import annotations

import argparse
import json
import pathlib
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from plugin_release import BUMP_PARTS, bump_version, validate_plugin_name  # noqa: E402


def package_plugin_path(root: pathlib.Path, package: str) -> pathlib.Path:
    validate_plugin_name(package)
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


def update_package(root: pathlib.Path, package: str, part: str, dry_run: bool) -> str:
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

    version = bump_version(data.get("version"), part)
    if not dry_run:
        data["version"] = version
        write_plugin(path, data)
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="Plugin package name under packages/")
    parser.add_argument("part", choices=BUMP_PARTS, help="Semantic version part to advance.")
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

    try:
        version = update_package(args.root.resolve(), args.package, args.part, args.dry_run)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
