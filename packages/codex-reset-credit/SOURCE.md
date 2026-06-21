# Source Package

This directory is the source of truth for `codex-reset-credit`.

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
make verify-generated-clean
```

This source directory generates these public install copies:

```text
packages/codex-reset-credit -> generated/claude/plugins/codex-reset-credit
packages/codex-reset-credit -> generated/claude/custom-skills/codex-reset-credit
packages/codex-reset-credit -> generated/codex/skills/codex-reset-credit
packages/codex-reset-credit -> generated/agent-skills/codex-reset-credit
```

Generated Markdown and Python files include in-file notices that point back to
the source paths in this package. Generated JSON and LICENSE files are covered
by the nearest `GENERATED.md` marker because those file formats should not carry
extra comments.
