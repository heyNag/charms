"""Shared helpers for package and Skillshare metadata checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_frontmatter(path: Path) -> dict[str, str]:
    """Read simple top-level YAML frontmatter from a Markdown skill file.

    The repo only needs scalar top-level fields here. Nested YAML is ignored so
    this stays dependency-free and predictable in CI.
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            fields[key] = _strip_quotes(value)
    return fields


def parse_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []

    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [_strip_quotes(part) for part in value.split(",") if _strip_quotes(part)]


def normalized_tags(value: object) -> list[str]:
    return sorted(dict.fromkeys(parse_tags(value)))


def invalid_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if not TAG_RE.match(tag)]
