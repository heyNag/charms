#!/usr/bin/env python3
"""Check Python syntax without writing bytecode caches."""

from __future__ import annotations

import sys
from pathlib import Path


def check(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check-python-syntax.py FILE [...]", file=sys.stderr)
        return 2

    failed = False
    for raw_path in argv:
        path = Path(raw_path)
        try:
            check(path)
        except SyntaxError as exc:
            failed = True
            location = f"{path}:{exc.lineno or 0}:{exc.offset or 0}"
            print(f"{location}: syntax error: {exc.msg}", file=sys.stderr)
        except OSError as exc:
            failed = True
            print(f"{path}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
