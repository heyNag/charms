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

    source = plugin.get("source")
    if not isinstance(source, str) or not source.startswith("./"):
        errors.append(f"plugins[{index}].source must be a relative ./ path")
    if "path" in plugin:
        errors.append(f"plugins[{index}].path is redundant; use source only")

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
        -iname "frame_*.jpg" -o \
        -iname "frame_*.jpeg" -o \
        -iname "frame_*.png" -o \
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
    fail "generated package contains forbidden files under ${output_dir#$ROOT/}"
  fi
}

check_file "$ROOT/.claude-plugin/marketplace.json"
valid_json "$ROOT/.claude-plugin/marketplace.json"
validate_marketplace

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
    plugin_dir="$ROOT/plugins/$package"
    check_file "$plugin_dir/.claude-plugin/plugin.json"
    check_file "$plugin_dir/skills/$package/SKILL.md"
    check_file "$plugin_dir/README.md"
    check_file "$plugin_dir/LICENSE"
    valid_json "$plugin_dir/.claude-plugin/plugin.json"
    validate_plugin_manifest "$plugin_dir/.claude-plugin/plugin.json"

    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$plugin_dir/skills/$package/scripts"
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
    codex_dir="$ROOT/codex/$package"
    check_file "$codex_dir/SKILL.md"
    check_file "$codex_dir/README.md"
    check_file "$codex_dir/LICENSE"
    if [[ -d "$package_dir/scripts" ]]; then
      check_dir "$codex_dir/scripts"
    fi
    scan_output "$codex_dir"
  fi
done

[[ "$found" -eq 1 ]] || fail "no package manifests found under packages/*/tool.json"

echo "package verification passed"
