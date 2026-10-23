"""Git helpers for release tests, isolated from the developer's Git configuration."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import unittest
from unittest import mock


# Drop inherited GIT_* variables: a Git hook exports GIT_DIR and GIT_INDEX_FILE,
# which would point fixture commands at the developer's own repository.
GIT_ENV = {
    **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    # Without a global config, Git still reads ~/.config/git/ignore and attributes.
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "core.excludesFile",
    "GIT_CONFIG_VALUE_0": os.devnull,
    "GIT_CONFIG_KEY_1": "core.attributesFile",
    "GIT_CONFIG_VALUE_1": os.devnull,
    "GIT_AUTHOR_NAME": "Charms Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Charms Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}
EMPTY_MARKETPLACE = {
    "name": "charms",
    "owner": {"name": "Charms Test"},
    "metadata": {"description": "Test marketplace."},
    "plugins": [],
}


def isolate_git(test: unittest.TestCase) -> None:
    """Run the code under test with the same isolated Git environment as the fixtures."""

    test.enterContext(mock.patch.dict(os.environ, GIT_ENV, clear=True))


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=GIT_ENV,
    )
    return result.stdout.strip()


def init_repository(root: pathlib.Path) -> None:
    git(root, "init", "--quiet", "--initial-branch", "main")


def commit_all(root: pathlib.Path, message: str = "Commit") -> str:
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "--allow-empty", "--message", message)
    return git(root, "rev-parse", "HEAD")


def write_json(path: pathlib.Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_marketplace(root: pathlib.Path, plugins: list | None = None) -> pathlib.Path:
    path = root / ".claude-plugin" / "marketplace.json"
    write_json(path, {**EMPTY_MARKETPLACE, "plugins": plugins or []})
    return path
