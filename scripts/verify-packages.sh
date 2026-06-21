#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "error: $*" >&2
  exit 1
}

check_file() {
  [[ -f "$1" ]] || fail "missing file: ${1#$ROOT/}"
}

check_dir() {
  [[ -d "$1" ]] || fail "missing directory: ${1#$ROOT/}"
}

valid_json() {
  python3 -m json.tool "$1" >/dev/null || fail "invalid JSON: ${1#$ROOT/}"
}

validate_marketplace() {
  python3 - "$ROOT/.claude-plugin/marketplace.json" "$ROOT" <<'PY'
import json
import pathlib
import sys

marketplace_path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
data = json.loads(marketplace_path.read_text(encoding="utf-8"))

errors = []
if not isinstance(data.get("name"), str) or not data["name"]:
    errors.append("marketplace name must be a non-empty string")
owner = data.get("owner")
if not isinstance(owner, dict) or not isinstance(owner.get("name"), str) or not owner["name"]:
    errors.append("marketplace owner.name must be present")
plugins = data.get("plugins")
if not isinstance(plugins, list) or not plugins:
    errors.append("marketplace plugins must be a non-empty array")

expected = {}
for tool_path in sorted((root / "packages").glob("*/tool.json")):
    tool = json.loads(tool_path.read_text(encoding="utf-8"))
    targets = tool.get("targets") or []
    if tool.get("public") is True and "claude" in targets:
        name = tool.get("name") or tool_path.parent.name
        expected[name] = tool_path

seen = set()
for index, plugin in enumerate(plugins or []):
    if not isinstance(plugin, dict):
        errors.append(f"plugins[{index}] must be an object")
        continue
    name = plugin.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"plugins[{index}].name must be present")
        continue
    if name in seen:
        errors.append(f"duplicate plugin name: {name}")
    seen.add(name)
    if name not in expected:
        errors.append(f"marketplace plugin has no public Claude package: {name}")

    source = plugin.get("source")
    if not isinstance(source, str) or not source.startswith("./"):
        errors.append(f"plugins[{index}].source must be a relative ./ path")
    if "path" in plugin:
        errors.append(f"plugins[{index}].path is redundant; use source only")
    if isinstance(source, str):
        if ".." in pathlib.PurePosixPath(source).parts:
            errors.append(f"plugins[{index}].source must not contain '..'")
        if source != f"./generated/claude/plugins/{name}":
            errors.append(f"plugins[{index}].source should be ./generated/claude/plugins/{name}")
        source_dir = root / source.removeprefix("./")
        if not source_dir.is_dir():
            errors.append(f"plugins[{index}].source directory is missing: {source}")

    author = plugin.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"]:
        errors.append(f"plugins[{index}].author.name must be present")

    for field in ("description", "version", "repository", "license"):
        if not isinstance(plugin.get(field), str) or not plugin[field]:
            errors.append(f"plugins[{index}].{field} must be a non-empty string")

    if isinstance(source, str) and source.startswith("./"):
        plugin_json = root / source[2:] / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
            if manifest.get("name") != name:
                errors.append(f"plugins[{index}].name does not match {plugin_json}")
            if manifest.get("version") != plugin.get("version"):
                errors.append(f"plugins[{index}].version does not match {plugin_json}")

missing = sorted(set(expected) - seen)
for name in missing:
    errors.append(f"public Claude package missing from marketplace: {name}")

if errors:
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_skillshare_hub() {
  python3 - "$ROOT/skillshare-hub.json" "$ROOT" <<'PY'
import json
import pathlib
import sys

hub_path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
data = json.loads(hub_path.read_text(encoding="utf-8"))

errors = []
if data.get("schemaVersion") != 1:
    errors.append("skillshare hub schemaVersion must be 1")
if not isinstance(data.get("generatedAt"), str) or not data["generatedAt"]:
    errors.append("skillshare hub generatedAt must be present")
if data.get("sourcePath") != "heyNag/agent-tools/packages":
    errors.append("skillshare hub sourcePath must be heyNag/agent-tools/packages")

skills = data.get("skills")
if not isinstance(skills, list) or not skills:
    errors.append("skillshare hub skills must be a non-empty array")

expected = {}
for tool_path in sorted((root / "packages").glob("*/tool.json")):
    tool = json.loads(tool_path.read_text(encoding="utf-8"))
    targets = tool.get("targets") or []
    if tool.get("public") is True and (tool.get("agent_agnostic") is True or "generic" in targets):
        name = tool.get("name") or tool_path.parent.name
        expected[name] = tool

seen = set()
for index, skill in enumerate(skills or []):
    if not isinstance(skill, dict):
        errors.append(f"skills[{index}] must be an object")
        continue
    name = skill.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"skills[{index}].name must be present")
        continue
    if name in seen:
        errors.append(f"duplicate skillshare skill name: {name}")
    seen.add(name)
    if name not in expected:
        errors.append(f"skillshare hub skill has no public package: {name}")

    source = skill.get("source")
    expected_source = name
    if source != expected_source:
        errors.append(f"skills[{index}].source should be {expected_source}")
    if isinstance(source, str) and "://" in source:
        errors.append(f"skills[{index}].source must be relative to sourcePath")
    if isinstance(source, str) and "/generated/" in source:
        errors.append(f"skills[{index}].source must not point at generated output")

    if skill.get("skill") not in (None, "", name):
        errors.append(f"skills[{index}].skill should be omitted or {name}")
    if not isinstance(skill.get("description"), str) or not skill["description"]:
        errors.append(f"skills[{index}].description must be present")
    tags = skill.get("tags", [])
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
        errors.append(f"skills[{index}].tags must be an array of strings when present")

