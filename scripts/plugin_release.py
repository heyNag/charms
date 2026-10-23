"""Shared Charms rules for plugin versions, release tags, and the marketplace."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess


PLUGIN_NAME_RE = re.compile(
    r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$"
)
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BUMP_PARTS = ("major", "minor", "patch")

MARKETPLACE_PATH = pathlib.PurePosixPath(".claude-plugin/marketplace.json")
MARKETPLACE_NAME = "charms"
REPOSITORY_URL = "https://github.com/heyNag/charms.git"


def validate_plugin_name(plugin: str) -> None:
    if PLUGIN_NAME_RE.fullmatch(plugin) is None:
        raise ValueError(f"invalid plugin name: {plugin!r}")


def parse_version(value: object) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"version is not MAJOR.MINOR.PATCH semantic versioning: {value!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def bump_version(value: str, part: str) -> str:
    major, minor, patch = parse_version(value)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unsupported version part: {part!r}")


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
    result = run_git(root, ["for-each-ref", "--format=%(refname:lstrip=2)", f"refs/tags/{prefix}*"])
    versions = []
    for tag in result.stdout.splitlines():
        version = tag[len(prefix):]
        if SEMVER_RE.fullmatch(version):
            versions.append(version)
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
    path = f"packages/{plugin}/plugin.json"
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
