#!/usr/bin/env python3
"""Validate Charms Agent Plugins v1 packages.

With no arguments, validate the complete repository and require every immediate
directory under ``packages/`` to be the only kind of plugin root. With one or
more arguments, validate just those plugin roots.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from skills_ref import validate as validate_skill

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugin_release import (  # noqa: E402
    GIT_SHA_RE,
    MARKETPLACE_NAME,
    MARKETPLACE_PATH,
    manifest_at,
    marketplace_entry,
    parse_version,
    tag_commit,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_RELATIVE_PATH = Path("schemas/agent-plugins/1.0.0/plugin.schema.json")
CANONICAL_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

# Charms deliberately uses one independently released plugin with one same-name
# skill. These are product invariants, stricter than the base Agent Plugins spec.
REQUIRED_STRING_FIELDS = ("version", "description", "homepage", "repository", "license")
REQUIRED_PACKAGE_FILES = ("README.md", "LICENSE")
EXTENSION_NAMESPACE_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$"
)

# The one shared marketplace lives at .claude-plugin/marketplace.json. Codex reads
# .agents/plugins/marketplace.json first, so a second manifest there would shadow it.
DISALLOWED_ROOT_SURFACES = (
    ".agents",
    ".codex-plugin",
    ".cursor-plugin",
    ".opencode",
    ".skillignore",
    "commands",
    "package.json",
    "plugin.json",
    "skills",
    "skillshare-hub.json",
)
DISALLOWED_PACKAGE_SURFACES = (".claude-plugin", "commands", "tool.json")
MARKETPLACE_KEYS = {"name", "owner", "metadata", "plugins"}
MARKETPLACE_ENTRY_KEYS = {"name", "description", "version", "source"}

FORBIDDEN_DIRECTORY_NAMES = {
    ".codex",
    ".dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".watch-video",
    ".x-bookmarks",
    "__pycache__",
    "dist",
    "frames",
    "node_modules",
}
FORBIDDEN_FILE_NAMES = {
    ".env",
    ".env.local",
    "auth.json",
    "bookmarks.json",
    "bookmarks.jsonl",
    "bookmarks.ndjson",
    "groq_transcript.raw.json",
    "metadata.json",
    "report.md",
    "search-index.json",
    "state.json",
    "tokens.json",
    "transcript.json",
    "transcript.md",
}
FORBIDDEN_SUFFIXES = {
    ".aac",
    ".avi",
    ".db",
    ".flv",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".sqlite",
    ".sqlite3",
    ".wav",
    ".webm",
    ".wmv",
}
FRAME_FILE_RE = re.compile(r"^frame_.*\.(?:jpe?g|png|webp)$", re.IGNORECASE)
ROLLOUT_FILE_RE = re.compile(r"^rollout-.*\.jsonl$", re.IGNORECASE)
SECRET_RE = re.compile(
    rb"gsk_[A-Za-z0-9_-]{12,}"
    rb"|sk-[A-Za-z0-9_-]{12,}"
    rb"|ghp_[A-Za-z0-9]{20,}"
    rb"|github_pat_[A-Za-z0-9_]{20,}"
    rb"|xox[baprs]-[A-Za-z0-9-]{10,}"
    rb"|OPENAI_API_KEY\s*=\s*sk-[A-Za-z0-9_-]{12,}"
    rb"|GROQ_API_KEY\s*=\s*gsk_[A-Za-z0-9_-]{12,}"
)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def _resolve_contained(
    path: Path,
    boundary: Path,
    root: Path,
    errors: list[str],
    *,
    label: str,
) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        errors.append(f"{_display(path, root)}: {label} cannot be resolved: {exc}")
        return None

    try:
        resolved_boundary = boundary.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        errors.append(f"{_display(boundary, root)}: plugin root cannot be resolved: {exc}")
        return None

    if not _is_within(resolved, resolved_boundary):
        errors.append(f"{_display(path, root)}: {label} resolves outside the plugin root")
        return None
    return resolved


def _load_schema(path: Path) -> tuple[Draft202012Validator | None, list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"{path}: missing vendored Agent Plugins schema"]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"{path}: cannot load vendored Agent Plugins schema: {exc}"]

    try:
        Draft202012Validator.check_schema(data)
    except Exception as exc:  # jsonschema exposes several schema-error subclasses
        errors.append(f"{path}: invalid vendored Agent Plugins schema: {exc}")
        return None, errors
    if data.get("$id") != CANONICAL_SCHEMA:
        errors.append(f"{path}: schema $id must be {CANONICAL_SCHEMA}")
        return None, errors
    return Draft202012Validator(data), errors


def _schema_errors(
    validator: Draft202012Validator,
    manifest: Any,
    manifest_path: Path,
    root: Path,
) -> list[str]:
    errors: list[str] = []
    ordered = sorted(
        validator.iter_errors(manifest),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    for error in ordered:
        suffix = "".join(f"[{part!r}]" for part in error.absolute_path)
        errors.append(f"{_display(manifest_path, root)}{suffix}: {error.message}")
    return errors


def _walk_without_following_symlinks(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    for current, directories, files in os.walk(root, followlinks=False):
        yield Path(current), directories, files


def _validate_symlinks(plugin_root: Path, report_root: Path) -> list[str]:
    errors: list[str] = []
    for current, directories, files in _walk_without_following_symlinks(plugin_root):
        for name in [*directories, *files]:
            path = current / name
            if path.is_symlink():
                _resolve_contained(path, plugin_root, report_root, errors, label="symlink")
    return errors


def _git_visible_files(scan_root: Path) -> list[Path] | None:
    """Return tracked and unignored files, or None outside a Git work tree."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(scan_root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [scan_root / os.fsdecode(item) for item in result.stdout.split(b"\0") if item]


