#!/usr/bin/env python3
"""Build the public Skillshare hub index from package source metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_metadata import load_json, normalized_tags, read_frontmatter


DEFAULT_HUB_SOURCE_PATH = "heyNag/agent-tools"
DEFAULT_GENERATED_AT = "1970-01-01T00:00:00Z"
VERSION_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.\d+)?$")


def plugin_version(package_dir: Path) -> str:
    plugin_path = package_dir / ".claude-plugin" / "plugin.json"
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

    skill_path = package_dir / "skills" / name / "SKILL.md"
    frontmatter = read_frontmatter(skill_path) if skill_path.exists() else {}
    skill_name = frontmatter.get("name")
    if skill_name and skill_name != name:
        raise SystemExit(f"error: {skill_path} name is {skill_name!r}, expected {name!r}")

    description = frontmatter.get("description") or tool.get("description")
    if not isinstance(description, str) or not description:
        description = f"{name} agent skill."

    tool_tags = tool.get("tags") or []
    if not isinstance(tool_tags, list) or not all(isinstance(tag, str) for tag in tool_tags):
        raise SystemExit(f"error: tags must be an array of strings in {package_dir / 'tool.json'}")
    tags = normalized_tags(frontmatter.get("tags")) or normalized_tags(tool_tags)

    entry = {
        "name": name,
        "description": description,
        "source": f"packages/{name}/skills/{name}",
    }
    if tags:
        entry["tags"] = tags
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
        "sourcePath": DEFAULT_HUB_SOURCE_PATH,
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
