#!/usr/bin/env python3
"""Safely extract a built plugin archive while preserving executable modes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_archive import extract_archive  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path, help="Absent or empty output directory")
    args = parser.parse_args(argv)
    try:
        extract_archive(args.archive, args.output)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        parser.exit(1, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
