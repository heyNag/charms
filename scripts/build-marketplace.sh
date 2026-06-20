#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/.claude-plugin/marketplace.json"
MARKER="$ROOT/.claude-plugin/GENERATED.md"

mkdir -p "$(dirname "$OUT")"

python3 - "$ROOT" "$OUT" <<'PY'
import json
import pathlib
import sys


ROOT = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
DEFAULT_AUTHOR = {"name": "Nagarjuna Boddu"}
DEFAULT_REPOSITORY = "https://github.com/heyNag/agent-tools"
DEFAULT_LICENSE = "MIT"
DEFAULT_VERSION = "0.1.0"


def load_json(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"error: expected JSON object in {path}")
    return data


def normalize_author(value: object) -> dict:
    if isinstance(value, dict) and isinstance(value.get("name"), str) and value["name"]:
        return {"name": value["name"]}
    if isinstance(value, str) and value:
        return {"name": value}
    return dict(DEFAULT_AUTHOR)


plugins = []
for tool_path in sorted((ROOT / "packages").glob("*/tool.json")):
    package_dir = tool_path.parent
    tool = load_json(tool_path)
    targets = tool.get("targets") or []
    if tool.get("public") is not True or "claude" not in targets:
        continue

    name = tool.get("name") or package_dir.name
    plugin_path = package_dir / "plugin" / "plugin.json"
    plugin = load_json(plugin_path) if plugin_path.exists() else {}

    plugins.append(
        {
            "name": name,
            "source": f"./plugins/{name}",
            "description": plugin.get("description")
            or tool.get("description")
            or f"{name} Claude Code plugin.",
            "version": plugin.get("version") or DEFAULT_VERSION,
            "author": normalize_author(plugin.get("author")),
            "repository": plugin.get("repository") or DEFAULT_REPOSITORY,
            "license": plugin.get("license") or DEFAULT_LICENSE,
        }
    )

marketplace = {
    "name": "agent-tools",
    "description": "Claude Code plugins from agent-tools.",
    "owner": DEFAULT_AUTHOR,
    "plugins": plugins,
}

OUT.write_text(json.dumps(marketplace, indent=2) + "\n", encoding="utf-8")
PY

echo "built Claude marketplace: .claude-plugin/marketplace.json"

cat > "$MARKER" <<'EOF'
# Generated Claude Code Marketplace Catalog

This directory contains generated Claude Code marketplace metadata.

Do not edit this directory directly during normal development.

Edit these source paths instead:

```text
.claude-plugin/marketplace.json <- packages/*/tool.json and packages/*/plugin/plugin.json
```

After editing source:

1. Edit package manifests under `packages/`.
2. Run `make build-packages`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
EOF
