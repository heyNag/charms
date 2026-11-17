"""Shared Charms rules for plugin versions, release tags, and the marketplace."""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess
from collections.abc import Iterable


PLUGIN_NAME_RE = re.compile(
    r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$"
)
# Three plain numbers. Claude Code reads a release tag's version as SemVer and
# ignores a tag it cannot read that way, so a fourth number has no place. The
# 1.x releases made before the move to CalVer have this shape too, and their
# tags and marketplace entries still have to be read.
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
# YEAR.MONTH.RELEASE in UTC, the form of every version set since that move.
CALVER_RE = re.compile(r"^[1-9][0-9]{3}\.(?:[1-9]|1[0-2])\.(?:0|[1-9][0-9]*)$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BUMP_HELPER = "scripts/bump-plugin-version.py"

MARKETPLACE_PATH = pathlib.PurePosixPath(".claude-plugin/marketplace.json")
MARKETPLACE_NAME = "charms"
MARKETPLACE_KEYS = {"name", "owner", "metadata", "plugins"}
REPOSITORY_URL = "https://github.com/heyNag/charms.git"


def catalog_metadata_errors(data: object) -> list[str]:
    """Apply the same named marketplace contract to both host catalogs."""
    if not isinstance(data, dict):
        return ["marketplace manifest must be a JSON object"]
    errors = []
    if set(data) != MARKETPLACE_KEYS:
        errors.append(f"top-level keys must be exactly {sorted(MARKETPLACE_KEYS)}")
    if data.get("name") != MARKETPLACE_NAME:
        errors.append(f"name must be {MARKETPLACE_NAME!r}")
    owner = data.get("owner")
    if (not isinstance(owner, dict) or set(owner) != {"name"}
            or not isinstance(owner.get("name"), str) or not owner["name"].strip()):
        errors.append("owner must contain only a non-empty name")
    metadata = data.get("metadata")
    if (not isinstance(metadata, dict) or set(metadata) != {"description"}
            or not isinstance(metadata.get("description"), str) or not metadata["description"].strip()):
        errors.append("metadata must contain only a non-empty description")
    return errors


def validate_plugin_name(plugin: str) -> None:
    if PLUGIN_NAME_RE.fullmatch(plugin) is None:
        raise ValueError(f"invalid plugin name: {plugin!r}")


def parse_version(value: object) -> tuple[int, int, int]:
    """Read a version for comparison: CalVer, or a 1.x release made before it."""

    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"version is not three plain numbers such as 2026.11.0: {value!r}")
    first, second, third = (int(part) for part in match.groups())
    return first, second, third


def parse_calver(value: object) -> tuple[int, int, int]:
    """Read a YEAR.MONTH.RELEASE version as (year, month, release)."""

    if not isinstance(value, str) or CALVER_RE.fullmatch(value) is None:
        raise ValueError(f"version is not YEAR.MONTH.RELEASE, such as 2026.11.0: {value!r}")
    return parse_version(value)


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def next_version(released: Iterable[str], today: datetime.date) -> str:
    """Return the version of a plugin's next release, given the ones it has made.

    The version is the year and month of `today`, then the number of releases
    the plugin has already made in that month.
    """

    latest = max(released, key=parse_version, default=None)
    count = 0
    if latest is not None:
        first, second, third = parse_version(latest)
        if (first, second) > (today.year, today.month):
            raise ValueError(
                f"the latest release {latest} names a month after {today.year}.{today.month}, "
                "the current month in UTC"
            )
        if (first, second) == (today.year, today.month):
            count = third + 1
    return f"{today.year}.{today.month}.{count}"


def check_next_version(version: object, released: Iterable[str], today: datetime.date) -> None:
    """Raise ValueError unless `version` can be the plugin's next release.

    It must be YEAR.MONTH.RELEASE, name no month after `today`, be greater
    than every release, and count the releases of its month without a gap.
    A version set in one month may still be released in a later one.
    """

    year, month, release = parse_calver(version)
    if (year, month) > (today.year, today.month):
        raise ValueError(
            f"version {version} names a month after {today.year}.{today.month}, "
            "the current month in UTC"
        )
    latest = max(released, key=parse_version, default=None)
    expected = 0
    if latest is not None:
        first, second, third = parse_version(latest)
        if (year, month, release) <= (first, second, third):
            raise ValueError(f"version {version} must be greater than the latest release {latest}")
        if (first, second) == (year, month):
            expected = third + 1
    if release != expected:
        raise ValueError(
            f"version {version} must be {year}.{month}.{expected}: the third number counts "
            "the releases the plugin has already made in that month"
        )


