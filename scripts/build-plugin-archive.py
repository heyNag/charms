#!/usr/bin/env python3
"""Build a deterministic, self-contained Agent Plugin ZIP and checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import stat
import sys
import zipfile
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from plugin_release import parse_version, validate_plugin_name  # noqa: E402
from pstack_bundle import bundle_archive_inputs  # noqa: E402
from plugin_archive import normalized_archive_key  # noqa: E402


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)



@dataclass(frozen=True)
class ArchiveResult:
    archive: pathlib.Path
    checksum: pathlib.Path
    version: str


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
    try:
        parse_version(version)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
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


def archive_inputs(
    root: pathlib.Path, plugin: str, target: str | None = None,
) -> tuple[str, list[tuple[pathlib.Path, str]]]:
    validate_plugin_name(plugin)
    if plugin == "pstack":
        version, selected = bundle_archive_inputs(root, target)
        normalized_names = [normalized_archive_key(name) for _, name in selected]
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("portable archive path collision")
        return version, selected
    if target is not None:
        raise ValueError("--target is only supported for the trusted pstack bundle")
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


def build_archive(
    root: pathlib.Path, plugin: str, output_dir: pathlib.Path, target: str | None = None,
) -> ArchiveResult:
    root = root.resolve()
    version, selected = archive_inputs(root, plugin, target)
    output_dir = output_dir.resolve()
    package_dir = (root / "packages" / plugin).resolve()
    if output_dir.is_relative_to(package_dir):
        raise ValueError("archive output directory must be outside the plugin root")
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{target}" if target is not None else ""
    kind = "bundle" if plugin == "pstack" and target is None else "agent-plugin"
    archive = output_dir / f"{plugin}{suffix}-{kind}-v{version}.zip"
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
    parser.add_argument(
        "--target", choices=["codex", "claude-code"],
        help="Create a selected-root transport ZIP from the trusted pstack bundle.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output_dir = args.output_dir or root / ".dist" / "agent-plugins"

    try:
        result = build_archive(root, args.plugin, output_dir, args.target)
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")

    print(f"archive={result.archive}")
    print(f"checksum={result.checksum}")
    print(f"version={result.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
