# Source Package

This directory is the source of truth and Claude Code plugin root for
`watch-video`.

Edit files here first:

- `skills/watch-video/SKILL.md`
- `skills/watch-video/scripts/`
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
Claude Code marketplace source  -> packages/watch-video
Codex skill source              -> packages/watch-video/skills/watch-video
OpenCode/generic skill source   -> packages/watch-video/skills/watch-video
Skillshare hub source           -> packages/watch-video/skills/watch-video
Claude Desktop local artifact   -> .dist/claude/custom-skills/watch-video
```

`.dist/` artifacts are local build outputs and must not be committed.
