#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

json_public() {
  python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print("true" if data.get("public") is True else "false")
PY
}

found=0
shopt -s nullglob
for tool_json in "$ROOT"/packages/*/tool.json; do
  found=1
  package="$(basename "$(dirname "$tool_json")")"
  if [[ "$(json_public "$tool_json")" != "true" ]]; then
    echo "skip: $package is not public"
    continue
  fi
  "$ROOT/scripts/build-claude-plugin.sh" "$package"
  "$ROOT/scripts/build-codex-skill.sh" "$package"
  "$ROOT/scripts/build-agent-skill.sh" "$package"
  "$ROOT/scripts/build-claude-custom-skill.sh" "$package"
done

"$ROOT/scripts/build-marketplace.sh"
python3 "$ROOT/scripts/build-skillshare-hub.py" "$ROOT"

if [[ "$found" -eq 0 ]]; then
  echo "no package manifests found under packages/*/tool.json"
fi