def _scan_file_artifact(path: Path, report_root: Path, errors: list[str]) -> None:
    name = path.name
    forbidden_parent = None
    for parent in path.parents:
        if parent == report_root:
            break
        if parent.name in FORBIDDEN_DIRECTORY_NAMES:
            forbidden_parent = parent
            break
    if forbidden_parent is not None:
        message = f"{_display(forbidden_parent, report_root)}: forbidden local artifact directory"
        if message not in errors:
            errors.append(message)
        return

    if (
        name in FORBIDDEN_FILE_NAMES
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
        or FRAME_FILE_RE.match(name)
        or ROLLOUT_FILE_RE.match(name)
    ):
        errors.append(f"{_display(path, report_root)}: forbidden local artifact file")
        return
    if path.is_symlink() or not path.is_file():
        return
    try:
        content = path.read_bytes()
    except OSError as exc:
        errors.append(f"{_display(path, report_root)}: cannot scan file: {exc}")
        return
    if SECRET_RE.search(content):
        errors.append(f"{_display(path, report_root)}: possible secret value found")


def _validate_repository_artifacts(
    scan_root: Path,
    report_root: Path,
    *,
    honor_gitignore: bool = False,
) -> list[str]:
    errors: list[str] = []
    if honor_gitignore:
        visible_files = _git_visible_files(scan_root)
        if visible_files is not None:
            for path in visible_files:
                _scan_file_artifact(path, report_root, errors)
            return errors

    for current, directories, files in _walk_without_following_symlinks(scan_root):
        if current == scan_root:
            directories[:] = [name for name in directories if name != ".git"]

        kept_directories: list[str] = []
        for name in directories:
            path = current / name
            if name in FORBIDDEN_DIRECTORY_NAMES:
                errors.append(f"{_display(path, report_root)}: forbidden local artifact directory")
            else:
                kept_directories.append(name)
        directories[:] = kept_directories

        for name in files:
            path = current / name
            _scan_file_artifact(path, report_root, errors)
    return errors


