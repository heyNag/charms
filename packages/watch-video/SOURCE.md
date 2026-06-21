# Source Package

This directory is the source of truth for `watch-video`.

Edit files here first:

- `SKILL.md`
- `README.md`
- `commands/`
- `plugin/plugin.json`
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
packages/watch-video -> generated/claude/plugins/watch-video
packages/watch-video -> generated/claude/custom-skills/watch-video
packages/watch-video -> generated/codex/skills/watch-video
packages/watch-video -> generated/agent-skills/watch-video
```

Generated Markdown, Python, shell, and YAML files include in-file notices that
point back to the source paths in this package. Generated JSON and LICENSE files
are covered by the nearest `GENERATED.md` marker because those file formats
should not carry extra comments.
