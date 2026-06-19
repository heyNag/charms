#!/usr/bin/env bash
set -euo pipefail

PACKAGE="${1:-watch-video}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/packages/$PACKAGE"
TOOL_JSON="$SRC/tool.json"
OUT="$ROOT/plugins/$PACKAGE"

fail() {
  echo "error: $*" >&2
  exit 1
}

case "$PACKAGE" in
  ""|*[!A-Za-z0-9._-]*)
    fail "invalid package name: $PACKAGE"
    ;;
esac

json_public() {
  python3 - "$TOOL_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print("true" if data.get("public") is True else "false")
PY
}

json_has_target() {
  python3 - "$TOOL_JSON" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
targets = data.get("targets") or []
print("true" if sys.argv[2] in targets else "false")
PY
}

copy_dir() {
  local source_dir="$1"
  local dest_dir="$2"
  mkdir -p "$dest_dir"
  cp -R "$source_dir"/. "$dest_dir"/
  prune_generated "$dest_dir"
}

prune_generated() {
  local dest_dir="$1"
  find "$dest_dir" \
    \( \
      -name ".env" -o \
      -name ".env.local" -o \
      -name ".watch-video" -o \
      -name ".watch-video" -o \
      -name "__pycache__" -o \
      -name ".pytest_cache" -o \
      -name ".mypy_cache" -o \
      -name ".ruff_cache" -o \
      -name ".venv" -o \
      -name "node_modules" -o \
      -name "dist" -o \
      -name "frames" \
    \) -prune -exec rm -rf {} +
  find "$dest_dir" -name ".DS_Store" -delete
  find "$dest_dir" \
    \( \
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
    \) -type f -delete
}

write_default_plugin_json() {
  python3 - "$TOOL_JSON" "$OUT/.claude-plugin/plugin.json" "$PACKAGE" <<'PY'
import json
import sys

tool_path, out_path, package = sys.argv[1:]
with open(tool_path, encoding="utf-8") as handle:
    tool = json.load(handle)

manifest = {
    "name": tool.get("name") or package,
    "version": "0.1.0",
    "description": tool.get("description") or f"{package} Claude Code plugin.",
    "author": {"name": "Nagarjuna Boddu"},
    "repository": "https://github.com/heyNag/agent-tools",
    "license": "MIT",
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2)
    handle.write("\n")
PY
}

[[ -f "$TOOL_JSON" ]] || fail "missing package manifest: $TOOL_JSON"
[[ "$(json_public)" == "true" ]] || {
  echo "skip: $PACKAGE is not public"
  exit 0
}
[[ "$(json_has_target claude)" == "true" ]] || {
  echo "skip: $PACKAGE does not target claude"
  exit 0
}

[[ -f "$SRC/SKILL.md" ]] || fail "missing required file: $SRC/SKILL.md"
[[ -f "$SRC/README.md" ]] || fail "missing required file: $SRC/README.md"
[[ -f "$ROOT/LICENSE" ]] || fail "missing required file: $ROOT/LICENSE"

rm -rf "$OUT"
mkdir -p "$OUT/.claude-plugin" "$OUT/skills/$PACKAGE"

cp "$SRC/SKILL.md" "$OUT/skills/$PACKAGE/SKILL.md"

if [[ -d "$SRC/scripts" ]]; then
  copy_dir "$SRC/scripts" "$OUT/skills/$PACKAGE/scripts"
fi

if [[ -d "$SRC/commands" ]]; then
  copy_dir "$SRC/commands" "$OUT/commands"
fi

if [[ -f "$SRC/plugin/plugin.json" ]]; then
  cp "$SRC/plugin/plugin.json" "$OUT/.claude-plugin/plugin.json"
else
  write_default_plugin_json
fi
cp "$SRC/README.md" "$OUT/README.md"
cp "$ROOT/LICENSE" "$OUT/LICENSE"
prune_generated "$OUT"

echo "built Claude plugin: plugins/$PACKAGE"
