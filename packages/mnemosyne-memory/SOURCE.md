# Source Package

This directory is the source of truth and Claude Code plugin root for
`mnemosyne-memory`.

Edit files here first:

- `skills/mnemosyne-memory/SKILL.md`
- `skills/mnemosyne-memory/agents/`
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
Claude Code marketplace source  -> packages/mnemosyne-memory
Codex skill source              -> packages/mnemosyne-memory/skills/mnemosyne-memory
Cursor plugin source            -> skills/mnemosyne-memory symlink
OpenCode/generic skill source   -> packages/mnemosyne-memory/skills/mnemosyne-memory
Skillshare hub source           -> packages/mnemosyne-memory/skills/mnemosyne-memory
Claude Desktop local artifact   -> .dist/claude/custom-skills/mnemosyne-memory
```

`.dist/` artifacts are local build outputs and must not be committed.
