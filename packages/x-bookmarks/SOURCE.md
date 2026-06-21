# Source Package

This directory is the source of truth for `x-bookmarks`.

Edit files here first:

- `SKILL.md`
- `README.md`
- `agents/`
- `commands/`
- `plugin/plugin.json`
- `references/`
- `scripts/`
- `tests/`
- `tool.json`

After changing package source, run:

```sh
make rebuild-generated
make verify-packages
make audit-generated
make verify-generated-clean
```

This source directory generates these public install copies:

```text
packages/x-bookmarks -> generated/claude/plugins/x-bookmarks
packages/x-bookmarks -> generated/claude/custom-skills/x-bookmarks
packages/x-bookmarks -> generated/codex/skills/x-bookmarks
packages/x-bookmarks -> generated/agent-skills/x-bookmarks
```

Generated Markdown, Python, shell, and YAML files include in-file notices that
point back to the source paths in this package. Generated JSON and LICENSE files
are covered by the nearest `GENERATED.md` marker because those file formats
should not carry extra comments.
