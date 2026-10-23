#!/usr/bin/env python3
"""Check that a plugin's manifest version is ready to release and print the plan.

The plan is printed as `key=value` lines for GitHub Actions outputs. A release is
refused when its tag already exists or when its version is not greater than every
version already released for that plugin.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from plugin_release import (  # noqa: E402
    manifest_at,
    parse_version,
    release_tag,
    released_versions,
    tag_commit,
    validate_plugin_name,
)


def plan_release(root: pathlib.Path, plugin: str, revision: str = "HEAD") -> dict[str, str]:
    validate_plugin_name(plugin)
    manifest = manifest_at(root, revision, plugin)
    if manifest.get("name") != plugin:
        raise ValueError(f"packages/{plugin}/plugin.json name is {manifest.get('name')!r}")
    version = manifest.get("version")
    parse_version(version)

    tag = release_tag(plugin, version)
    if tag_commit(root, tag) is not None:
        raise ValueError(
            f"{tag} already exists; bump the version with scripts/bump-plugin-version.py first"
        )
    previous = released_versions(root, plugin)
    if previous and parse_version(version) <= parse_version(previous[-1]):
        raise ValueError(
            f"version {version} must be greater than the latest release {previous[-1]}"
        )
    return {
        "version": version,
        "tag": tag,
        "previous_tag": release_tag(plugin, previous[-1]) if previous else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", help="Plugin package name under packages/")
    parser.add_argument("--revision", default="HEAD", help="Commit to release. Defaults to HEAD.")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    try:
        plan = plan_release(args.root.resolve(), args.plugin, args.revision)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for key, value in plan.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
