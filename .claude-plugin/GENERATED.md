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
