#!/usr/bin/env python3
"""Check that a plugin's manifest version is ready to release and print the plan.

The plan is printed as `key=value` lines for GitHub Actions outputs. A release is
refused when its tag already exists, and when its version is not the
YEAR.MONTH.RELEASE that follows the plugin's latest release: greater than it,
naming no month after the current one in UTC, and counting the releases already
made in its month.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from plugin_release import (  # noqa: E402
    BUMP_HELPER,
    check_next_version,
    manifest_at,
    known_releases,
    parse_version,
    release_tag,
    released_versions,
    tag_commit,
    utc_today,
    validate_plugin_name,
)


def plan_release(
    root: pathlib.Path,
    plugin: str,
    revision: str = "HEAD",
    today: datetime.date | None = None,
) -> dict[str, str]:
    validate_plugin_name(plugin)
    manifest = manifest_at(root, revision, plugin)
    if manifest.get("name") != plugin:
        raise ValueError(f"release manifest for {plugin} names {manifest.get('name')!r}")
    version = manifest.get("version")
    parse_version(version)
    if plugin == "pstack":
        from pstack_release import bundle_at, check_native_transition, read_published
        from plugin_release import run_git

        commit = run_git(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"]).stdout.strip()
        check_native_transition(read_published(root), bundle_at(root, commit))

    tag = release_tag(plugin, version)
    if tag_commit(root, tag) is not None:
        raise ValueError(f"{tag} already exists; bump the version with {BUMP_HELPER} first")
    previous = known_releases(root, plugin) if plugin == "pstack" else released_versions(root, plugin)
    try:
        check_next_version(version, previous, today or utc_today())
    except ValueError as exc:
        raise ValueError(f"{exc}; set the version with {BUMP_HELPER} first") from exc
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
