# Source Package

This directory is the source of truth and Claude Code plugin root for
`codex-reset-credit`.

Edit files here first:

- `skills/codex-reset-credit/SKILL.md`
- `skills/codex-reset-credit/scripts/`
- `commands/`
- `.claude-plugin/plugin.json`
- `README.md`
- `SOURCE.md`
- `tests/`
- `tool.json`

After changing package source, run:

```sh
make build-packages
make public-check
```

Install targets consume source directly:

```text
Claude Code marketplace source  -> packages/codex-reset-credit
Codex skill source              -> packages/codex-reset-credit/skills/codex-reset-credit
OpenCode/generic skill source   -> packages/codex-reset-credit/skills/codex-reset-credit
Skillshare hub source           -> packages/codex-reset-credit/skills/codex-reset-credit
Claude Desktop local artifact   -> .dist/claude/custom-skills/codex-reset-credit
```

`.dist/` artifacts are local build outputs and must not be committed.
