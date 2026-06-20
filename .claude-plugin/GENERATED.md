# Generated Claude Code Marketplace Catalog

This directory contains generated Claude Code marketplace metadata.

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated output on the right is
rewritten by `make rebuild-generated`.

```text
packages/*/tool.json and packages/*/plugin/plugin.json -> .claude-plugin/marketplace.json
```

After editing source:

1. Edit package manifests under `packages/`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