def release_tag(plugin: str, version: str) -> str:
    """Return the `<plugin>--v<version>` release tag.

    The name follows Claude Code's plugin tag convention, but only the Release
    Plugin workflow creates these tags. `claude plugin tag` refuses them anyway:
    the marketplace entry moves to a version only after its tag exists.
    """

    validate_plugin_name(plugin)
    parse_version(version)
    return f"{plugin}--v{version}"


def run_git(root: pathlib.Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def released_versions(root: pathlib.Path, plugin: str) -> list[str]:
    """Return the plugin's released versions from local tags, oldest first."""

    validate_plugin_name(plugin)
    prefix = f"{plugin}--v"
    # for-each-ref is plumbing, so column.ui and tag.sort cannot reshape its output.
    result = run_git(
        root, ["for-each-ref", "--format=%(refname:lstrip=2)", f"refs/tags/{prefix}*"], check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git cannot list the release tags of {plugin}: {result.stderr.strip()}")
    versions = []
    for tag in result.stdout.splitlines():
        version = tag[len(prefix):]
        if VERSION_RE.fullmatch(version):
            versions.append(version)
    return sorted(versions, key=parse_version)


def marketplace_version(root: pathlib.Path, plugin: str) -> str | None:
    """Return the version the marketplace lists for a plugin, or None."""

    if plugin == "pstack":
        # Claude's native version is not the bundle's release version. This
        # record also supplies the released version in a tagless checkout.
        from pstack_release import read_published

        published = read_published(root)
        return published["version"] if published else None

    try:
        data = json.loads((root / MARKETPLACE_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    plugins = data.get("plugins") if isinstance(data, dict) else None
    for entry in plugins if isinstance(plugins, list) else []:
        if isinstance(entry, dict) and entry.get("name") == plugin:
            version = entry.get("version")
            if isinstance(version, str) and VERSION_RE.fullmatch(version):
                return version
            return None
    return None


def known_releases(root: pathlib.Path, plugin: str) -> list[str]:
    """Return the versions this checkout knows the plugin has released, oldest first.

    A release leaves a tag and then a marketplace entry. A checkout whose tags
    were not fetched still holds the entry, so both are read.
    """

    versions = set(released_versions(root, plugin))
    listed = marketplace_version(root, plugin)
    if listed is not None:
        versions.add(listed)
    return sorted(versions, key=parse_version)


def tag_commit(root: pathlib.Path, tag: str) -> str | None:
    """Return the commit a tag points at, or None when the tag does not exist."""

    result = run_git(root, ["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"], check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise RuntimeError(f"git cannot read tag {tag}: {result.stderr.strip()}")
    return result.stdout.strip()


def manifest_at(root: pathlib.Path, revision: str, plugin: str) -> dict:
    validate_plugin_name(plugin)
    if not revision or revision.startswith("-"):
        raise ValueError(f"invalid revision: {revision!r}")
    path = f"packages/{plugin}/{'bundle.json' if plugin == 'pstack' else 'plugin.json'}"
    result = run_git(root, ["show", f"{revision}:{path}"], check=False)
    if result.returncode != 0:
        raise ValueError(f"cannot read {path} at {revision}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError(f"{path} at {revision} is not a JSON object")
    return data


def marketplace_entry(plugin: str, version: str, description: str, sha: str) -> dict:
    if GIT_SHA_RE.fullmatch(sha) is None:
        raise ValueError(f"release commit must be a full 40-character SHA: {sha!r}")
    return {
        "name": plugin,
        "description": description,
        "version": version,
        "source": {
            "source": "git-subdir",
            "url": REPOSITORY_URL,
            "path": f"packages/{plugin}",
            "ref": release_tag(plugin, version),
            "sha": sha,
        },
    }
