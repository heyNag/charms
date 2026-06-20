#!/usr/bin/env python3
"""Add generated-file notices to comment-friendly generated outputs."""

from __future__ import annotations

import argparse
from pathlib import Path


BEGIN = "BEGIN GENERATED FROM SOURCE"
END = "END GENERATED FROM SOURCE"
SKIP_NAMES = {"GENERATED.md", "LICENSE"}
SKIP_SUFFIXES = {".json"}


def repo_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def markdown_notice(source: str) -> str:
    return (
        f"<!-- {BEGIN}: {source} -->\n"
        "<!-- Do not edit directly; edit the source path and run make build-packages. -->\n"
        f"<!-- {END} -->\n\n"
    )


def python_notice(source: str) -> str:
    return (
        f"# {BEGIN}: {source}\n"
        "# Do not edit directly; edit the source path and run make build-packages.\n"
        f"# {END}\n\n"
    )


def strip_existing_notice(text: str, suffix: str) -> str:
    lines = text.splitlines(keepends=True)
    if suffix == ".md":
        if lines and lines[0].startswith(f"<!-- {BEGIN}:"):
            end_index = None
            for index, line in enumerate(lines[:6]):
                if line.startswith(f"<!-- {END}"):
                    end_index = index
                    break
            if end_index is not None:
                remainder = lines[end_index + 1 :]
                if remainder and remainder[0].strip() == "":
                    remainder = remainder[1:]
                return "".join(remainder)
    if suffix == ".py":
        start_index = 1 if lines and lines[0].startswith("#!") else 0
        if len(lines) > start_index and lines[start_index].startswith(f"# {BEGIN}:"):
            end_index = None
            for index in range(start_index, min(len(lines), start_index + 6)):
                if lines[index].startswith(f"# {END}"):
                    end_index = index
                    break
            if end_index is not None:
                remainder = lines[:start_index] + lines[end_index + 1 :]
                if len(remainder) > start_index and remainder[start_index].strip() == "":
                    del remainder[start_index]
                return "".join(remainder)
    return text


def add_markdown_header(path: Path, source: str) -> None:
    text = strip_existing_notice(path.read_text(encoding="utf-8"), ".md")
    if text.startswith("---\n"):
        marker = text.find("\n---\n", 4)
        if marker != -1:
            insert_at = marker + len("\n---\n")
            updated = text[:insert_at] + markdown_notice(source) + text[insert_at:]
        else:
            updated = markdown_notice(source) + text
    else:
        updated = markdown_notice(source) + text
    path.write_text(updated, encoding="utf-8")


def add_python_header(path: Path, source: str) -> None:
    text = strip_existing_notice(path.read_text(encoding="utf-8"), ".py")
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        updated = lines[0] + python_notice(source) + "".join(lines[1:])
    else:
        updated = python_notice(source) + text
    path.write_text(updated, encoding="utf-8")


def add_header(path: Path, source: str) -> None:
    if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
        return
    if path.suffix == ".md":
        add_markdown_header(path, source)
    elif path.suffix == ".py":
        add_python_header(path, source)


def iter_mapped_files(generated: Path, source: Path) -> list[tuple[Path, Path]]:
    if generated.is_dir():
        pairs: list[tuple[Path, Path]] = []
        for path in sorted(generated.rglob("*")):
            if path.is_file():
                pairs.append((path, source / path.relative_to(generated)))
        return pairs
    return [(generated, source)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Add generated notices to generated files.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="GENERATED=SOURCE",
        help="Generated path and source path mapping",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    for raw_mapping in args.map:
        if "=" not in raw_mapping:
            raise SystemExit(f"invalid mapping {raw_mapping!r}; expected GENERATED=SOURCE")
        generated_raw, source_raw = raw_mapping.split("=", 1)
        generated = (root / generated_raw).resolve()
        source = (root / source_raw).resolve()
        if not generated.exists():
            raise SystemExit(f"generated path does not exist: {generated_raw}")
        for generated_file, source_file in iter_mapped_files(generated, source):
            add_header(generated_file, repo_relative(source_file, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
