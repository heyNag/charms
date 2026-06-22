# Source Package

This directory is the source of truth and Claude Code plugin root for
`x-bookmarks`.

Edit files here first:

- `skills/x-bookmarks/SKILL.md`
- `skills/x-bookmarks/scripts/`
- `skills/x-bookmarks/references/`
- `skills/x-bookmarks/agents/`
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
Claude Code marketplace source  -> packages/x-bookmarks
Codex skill source              -> packages/x-bookmarks/skills/x-bookmarks
OpenCode/generic skill source   -> packages/x-bookmarks/skills/x-bookmarks
Skillshare hub source           -> packages/x-bookmarks/skills/x-bookmarks
Claude Desktop local artifact   -> .dist/claude/custom-skills/x-bookmarks
```

`.dist/` artifacts are local build outputs and must not be committed.
