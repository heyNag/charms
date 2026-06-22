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
if data.get("name") != "agent-tools":
    errors.append("marketplace name must be agent-tools")
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
        expected[name] = tool_path.parent

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
    expected_source = f"./packages/{name}"
    if source != expected_source:
        errors.append(f"plugins[{index}].source should be {expected_source}")
    if "path" in plugin:
        errors.append(f"plugins[{index}].path is redundant; use source only")
    if isinstance(source, str):
        if ".." in pathlib.PurePosixPath(source).parts:
            errors.append(f"plugins[{index}].source must not contain '..'")
        source_dir = root / source.removeprefix("./")
        if not source_dir.is_dir():
            errors.append(f"plugins[{index}].source directory is missing: {source}")
        if not (source_dir / ".claude-plugin" / "plugin.json").is_file():
            errors.append(f"plugins[{index}].source missing .claude-plugin/plugin.json: {source}")
        if not (source_dir / "skills" / name / "SKILL.md").is_file():
            errors.append(f"plugins[{index}].source missing skills/{name}/SKILL.md: {source}")

    author = plugin.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"]:
        errors.append(f"plugins[{index}].author.name must be present")

    for field in ("description", "version", "repository", "license"):
        if not isinstance(plugin.get(field), str) or not plugin[field]:
            errors.append(f"plugins[{index}].{field} must be a non-empty string")

    if name in expected:
        manifest_path = expected[name] / ".claude-plugin" / "plugin.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("name") != name:
                errors.append(f"plugins[{index}].name does not match {manifest_path}")
            if manifest.get("version") != plugin.get("version"):
                errors.append(f"plugins[{index}].version does not match {manifest_path}")

for name in sorted(set(expected) - seen):
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
if data.get("sourcePath") != "heyNag/agent-tools":
    errors.append("skillshare hub sourcePath must be heyNag/agent-tools")

skills = data.get("skills")
if not isinstance(skills, list) or not skills:
    errors.append("skillshare hub skills must be a non-empty array")

expected = {}
for tool_path in sorted((root / "packages").glob("*/tool.json")):
    tool = json.loads(tool_path.read_text(encoding="utf-8"))
    targets = tool.get("targets") or []
    if tool.get("public") is True and (tool.get("agent_agnostic") is True or "generic" in targets):
        name = tool.get("name") or tool_path.parent.name
        expected[name] = f"packages/{name}/skills/{name}"

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
        continue

    source = skill.get("source")
    if source != expected[name]:
        errors.append(f"skills[{index}].source should be {expected[name]}")
    if isinstance(source, str) and "generated/" in source:
        errors.append(f"skills[{index}].source must not point at generated output")
    if isinstance(source, str) and not (root / source).is_dir():
        errors.append(f"skills[{index}].source directory is missing: {source}")
    if skill.get("skill") not in (None, "", name):
        errors.append(f"skills[{index}].skill should be omitted or {name}")

for name in sorted(set(expected) - seen):
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

scan_tree() {
  local scan_dir="$1"
  [[ -d "$scan_dir" ]] || return 0

  local hits
  hits="$(
    find "$scan_dir" \
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
        -iname "*.sqlite" -o \
        -iname "*.sqlite3" -o \
        -iname "*.db" -o \
        -iname "*.mp3" -o \
        -iname "*.wav" -o \
        -iname "*.m4a" -o \
        -iname "*.aac" -o \
        -iname "*.mp4" -o \
        -iname "*.mov" -o \
        -iname "*.mkv" -o \
        -iname "*.webm" -o \
        -iname "*.avi" -o \
        -iname "*.flv" -o \
        -iname "*.wmv" \
      \) -print
  )"
  if [[ -n "$hits" ]]; then
    echo "$hits" >&2
    fail "forbidden local artifact found under ${scan_dir#$ROOT/}"
  fi

  if grep -R -I -n -E 'gsk_[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{12,}|OPENAI_API_KEY=[[:space:]]*sk-[A-Za-z0-9_-]{12,}|GROQ_API_KEY=[[:space:]]*gsk_[A-Za-z0-9_-]{12,}' "$scan_dir" >/tmp/agent-tools-secret-scan.$$ 2>/dev/null; then
    cat /tmp/agent-tools-secret-scan.$$ >&2
    rm -f /tmp/agent-tools-secret-scan.$$
    fail "possible secret value found under ${scan_dir#$ROOT/}"
  fi
  rm -f /tmp/agent-tools-secret-scan.$$
}

check_file "$ROOT/.claude-plugin/marketplace.json"
check_file "$ROOT/skillshare-hub.json"
valid_json "$ROOT/.claude-plugin/marketplace.json"
valid_json "$ROOT/skillshare-hub.json"
validate_marketplace
validate_skillshare_hub

shopt -s nullglob
found=0
for tool_json in "$ROOT"/packages/*/tool.json; do
  found=1
  package="$(basename "$(dirname "$tool_json")")"
  package_dir="$ROOT/packages/$package"
  skill_dir="$package_dir/skills/$package"

  valid_json "$tool_json"
  check_file "$package_dir/README.md"
  check_file "$package_dir/SOURCE.md"
  check_file "$skill_dir/SKILL.md"

  if [[ -e "$package_dir/SKILL.md" ]]; then
    fail "legacy root skill file remains: packages/$package/SKILL.md"
  fi
  if [[ -d "$package_dir/scripts" || -d "$package_dir/references" || -d "$package_dir/agents" ]]; then
    fail "legacy package-level bundled skill directory remains under packages/$package"
  fi
  if [[ -d "$package_dir/plugin" ]]; then
    fail "legacy plugin/ directory remains under packages/$package; use .claude-plugin/plugin.json"
  fi

  if [[ "$(json_public "$tool_json")" == "true" && "$(json_has_target "$tool_json" claude)" == "true" ]]; then
    check_file "$package_dir/.claude-plugin/plugin.json"
    valid_json "$package_dir/.claude-plugin/plugin.json"
    validate_plugin_manifest "$package_dir/.claude-plugin/plugin.json"
  fi

  scan_tree "$package_dir"
done
shopt -u nullglob

if [[ "$found" -eq 0 ]]; then
  fail "no package manifests found under packages/*/tool.json"
fi

if [[ -d "$ROOT/generated" ]]; then
  fail "generated/ should not exist in the source-only repo shape"
fi

if command -v claude >/dev/null 2>&1; then
  echo "claude CLI found; validating package plugins"
  for tool_json in "$ROOT"/packages/*/tool.json; do
    package="$(basename "$(dirname "$tool_json")")"
    if [[ "$(json_public "$tool_json")" == "true" && "$(json_has_target "$tool_json" claude)" == "true" ]]; then
      if ! claude plugin validate "$ROOT/packages/$package"; then
        fail "Claude plugin validation failed for packages/$package"
      fi
    fi
  done
else
  echo "claude CLI not found; skipping Claude plugin validation"
fi

echo "package verification passed"
