"""Portable archive names and mode-preserving extraction for built plugins."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile
import unicodedata
import zipfile

WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
MAX_ARCHIVE_FILES = 100_000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


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


def extract_archive(archive: Path, output: Path) -> Path:
    """Extract a built archive into an absent/empty directory without losing modes.

    Validate the complete entry set before writing, extract to private staging,
    and replace the empty destination only after every member's CRC succeeds.
    No member-controlled symlink, special file, overwrite, or traversal is allowed.
    """
    archive, output = archive.absolute(), output.absolute()
    for ancestor in (output, *output.parents):
        if ancestor.is_symlink():
            raise ValueError(f"archive output must not use a symlink: {ancestor}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("archive output must be an absent or empty directory")
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("archive input must be a regular file")
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if not entries or len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("archive has an invalid entry count")
        if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds the uncompressed size limit")
        keys = set()
        for entry in entries:
            key = normalized_archive_key(entry.filename)
            if key in keys:
                raise ValueError(f"portable archive path collision: {entry.filename}")
            keys.add(key)
            mode = entry.external_attr >> 16
            if entry.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise ValueError(f"archive entries must be regular files: {entry.filename}")
            if entry.flag_bits & 1:
                raise ValueError("encrypted archive entries are unsupported")
        for key in keys:
            parts = key.split("/")
            if any("/".join(parts[:n]) in keys for n in range(1, len(parts))):
                raise ValueError("archive file/directory path collision")
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".plugin-extract-", dir=output.parent))
        try:
            for entry in entries:
                target = stage / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
                mode = entry.external_attr >> 16
                target.chmod(0o755 if mode & 0o111 else 0o644)
            if output.exists():
                output.rmdir()
            os.replace(stage, output)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return output
