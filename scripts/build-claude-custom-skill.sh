#!/usr/bin/env bash
set -euo pipefail

PACKAGE="${1:-watch-video}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/packages/$PACKAGE"
TOOL_JSON="$SRC/tool.json"
SKILL_SRC="$SRC/skills/$PACKAGE"
OUT="$ROOT/.dist/claude/custom-skills/$PACKAGE"

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

prune_artifact() {
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
      -name ".dist" -o \
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
      -iname "*.avi" -o \
      -iname "*.flv" -o \
      -iname "*.wmv" \
    \) -type f -delete
}

copy_optional_dir() {
  local name="$1"
  if [[ -d "$SKILL_SRC/$name" ]]; then
    mkdir -p "$OUT/$name"
    cp -R "$SKILL_SRC/$name"/. "$OUT/$name"/
  fi
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

[[ -f "$SKILL_SRC/SKILL.md" ]] || fail "missing required file: $SKILL_SRC/SKILL.md"
[[ -f "$SRC/README.md" ]] || fail "missing required file: $SRC/README.md"
[[ -f "$ROOT/LICENSE" ]] || fail "missing required file: $ROOT/LICENSE"

rm -rf "$OUT"
mkdir -p "$OUT"

cp "$SKILL_SRC/SKILL.md" "$OUT/skill.md"
copy_optional_dir scripts
copy_optional_dir references
copy_optional_dir agents
cp "$SRC/README.md" "$OUT/README.md"
cp "$ROOT/LICENSE" "$OUT/LICENSE"

cat > "$OUT/ARTIFACT.md" <<EOF
# Claude Custom Skill Artifact

This local artifact was built from:

\`\`\`text
packages/$PACKAGE/skills/$PACKAGE
packages/$PACKAGE/README.md
LICENSE
\`\`\`

It is written under \`.dist/\` and is not committed. Zip the \`$PACKAGE/\`
folder for Claude Desktop or claude.ai custom skill upload.
EOF

prune_artifact "$OUT"

echo "built Claude custom skill artifact: .dist/claude/custom-skills/$PACKAGE"