def _validate_manifest_quality(manifest: dict[str, Any], manifest_path: Path, root: Path) -> list[str]:
    errors: list[str] = []
    display = _display(manifest_path, root)

    for field in REQUIRED_STRING_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{display}: {field} must be a non-empty string for a Charms release")

    version = manifest.get("version")
    if isinstance(version, str) and version:
        try:
            parse_version(version)
        except ValueError:
            errors.append(f"{display}: version must be MAJOR.MINOR.PATCH semantic versioning")

    author = manifest.get("author")
    if not isinstance(author, dict):
        errors.append(f"{display}: author must be an object for a Charms release")
    else:
        for field in ("name", "url"):
            value = author.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"{display}: author.{field} must be a non-empty string for a Charms release"
                )

    keywords = manifest.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        errors.append(f"{display}: keywords must be a non-empty string array for a Charms release")
    elif any(not isinstance(keyword, str) or not keyword.strip() for keyword in keywords):
        errors.append(f"{display}: keywords entries must be non-empty strings")
    elif len(keywords) != len(set(keywords)):
        errors.append(f"{display}: keywords must not contain duplicates")

    extensions = manifest.get("extensions")
    if isinstance(extensions, dict):
        for namespace in extensions:
            if not EXTENSION_NAMESPACE_RE.fullmatch(namespace):
                errors.append(f"{display}: extension namespace {namespace!r} must be reverse-domain style")

    return errors


def _validate_skill(plugin_root: Path, plugin_name: str, report_root: Path) -> list[str]:
    errors: list[str] = []
    skills_path = plugin_root / "skills"
    if not _lexists(skills_path):
        return [f"{_display(skills_path, report_root)}: missing required skills directory"]

    resolved_skills = _resolve_contained(
        skills_path,
        plugin_root,
        report_root,
        errors,
        label="skills directory",
    )
    if resolved_skills is None:
        return errors
    if not resolved_skills.is_dir():
        errors.append(f"{_display(skills_path, report_root)}: skills must resolve to a directory")
        return errors

    child_directories = sorted(
        child.name
        for child in skills_path.iterdir()
        if child.is_dir() or child.is_symlink()
    )
    if child_directories != [plugin_name]:
        errors.append(
            f"{_display(skills_path, report_root)}: expected exactly one immediate skill "
            f"directory named {plugin_name!r}, found {child_directories!r}"
        )

    skill_path = skills_path / plugin_name
    if not _lexists(skill_path):
        return errors
    resolved_skill = _resolve_contained(
        skill_path,
        plugin_root,
        report_root,
        errors,
        label="skill directory",
    )
    if resolved_skill is None:
        return errors
    if not resolved_skill.is_dir():
        errors.append(f"{_display(skill_path, report_root)}: skill must resolve to a directory")
        return errors

    skill_file = skill_path / "SKILL.md"
    if not _lexists(skill_file):
        errors.append(f"{_display(skill_file, report_root)}: missing required SKILL.md")
        return errors
    resolved_file = _resolve_contained(
        skill_file,
        plugin_root,
        report_root,
        errors,
        label="SKILL.md",
    )
    if resolved_file is None:
        return errors
    if not resolved_file.is_file():
        errors.append(f"{_display(skill_file, report_root)}: SKILL.md must resolve to a regular file")
        return errors

    for problem in validate_skill(skill_path):
        errors.append(f"{_display(skill_path, report_root)}: {problem}")

    nested_skill_files = []
    for current, _directories, files in _walk_without_following_symlinks(skills_path):
        for filename in files:
            candidate = current / filename
            if filename == "SKILL.md" and candidate != skill_file:
                nested_skill_files.append(_display(candidate, report_root))
    for candidate in sorted(nested_skill_files):
        errors.append(f"{candidate}: unexpected additional SKILL.md")

    client_agents = skill_path / "agents"
    if _lexists(client_agents):
        errors.append(
            f"{_display(client_agents, report_root)}: client-specific agents directory "
            "is not part of the Charms v1 package shape"
        )
    return errors


