#!/usr/bin/env bash
set -euo pipefail

PACKAGE="${1:-watch-video}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/packages/$PACKAGE"
TOOL_JSON="$SRC/tool.json"
OUT="$ROOT/codex/$PACKAGE"

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
[[ "$(json_has_target codex)" == "true" ]] || {
  echo "skip: $PACKAGE does not target codex"
  exit 0
}

[[ -f "$SRC/SKILL.md" ]] || fail "missing required file: $SRC/SKILL.md"
[[ -f "$SRC/README.md" ]] || fail "missing required file: $SRC/README.md"
[[ -f "$ROOT/LICENSE" ]] || fail "missing required file: $ROOT/LICENSE"

rm -rf "$OUT"
mkdir -p "$OUT"

cp "$SRC/SKILL.md" "$OUT/SKILL.md"

if [[ -d "$SRC/scripts" ]]; then
  copy_dir "$SRC/scripts" "$OUT/scripts"
fi

cp "$SRC/README.md" "$OUT/README.md"
cp "$ROOT/LICENSE" "$OUT/LICENSE"
cat > "$OUT/GENERATED.md" <<EOF
# Generated Codex Skill Package

This directory is generated from:

\`\`\`text
packages/$PACKAGE
\`\`\`

Do not edit this directory directly during normal development.

Edit these source paths instead:

~~~text
codex/$PACKAGE/README.md      <- packages/$PACKAGE/README.md
codex/$PACKAGE/SKILL.md       <- packages/$PACKAGE/SKILL.md
codex/$PACKAGE/scripts/       <- packages/$PACKAGE/scripts/
codex/$PACKAGE/LICENSE        <- LICENSE
~~~

After editing source:

1. Edit \`packages/$PACKAGE\`.
2. Run \`make build-packages\`.
3. Run \`make verify-generated-clean\`.
4. Commit both source and regenerated output changes.
EOF
prune_generated "$OUT"
python3 "$ROOT/scripts/add-generated-headers.py" \
  --root "$ROOT" \
  --map "codex/$PACKAGE/README.md=packages/$PACKAGE/README.md" \
  --map "codex/$PACKAGE/SKILL.md=packages/$PACKAGE/SKILL.md" \
  --map "codex/$PACKAGE/scripts=packages/$PACKAGE/scripts"

echo "built Codex skill: codex/$PACKAGE"
