#!/usr/bin/env python3
"""Build the public Skillshare hub index from package manifests."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


DEFAULT_REPOSITORY = "https://github.com/heyNag/agent-tools"
DEFAULT_OWNER_REPO = "heyNag/agent-tools"
DEFAULT_GENERATED_AT = "1970-01-01T00:00:00Z"
VERSION_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.\d+)?$")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"error: expected JSON object in {path}")
    return data


def plugin_version(package_dir: Path) -> str:
    plugin_path = package_dir / "plugin" / "plugin.json"
    if not plugin_path.exists():
        return ""
    value = load_json(plugin_path).get("version")
    return value if isinstance(value, str) else ""


def generated_at_for_versions(versions: list[str]) -> str:
    dates: list[tuple[int, int, int]] = []
    for version in versions:
        match = VERSION_DATE_RE.match(version)
        if not match:
            continue
        year, month, day = (int(part) for part in match.groups())
        dates.append((year, month, day))
    if not dates:
        return DEFAULT_GENERATED_AT
    year, month, day = max(dates)
    return f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"


def skill_entry(package_dir: Path, tool: dict) -> tuple[dict, str]:
    name = tool.get("name") or package_dir.name
    if not isinstance(name, str) or not name:
        raise SystemExit(f"error: invalid package name in {package_dir / 'tool.json'}")

    description = tool.get("description")
    if not isinstance(description, str) or not description:
        description = f"{name} agent skill."

    tags = tool.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise SystemExit(f"error: tags must be an array of strings in {package_dir / 'tool.json'}")

    source = f"{DEFAULT_OWNER_REPO}/packages/{name}"
    entry = {
        "name": name,
        "description": description,
        "source": source,
        "skill": name,
    }
    if tags:
        entry["tags"] = sorted(dict.fromkeys(tags))
    return entry, plugin_version(package_dir)


def build_index(root: Path) -> dict:
    skills: list[dict] = []
    versions: list[str] = []
    for tool_path in sorted((root / "packages").glob("*/tool.json")):
        package_dir = tool_path.parent
        tool = load_json(tool_path)
        targets = tool.get("targets") or []
        if tool.get("public") is not True:
            continue
        if not tool.get("agent_agnostic", False) and "generic" not in targets:
            continue
        entry, version = skill_entry(package_dir, tool)
        skills.append(entry)
        if version:
            versions.append(version)

    skills.sort(key=lambda item: item["name"])
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at_for_versions(versions),
        "sourcePath": DEFAULT_REPOSITORY,
        "skills": skills,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    root = root.resolve()
    out = root / "skillshare-hub.json"
    out.write_text(json.dumps(build_index(root), indent=2) + "\n", encoding="utf-8")
    print("built Skillshare hub: skillshare-hub.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