def validate_plugin_root(
    plugin_root: Path,
    validator: Draft202012Validator,
    *,
    report_root: Path | None = None,
    scan_artifacts: bool = True,
) -> list[str]:
    """Validate one plugin root and return deterministic human-readable errors."""

    plugin_root = plugin_root.absolute()
    report_root = (report_root or plugin_root.parent).absolute()
    errors: list[str] = []

    if not _lexists(plugin_root):
        return [f"{_display(plugin_root, report_root)}: plugin root does not exist"]
    try:
        resolved_root = plugin_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return [f"{_display(plugin_root, report_root)}: plugin root cannot be resolved: {exc}"]
    if not resolved_root.is_dir():
        return [f"{_display(plugin_root, report_root)}: plugin root must be a directory"]

    for filename in REQUIRED_PACKAGE_FILES:
        path = plugin_root / filename
        if not _lexists(path):
            errors.append(f"{_display(path, report_root)}: missing required package file")
            continue
        if path.is_symlink() or not path.is_file():
            errors.append(
                f"{_display(path, report_root)}: required package file must be a regular file"
            )

    for relative in DISALLOWED_PACKAGE_SURFACES:
        path = plugin_root / relative
        if _lexists(path):
            errors.append(
                f"{_display(path, report_root)}: surface is not part of the Charms v1 package shape"
            )

    mcp_path = plugin_root / "mcp.json"
    if _lexists(mcp_path):
        errors.append(f"{_display(mcp_path, report_root)}: mcp.json is not allowed without a real Charms MCP server")

    manifest_path = plugin_root / "plugin.json"
    if not _lexists(manifest_path):
        errors.append(f"{_display(manifest_path, report_root)}: missing Agent Plugins manifest")
        errors.extend(_validate_symlinks(plugin_root, report_root))
        if scan_artifacts:
            errors.extend(_validate_repository_artifacts(plugin_root, report_root))
        return sorted(dict.fromkeys(errors))

    resolved_manifest = _resolve_contained(
        manifest_path,
        plugin_root,
        report_root,
        errors,
        label="plugin manifest",
    )
    manifest: Any = None
    if resolved_manifest is not None:
        if not resolved_manifest.is_file():
            errors.append(f"{_display(manifest_path, report_root)}: manifest must resolve to a regular file")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"{_display(manifest_path, report_root)}: invalid JSON: {exc}")

    if manifest is not None:
        errors.extend(_schema_errors(validator, manifest, manifest_path, report_root))
        if isinstance(manifest, dict):
            errors.extend(_validate_manifest_quality(manifest, manifest_path, report_root))
            name = manifest.get("name")
            if isinstance(name, str):
                if name != plugin_root.name:
                    errors.append(
                        f"{_display(manifest_path, report_root)}: manifest name {name!r} "
                        f"must match plugin directory {plugin_root.name!r}"
                    )
                errors.extend(_validate_skill(plugin_root, name, report_root))

    nested_manifests: list[str] = []
    for current, _directories, files in _walk_without_following_symlinks(plugin_root):
        for filename in files:
            candidate = current / filename
            if filename == "plugin.json" and candidate != manifest_path:
                nested_manifests.append(_display(candidate, report_root))
    for candidate in sorted(nested_manifests):
        errors.append(f"{candidate}: unexpected nested plugin manifest")

    errors.extend(_validate_symlinks(plugin_root, report_root))
    if scan_artifacts:
        errors.extend(_validate_repository_artifacts(plugin_root, report_root))
    return sorted(dict.fromkeys(errors))


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_marketplace_entry(
    root: Path,
    entry: dict[str, Any],
    label: str,
    package_version: Any,
) -> list[str]:
    name = entry["name"]
    version = entry["version"]
    description = entry["description"]
    source = entry["source"]
    if not _non_empty_string(description):
        return [f"{label}: description must be a non-empty string"]
    sha = source.get("sha") if isinstance(source, dict) else None
    if not isinstance(sha, str) or GIT_SHA_RE.fullmatch(sha) is None:
        return [f"{label}: source.sha must be the full 40-character release commit SHA"]
    try:
        expected = marketplace_entry(name, version, description, sha)
    except ValueError as exc:
        return [f"{label}: {exc}"]
    if entry != expected:
        return [f"{label}: source must be {json.dumps(expected['source'], sort_keys=True)}"]

    errors: list[str] = []
    try:
        if parse_version(package_version) < parse_version(version):
            errors.append(
                f"{label}: released version {version} is newer than "
                f"packages/{name}/plugin.json version {package_version}"
            )
    except ValueError:
        pass  # The manifest check reports an invalid package version.

    ref = expected["source"]["ref"]
    try:
        commit = tag_commit(root, ref)
        released = manifest_at(root, sha, name) if commit == sha else None
    except (OSError, RuntimeError) as exc:
        return errors + [f"{label}: git is required to verify the release pin: {exc}"]
    except (ValueError, json.JSONDecodeError) as exc:
        return errors + [f"{label}: {exc}"]
    if commit is None:
        errors.append(f"{label}: release tag {ref} is not available locally; run `git fetch --tags`")
    elif commit != sha:
        errors.append(f"{label}: release tag {ref} points at {commit}, not {sha}")
    elif released.get("version") != version or released.get("description") != description:
        errors.append(
            f"{label}: version and description must match packages/{name}/plugin.json at {sha}"
        )
    return errors


