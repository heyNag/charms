#!/usr/bin/env python3
"""Build a deterministic, self-contained Agent Plugin ZIP and checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass


PLUGIN_NAME_RE = re.compile(
    r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$"
)
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


@dataclass(frozen=True)
class ArchiveResult:
    archive: pathlib.Path
    checksum: pathlib.Path
    version: str


def validate_plugin_name(plugin: str) -> None:
    if PLUGIN_NAME_RE.fullmatch(plugin) is None:
        raise ValueError(f"invalid plugin name: {plugin!r}")


def require_regular_file(path: pathlib.Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing required file: {path}") from exc
    if stat.S_ISLNK(mode):
        raise ValueError(f"symlinks are not allowed in plugin archives: {path}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"archive input must be a regular file: {path}")


def require_real_directory(path: pathlib.Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing required directory: {path}") from exc
    if stat.S_ISLNK(mode):
        raise ValueError(f"symlinks are not allowed in plugin archives: {path}")
    if not stat.S_ISDIR(mode):
        raise ValueError(f"archive input must be a directory: {path}")


def load_manifest(path: pathlib.Path, plugin: str) -> tuple[dict, str]:
    require_regular_file(path)
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError(f"Agent Plugin manifest must be a JSON object: {path}")
    if manifest.get("name") != plugin:
        raise ValueError(f"{path} name is {manifest.get('name')!r}, expected {plugin!r}")
    version = manifest.get("version")
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"{path} version is not strict SemVer: {version!r}")
    return manifest, version


def regular_tree_files(root: pathlib.Path) -> list[pathlib.Path]:
    require_real_directory(root)
    files: list[pathlib.Path] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = pathlib.Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            require_real_directory(current_path / name)
        for name in file_names:
            path = current_path / name
            require_regular_file(path)
            files.append(path)
    return files


def normalized_archive_key(archive_name: str) -> str:
    if "\\" in archive_name:
        raise ValueError(f"backslashes are not allowed in archive paths: {archive_name!r}")
    components = archive_name.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError(f"invalid archive path component: {archive_name!r}")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in archive_name):
        raise ValueError(f"control characters are not allowed in archive paths: {archive_name!r}")
    for component in components:
        if any(character in WINDOWS_INVALID_CHARACTERS for character in component):
            raise ValueError(f"Windows-invalid character in archive path: {archive_name!r}")
        if component.endswith((".", " ")):
            raise ValueError(f"archive path component ends with a dot or space: {archive_name!r}")
        if component.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Windows-reserved archive path component: {archive_name!r}")
    return unicodedata.normalize("NFC", archive_name).casefold()


def archive_inputs(root: pathlib.Path, plugin: str) -> tuple[str, list[tuple[pathlib.Path, str]]]:
    validate_plugin_name(plugin)
    require_real_directory(root / "packages")
    package_dir = root / "packages" / plugin
    require_real_directory(package_dir)

    manifest_path = package_dir / "plugin.json"
    _, version = load_manifest(manifest_path, plugin)
    selected: list[tuple[pathlib.Path, str]] = [
        (manifest_path, f"{plugin}/plugin.json")
    ]

    skills_dir = package_dir / "skills"
    for source in regular_tree_files(skills_dir):
        relative = source.relative_to(package_dir).as_posix()
        selected.append((source, f"{plugin}/{relative}"))

    mcp_path = package_dir / "mcp.json"
    if mcp_path.exists() or mcp_path.is_symlink():
        require_regular_file(mcp_path)
        selected.append((mcp_path, f"{plugin}/mcp.json"))

    readme_path = package_dir / "README.md"
    require_regular_file(readme_path)
    selected.append((readme_path, f"{plugin}/README.md"))

    license_path = package_dir / "LICENSE"
    require_regular_file(license_path)
    selected.append((license_path, f"{plugin}/LICENSE"))

    selected.sort(key=lambda item: item[1])
    normalized_names: set[str] = set()
    for _, archive_name in selected:
        normalized = normalized_archive_key(archive_name)
        if normalized in normalized_names:
            raise ValueError(f"portable archive path collision: {archive_name}")
        normalized_names.add(normalized)
    return version, selected


def zip_info(archive_name: str, source_mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
    info.create_system = 3
    permissions = 0o755 if source_mode & 0o111 else 0o644
    info.external_attr = (stat.S_IFREG | permissions) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def build_archive(root: pathlib.Path, plugin: str, output_dir: pathlib.Path) -> ArchiveResult:
    root = root.resolve()
    version, selected = archive_inputs(root, plugin)
    output_dir = output_dir.resolve()
    package_dir = (root / "packages" / plugin).resolve()
    if output_dir.is_relative_to(package_dir):
        raise ValueError("archive output directory must be outside the plugin root")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{plugin}-agent-plugin-v{version}.zip"
    checksum = archive.with_suffix(archive.suffix + ".sha256")

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        for source, archive_name in selected:
            mode = source.lstat().st_mode
            handle.writestr(zip_info(archive_name, mode), source.read_bytes())

    with zipfile.ZipFile(archive) as handle:
        corrupt = handle.testzip()
        if corrupt is not None:
            raise ValueError(f"archive integrity check failed for entry: {corrupt}")

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return ArchiveResult(archive=archive.resolve(), checksum=checksum.resolve(), version=version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", help="Plugin package name under packages/")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        help="Artifact directory. Defaults to .dist/agent-plugins under the repository root.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output_dir = args.output_dir or root / ".dist" / "agent-plugins"

    try:
        result = build_archive(root, args.plugin, output_dir)
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")

    print(f"archive={result.archive}")
    print(f"checksum={result.checksum}")
    print(f"version={result.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
