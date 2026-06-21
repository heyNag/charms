#!/usr/bin/env python3
"""Verify package metadata used by generated targets and Skillshare hubs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_metadata import invalid_tags, load_json, normalized_tags, read_frontmatter


DEFAULT_HUB_SOURCE_PATH = "heyNag/agent-tools/packages"


def validate_package(root: Path, tool_path: Path) -> list[str]:
    errors: list[str] = []
    package_dir = tool_path.parent
    package = package_dir.name

    try:
        tool = load_json(tool_path)
    except Exception as exc:
        return [f"{tool_path.relative_to(root)}: {exc}"]

    if tool.get("public") is not True:
        return errors

    name = tool.get("name")
    if name != package:
        errors.append(f"{tool_path.relative_to(root)}: name must be {package!r}")
        name = package

    description = tool.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{tool_path.relative_to(root)}: description must be a non-empty string")

    tool_tags = normalized_tags(tool.get("tags"))
    if not tool_tags:
        errors.append(f"{tool_path.relative_to(root)}: tags must be a non-empty string array")
    for tag in invalid_tags(tool_tags):
        errors.append(f"{tool_path.relative_to(root)}: invalid tag {tag!r}")

    targets = tool.get("targets")
    if not isinstance(targets, list) or not all(isinstance(target, str) for target in targets):
        errors.append(f"{tool_path.relative_to(root)}: targets must be a string array")
    elif tool.get("agent_agnostic") is True and "generic" not in targets:
        errors.append(f"{tool_path.relative_to(root)}: agent_agnostic packages should target generic")

    skill_path = package_dir / "SKILL.md"
    if not skill_path.is_file():
        errors.append(f"{skill_path.relative_to(root)}: missing SKILL.md")
        return errors

    frontmatter = read_frontmatter(skill_path)
    if frontmatter.get("name") != name:
        errors.append(f"{skill_path.relative_to(root)}: frontmatter name must be {name!r}")
    skill_description = frontmatter.get("description")
    if not skill_description:
        errors.append(f"{skill_path.relative_to(root)}: frontmatter description is required")
    elif not str(skill_description).startswith("Use when "):
        errors.append(
            f"{skill_path.relative_to(root)}: frontmatter description must start with "
            "'Use when ' and describe trigger conditions"
        )

    skill_tags = normalized_tags(frontmatter.get("tags"))
    if not skill_tags:
        errors.append(f"{skill_path.relative_to(root)}: frontmatter tags are required")
    elif skill_tags != tool_tags:
        errors.append(
            f"{skill_path.relative_to(root)}: frontmatter tags {skill_tags!r} "
            f"must match tool.json tags {tool_tags!r}"
        )
    for tag in invalid_tags(skill_tags):
        errors.append(f"{skill_path.relative_to(root)}: invalid tag {tag!r}")

    return errors


def validate_skillshare_hub(root: Path) -> list[str]:
    hub_path = root / "skillshare-hub.json"
    errors: list[str] = []
    if not hub_path.is_file():
        return ["skillshare-hub.json: missing generated Skillshare hub"]

    try:
        hub = json.loads(hub_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"skillshare-hub.json: {exc}"]

    if hub.get("schemaVersion") != 1:
        errors.append("skillshare-hub.json: schemaVersion must be 1")
    if hub.get("sourcePath") != DEFAULT_HUB_SOURCE_PATH:
        errors.append(f"skillshare-hub.json: sourcePath must be {DEFAULT_HUB_SOURCE_PATH}")

    expected: dict[str, dict[str, object]] = {}
    for tool_path in sorted((root / "packages").glob("*/tool.json")):
        tool = load_json(tool_path)
        targets = tool.get("targets") or []
        if tool.get("public") is True and (tool.get("agent_agnostic") is True or "generic" in targets):
            name = tool.get("name") or tool_path.parent.name
            frontmatter = read_frontmatter(tool_path.parent / "SKILL.md")
            expected[name] = {
                "source": name,
                "description": frontmatter.get("description") or tool.get("description"),
                "tags": normalized_tags(frontmatter.get("tags")) or normalized_tags(tool.get("tags")),
            }

    seen: set[str] = set()
    skills = hub.get("skills")
    if not isinstance(skills, list):
        errors.append("skillshare-hub.json: skills must be an array")
        skills = []

    for index, skill in enumerate(skills):
        if not isinstance(skill, dict):
            errors.append(f"skillshare-hub.json: skills[{index}] must be an object")
            continue
        name = skill.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"skillshare-hub.json: skills[{index}].name is required")
            continue
        if name in seen:
            errors.append(f"skillshare-hub.json: duplicate skill {name}")
        seen.add(name)

        if name not in expected:
            errors.append(f"skillshare-hub.json: unexpected skill {name}")
            continue
        info = expected[name]
        if skill.get("source") != info["source"]:
            errors.append(f"skillshare-hub.json: {name}.source must be {info['source']}")
        if isinstance(skill.get("source"), str) and "://" in skill.get("source", ""):
            errors.append(f"skillshare-hub.json: {name}.source must be relative to sourcePath")
        if skill.get("source") and "/generated/" in str(skill.get("source")):
            errors.append(f"skillshare-hub.json: {name}.source must not point at generated output")
        if skill.get("skill") not in (None, "", name):
            errors.append(f"skillshare-hub.json: {name}.skill must be omitted or {name}")
        if skill.get("description") != info["description"]:
            errors.append(f"skillshare-hub.json: {name}.description must match SKILL.md frontmatter")
        if normalized_tags(skill.get("tags")) != info["tags"]:
            errors.append(f"skillshare-hub.json: {name}.tags must match SKILL.md frontmatter")

    for name in sorted(set(expected) - seen):
        errors.append(f"skillshare-hub.json: missing public agent-compatible skill {name}")

    return errors


def validate_skillignore(root: Path) -> list[str]:
    path = root / ".skillignore"
    if not path.is_file():
        return [".skillignore: missing; generated/ must stay hidden from Skillshare discovery"]
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if "generated/" not in lines and "generated" not in lines:
        return [".skillignore: must include generated/"]
    return []


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    root = Path(args[0]) if args else Path.cwd()
    root = root.resolve()

    errors: list[str] = []
    for tool_path in sorted((root / "packages").glob("*/tool.json")):
        errors.extend(validate_package(root, tool_path))
    errors.extend(validate_skillshare_hub(root))
    errors.extend(validate_skillignore(root))

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print("skill metadata verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