missing = sorted(set(expected) - seen)
for name in missing:
    errors.append(f"public agent-compatible package missing from skillshare hub: {name}")

if errors:
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_plugin_manifest() {
  python3 - "$1" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
errors = []
if not isinstance(data.get("name"), str) or not data["name"]:
    errors.append("plugin name must be a non-empty string")
author = data.get("author")
if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"]:
    errors.append("plugin author.name must be present")
for field in ("version", "description", "repository", "license"):
    if not isinstance(data.get(field), str) or not data[field]:
        errors.append(f"plugin {field} must be a non-empty string")
if errors:
    for error in errors:
        print(f"error: {path}: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

json_public() {
  python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print("true" if data.get("public") is True else "false")
PY
}

json_has_target() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
targets = data.get("targets") or []
print("true" if sys.argv[2] in targets else "false")
PY
}

scan_output() {
  local output_dir="$1"
  [[ -d "$output_dir" ]] || return 0

  local hits
  hits="$(
    find "$output_dir" \
      \( \
        -name ".env" -o \
        -name ".env.local" -o \
        -name ".watch-video" -o \
        -name ".x-bookmarks" -o \
        -name ".codex" -o \
        -name "auth.json" -o \
        -name "tokens.json" -o \
        -name "state.json" -o \
        -name "bookmarks.json" -o \
        -name "bookmarks.jsonl" -o \
        -name "bookmarks.ndjson" -o \
        -name "search-index.json" -o \
        -name "__pycache__" -o \
        -name ".pytest_cache" -o \
        -name ".mypy_cache" -o \
        -name ".ruff_cache" -o \
        -name ".venv" -o \
        -name "node_modules" -o \
        -name "dist" -o \
        -name ".DS_Store" -o \
        -name "frames" -o \
        -name "metadata.json" -o \
        -name "transcript.json" -o \
        -name "transcript.md" -o \
        -name "report.md" -o \
        -name "groq_transcript.raw.json" -o \
        -iname "rollout-*.jsonl" -o \
        -iname "*.sqlite" -o \
        -iname "*.sqlite3" -o \
        -iname "*.db" -o \
        -iname "frame_*.jpg" -o \
        -iname "frame_*.jpeg" -o \
        -iname "frame_*.png" -o \
        -iname "frame_*.webp" -o \
        -iname "*.mp3" -o \
        -iname "*.wav" -o \
        -iname "*.m4a" -o \
        -iname "*.aac" -o \
        -iname "*.mp4" -o \
        -iname "*.mov" -o \
        -iname "*.mkv" -o \
        -iname "*.webm" -o \
        -iname "*.webp" -o \
        -iname "*.avi" -o \
        -iname "*.flv" -o \
        -iname "*.wmv" \
      \) -print
  )"

  if [[ -n "$hits" ]]; then
    echo "$hits" >&2
    fail "generated package contains forbidden files under ${output_dir#$ROOT/}"
  fi

  python3 - "$output_dir" "$ROOT" <<'PY'
import pathlib
import re
import sys

output_dir = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
secret_patterns = [
    re.compile(r"gsk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
]
assignment = re.compile(r"\b(?:GROQ_API_KEY|OPENAI_API_KEY)\s*=\s*['\"]?([^'\"\s`]+)")
safe_values = {"", "...", "your-key", "your_groq_api_key", "<key>", "<your-key>"}
hits = []

for path in sorted(output_dir.rglob("*")):
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    rel = path.relative_to(root)
    for line_no, line in enumerate(text.splitlines(), start=1):
        if ".env.local" in line:
            hits.append(f"{rel}:{line_no}: .env.local")
        for pattern in secret_patterns:
            if pattern.search(line):
                hits.append(f"{rel}:{line_no}: {pattern.pattern}")
        match = assignment.search(line)
        if match:
            value = match.group(1).strip()
            if value not in safe_values and not value.startswith("$"):
                hits.append(f"{rel}:{line_no}: API key assignment")

if hits:
    for hit in hits:
        print(hit, file=sys.stderr)
    raise SystemExit(1)
PY
}

scan_metadata_file() {
  local metadata_file="$1"
  python3 - "$metadata_file" "$ROOT" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
secret_patterns = [
    re.compile(r"gsk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(?:GROQ_API_KEY|OPENAI_API_KEY)\s*="),
]
forbidden_text = [".env.local", "/generated/", "generated/"]
hits = []
text = path.read_text(encoding="utf-8")
rel = path.relative_to(root)
for line_no, line in enumerate(text.splitlines(), start=1):
    for pattern in secret_patterns:
        if pattern.search(line):
            hits.append(f"{rel}:{line_no}: {pattern.pattern}")
    for value in forbidden_text:
        if value in line:
            hits.append(f"{rel}:{line_no}: {value}")
if hits:
    for hit in hits:
        print(hit, file=sys.stderr)
    raise SystemExit(1)
PY
}

check_file "$ROOT/.claude-plugin/marketplace.json"
check_file "$ROOT/.claude-plugin/GENERATED.md"
check_file "$ROOT/skillshare-hub.json"
python3 "$ROOT/scripts/verify-skill-metadata.py" "$ROOT"
valid_json "$ROOT/.claude-plugin/marketplace.json"
valid_json "$ROOT/skillshare-hub.json"
scan_metadata_file "$ROOT/skillshare-hub.json"
validate_marketplace
validate_skillshare_hub

found=0
shopt -s nullglob
for tool_json in "$ROOT"/packages/*/tool.json; do
  found=1
  package="$(basename "$(dirname "$tool_json")")"
  package_dir="$ROOT/packages/$package"
  valid_json "$tool_json"

  if [[ "$(json_public "$tool_json")" != "true" ]]; then
    echo "skip: $package is not public"
    continue
  fi

  if [[ "$(json_has_target "$tool_json" claude)" == "true" ]]; then
    plugin_dir="$ROOT/generated/claude/plugins/$package"
    check_file "$plugin_dir/.claude-plugin/plugin.json"
    check_file "$plugin_dir/GENERATED.md"
    check_file "$plugin_dir/skills/$package/SKILL.md"
    check_file "$plugin_dir/README.md"
    check_file "$plugin_dir/LICENSE"
    valid_json "$plugin_dir/.claude-plugin/plugin.json"
    validate_plugin_manifest "$plugin_dir/.claude-plugin/plugin.json"

    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$plugin_dir/skills/$package/scripts"
    fi
    if [[ -d "$package_dir/references" ]]; then
      check_dir "$plugin_dir/skills/$package/references"
    fi
    if [[ -d "$package_dir/agents" ]]; then
      check_dir "$plugin_dir/skills/$package/agents"
    fi
    if [[ -d "$package_dir/commands" ]]; then
      check_dir "$plugin_dir/commands"
    fi
    scan_output "$plugin_dir"

    if command -v claude >/dev/null 2>&1; then
      if [[ "${CLAUDE_PLUGIN_VALIDATE:-0}" == "1" ]]; then
        claude plugin validate "$plugin_dir" || fail "Claude plugin validation failed for $package"
      else
        echo "skip: claude CLI validation for $package (set CLAUDE_PLUGIN_VALIDATE=1 to enable)"
      fi
    else
      echo "skip: claude CLI not found for $package"
    fi
  fi

  if [[ "$(json_has_target "$tool_json" codex)" == "true" ]]; then
    codex_dir="$ROOT/generated/codex/skills/$package"
    check_file "$codex_dir/GENERATED.md"
    check_file "$codex_dir/SKILL.md"
    check_file "$codex_dir/README.md"
    check_file "$codex_dir/LICENSE"
    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$codex_dir/scripts"
    fi
    if [[ -d "$package_dir/references" ]]; then
      check_dir "$codex_dir/references"
    fi
    if [[ -d "$package_dir/agents" ]]; then
      check_dir "$codex_dir/agents"
    fi
    scan_output "$codex_dir"
  fi

  if [[ "$(json_has_target "$tool_json" generic)" == "true" ]]; then
    agent_dir="$ROOT/generated/agent-skills/$package"
    check_file "$agent_dir/GENERATED.md"
    check_file "$agent_dir/SKILL.md"
    check_file "$agent_dir/README.md"
    check_file "$agent_dir/LICENSE"
    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$agent_dir/scripts"
    fi
    if [[ -d "$package_dir/references" ]]; then
      check_dir "$agent_dir/references"
    fi
    if [[ -d "$package_dir/agents" ]]; then
      check_dir "$agent_dir/agents"
    fi
    scan_output "$agent_dir"

    claude_skill_dir="$ROOT/generated/claude/custom-skills/$package"
    check_file "$claude_skill_dir/GENERATED.md"
    check_file "$claude_skill_dir/skill.md"
    check_file "$claude_skill_dir/README.md"
    check_file "$claude_skill_dir/LICENSE"
    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$claude_skill_dir/scripts"
    fi
    if [[ -d "$package_dir/references" ]]; then
      check_dir "$claude_skill_dir/references"
    fi
    if [[ -d "$package_dir/agents" ]]; then
      check_dir "$claude_skill_dir/agents"
    fi
    scan_output "$claude_skill_dir"
  fi
done

[[ "$found" -eq 1 ]] || fail "no package manifests found under packages/*/tool.json"

echo "package verification passed"
