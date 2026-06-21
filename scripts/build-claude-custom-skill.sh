#!/usr/bin/env bash
set -euo pipefail

PACKAGE="${1:-watch-video}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/packages/$PACKAGE"
TOOL_JSON="$SRC/tool.json"
OUT="$ROOT/generated/claude/custom-skills/$PACKAGE"

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
      -name ".x-bookmarks" -o \
      -name ".codex" -o \
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
      -name "auth.json" -o \
      -name "metadata.json" -o \
      -name "transcript.json" -o \
      -name "transcript.md" -o \
      -name "report.md" -o \
      -name "groq_transcript.raw.json" -o \
      -name "tokens.json" -o \
      -name "state.json" -o \
      -name "bookmarks.json" -o \
      -name "bookmarks.jsonl" -o \
      -name "bookmarks.ndjson" -o \
      -name "search-index.json" -o \
      -iname "*.sqlite" -o \
      -iname "*.sqlite3" -o \
      -iname "*.db" -o \
      -iname "rollout-*.jsonl" -o \
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
    \) -type f -delete
}

[[ -f "$TOOL_JSON" ]] || fail "missing package manifest: $TOOL_JSON"
[[ "$(json_public)" == "true" ]] || {
  echo "skip: $PACKAGE is not public"
  exit 0
}
[[ "$(json_has_target generic)" == "true" ]] || {
  echo "skip: $PACKAGE does not target generic"
  exit 0
}

[[ -f "$SRC/SKILL.md" ]] || fail "missing required file: $SRC/SKILL.md"
[[ -f "$SRC/README.md" ]] || fail "missing required file: $SRC/README.md"
[[ -f "$ROOT/LICENSE" ]] || fail "missing required file: $ROOT/LICENSE"

rm -rf "$OUT"
mkdir -p "$OUT"

cp "$SRC/SKILL.md" "$OUT/skill.md"

if [[ -d "$SRC/scripts" ]]; then
  copy_dir "$SRC/scripts" "$OUT/scripts"
fi

if [[ -d "$SRC/references" ]]; then
  copy_dir "$SRC/references" "$OUT/references"
fi

if [[ -d "$SRC/agents" ]]; then
  copy_dir "$SRC/agents" "$OUT/agents"
fi

cp "$SRC/README.md" "$OUT/README.md"
cp "$ROOT/LICENSE" "$OUT/LICENSE"
map_lines="packages/$PACKAGE/SKILL.md       -> generated/claude/custom-skills/$PACKAGE/skill.md"$'\n'
if [[ -d "$SRC/scripts" ]]; then
  map_lines+="packages/$PACKAGE/scripts/       -> generated/claude/custom-skills/$PACKAGE/scripts/"$'\n'
fi
if [[ -d "$SRC/references" ]]; then
  map_lines+="packages/$PACKAGE/references/    -> generated/claude/custom-skills/$PACKAGE/references/"$'\n'
fi
if [[ -d "$SRC/agents" ]]; then
  map_lines+="packages/$PACKAGE/agents/        -> generated/claude/custom-skills/$PACKAGE/agents/"$'\n'
fi
cat > "$OUT/GENERATED.md" <<EOF
# Generated Claude Custom Skill Package

This directory is generated from:

\`\`\`text
packages/$PACKAGE
\`\`\`

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by \`make rebuild-generated\`.

~~~text
packages/$PACKAGE/README.md      -> generated/claude/custom-skills/$PACKAGE/README.md
${map_lines}
LICENSE                          -> generated/claude/custom-skills/$PACKAGE/LICENSE
~~~

This bundle is for Claude Desktop / claude.ai custom skill upload. Create the
ZIP from \`generated/claude/custom-skills\` so the archive contains the
\`$PACKAGE/\` folder at its root.

After editing source:

1. Edit \`packages/$PACKAGE\`.
2. Run \`make rebuild-generated\`.
3. Run \`make verify-generated-clean\`.
4. Commit both source and regenerated output changes.
EOF
prune_generated "$OUT"
header_args=(
  --root "$ROOT" \
  --map "generated/claude/custom-skills/$PACKAGE/README.md=packages/$PACKAGE/README.md" \
  --map "generated/claude/custom-skills/$PACKAGE/skill.md=packages/$PACKAGE/SKILL.md"
)
if [[ -d "$SRC/scripts" ]]; then
  header_args+=(--map "generated/claude/custom-skills/$PACKAGE/scripts=packages/$PACKAGE/scripts")
fi
if [[ -d "$SRC/references" ]]; then
  header_args+=(--map "generated/claude/custom-skills/$PACKAGE/references=packages/$PACKAGE/references")
fi
if [[ -d "$SRC/agents" ]]; then
  header_args+=(--map "generated/claude/custom-skills/$PACKAGE/agents=packages/$PACKAGE/agents")
fi
python3 "$ROOT/scripts/add-generated-headers.py" "${header_args[@]}"

echo "built Claude custom skill: generated/claude/custom-skills/$PACKAGE"