def _validate_marketplace(root: Path, plugin_roots: list[Path]) -> list[str]:
    """Validate the shared Claude Code and Codex marketplace manifest."""

    display = MARKETPLACE_PATH.as_posix()
    directory = root / MARKETPLACE_PATH.parent
    path = root / MARKETPLACE_PATH
    if not _lexists(path):
        return [f"{display}: missing marketplace manifest for Claude Code and Codex installs"]
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        return [f"{display}: marketplace manifest must be a regular file in a real directory"]

    visible = _git_visible_files(directory)
    children = (
        {path.relative_to(directory).parts[0] for path in visible}
        if visible is not None
        else {child.name for child in directory.iterdir()}
    )
    errors = [
        f"{_display(directory / name, root)}: only {MARKETPLACE_PATH.name} is allowed in "
        f"{MARKETPLACE_PATH.parent.as_posix()}"
        for name in sorted(children)
        if name != MARKETPLACE_PATH.name
    ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return errors + [f"{display}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return errors + [f"{display}: marketplace manifest must be a JSON object"]

    if set(data) != MARKETPLACE_KEYS:
        errors.append(f"{display}: top-level keys must be exactly {sorted(MARKETPLACE_KEYS)}")
    if data.get("name") != MARKETPLACE_NAME:
        errors.append(f"{display}: name must be {MARKETPLACE_NAME!r}")
    owner = data.get("owner")
    if not isinstance(owner, dict) or set(owner) != {"name"} or not _non_empty_string(owner["name"]):
        errors.append(f"{display}: owner must contain only a non-empty name")
    metadata = data.get("metadata")
    if (
        not isinstance(metadata, dict)
        or set(metadata) != {"description"}
        or not _non_empty_string(metadata["description"])
    ):
        errors.append(f"{display}: metadata must contain only a non-empty description")
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return errors + [f"{display}: plugins must be an array"]

    package_versions: dict[str, Any] = {}
    for plugin_root in plugin_roots:
        try:
            manifest = json.loads((plugin_root / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue  # The plugin root check reports the broken manifest.
        if isinstance(manifest, dict):
            package_versions[plugin_root.name] = manifest.get("version")

    names: list[str] = []
    for index, entry in enumerate(plugins):
        label = f"{display}[plugins][{index}]"
        if not isinstance(entry, dict) or set(entry) != MARKETPLACE_ENTRY_KEYS:
            errors.append(f"{label}: entry keys must be exactly {sorted(MARKETPLACE_ENTRY_KEYS)}")
            continue
        name = entry["name"]
        if not isinstance(name, str) or name not in package_versions:
            errors.append(f"{label}: {name!r} is not a plugin under packages/")
            continue
        names.append(name)
        errors.extend(_validate_marketplace_entry(root, entry, label, package_versions[name]))
    if names != sorted(set(names)):
        errors.append(f"{display}: plugins must be sorted by name without duplicates")
    return errors


def _plugin_directories(packages_path: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in packages_path.iterdir()
            if path.is_dir() or path.is_symlink()
        ),
        key=lambda path: path.name,
    )


def validate_repository(root: Path) -> tuple[list[Path], list[str]]:
    """Validate the complete Charms repository."""

    root = root.absolute()
    schema_path = root / SCHEMA_RELATIVE_PATH
    validator, errors = _load_schema(schema_path)
    if validator is None:
        return [], errors

    for relative in DISALLOWED_ROOT_SURFACES:
        path = root / relative
        if _lexists(path):
            errors.append(
                f"{_display(path, root)}: root plugin or client surface is not part of the "
                "Charms v1 repository shape"
            )

    packages_path = root / "packages"
    if not _lexists(packages_path):
        errors.append("packages: missing packages directory")
        errors.extend(_validate_repository_artifacts(root, root, honor_gitignore=True))
        return [], sorted(dict.fromkeys(errors))
    try:
        resolved_packages = packages_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        errors.append(f"packages: cannot resolve packages directory: {exc}")
        return [], sorted(dict.fromkeys(errors))
    if not resolved_packages.is_dir():
        errors.append("packages: packages must resolve to a directory")
        return [], sorted(dict.fromkeys(errors))
    if not _is_within(resolved_packages, root.resolve(strict=True)):
        errors.append("packages: packages directory resolves outside the repository")
        return [], sorted(dict.fromkeys(errors))

    plugin_roots = _plugin_directories(packages_path)
    if not plugin_roots:
        errors.append("packages: no plugin roots found")
    for plugin_root in plugin_roots:
        try:
            resolved_plugin_root = plugin_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            errors.append(
                f"{_display(plugin_root, root)}: plugin root cannot be resolved: {exc}"
            )
            continue
        if not _is_within(resolved_plugin_root, root.resolve(strict=True)):
            errors.append(
                f"{_display(plugin_root, root)}: plugin root resolves outside the repository"
            )
            continue
        errors.extend(
            validate_plugin_root(
                plugin_root,
                validator,
                report_root=root,
                scan_artifacts=False,
            )
        )

    errors.extend(_validate_marketplace(root, plugin_roots))

    expected_manifests = {plugin_root / "plugin.json" for plugin_root in plugin_roots}
    for current, directories, files in _walk_without_following_symlinks(root):
        if current == root:
            directories[:] = [name for name in directories if name != ".git"]
        if ".git" in current.parts:
            continue
        for filename in files:
            candidate = current / filename
            if filename == "plugin.json" and candidate not in expected_manifests:
                errors.append(f"{_display(candidate, root)}: plugin manifests are allowed only at packages/*/plugin.json")

    errors.extend(_validate_repository_artifacts(root, root, honor_gitignore=True))
    return plugin_roots, sorted(dict.fromkeys(errors))


def validate_explicit_plugins(paths: Iterable[Path]) -> tuple[list[Path], list[str]]:
    schema_path = REPOSITORY_ROOT / SCHEMA_RELATIVE_PATH
    validator, errors = _load_schema(schema_path)
    if validator is None:
        return [], errors

    plugin_roots: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        absolute = path.absolute()
        if absolute in seen:
            continue
        seen.add(absolute)
        plugin_roots.append(absolute)
        errors.extend(validate_plugin_root(absolute, validator, report_root=Path.cwd().absolute()))
    return plugin_roots, sorted(dict.fromkeys(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plugin_roots",
        nargs="*",
        type=Path,
        help="Optional plugin roots. With no paths, validate the complete repository.",
    )
    args = parser.parse_args(argv)

    if args.plugin_roots:
        plugin_roots, errors = validate_explicit_plugins(args.plugin_roots)
    else:
        plugin_roots, errors = validate_repository(REPOSITORY_ROOT)

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"validated {len(plugin_roots)} Agent Plugins v1 package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
