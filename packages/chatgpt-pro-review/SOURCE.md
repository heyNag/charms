# Source Package

This directory is the source of truth and Claude Code plugin root for
`chatgpt-pro-review`.

Edit source here:

```text
packages/chatgpt-pro-review
packages/chatgpt-pro-review/skills/chatgpt-pro-review
packages/chatgpt-pro-review/commands
```

Do not edit root `skills/` or `commands/` symlink indexes as source. Rebuild
them from this package:

```sh
make build-packages
make public-check
```

Target mapping:

```text
Claude Code marketplace source  -> packages/chatgpt-pro-review
Codex skill source              -> packages/chatgpt-pro-review/skills/chatgpt-pro-review
Cursor root skill index         -> skills/chatgpt-pro-review
OpenCode/generic skill source   -> packages/chatgpt-pro-review/skills/chatgpt-pro-review
Skillshare hub source           -> packages/chatgpt-pro-review/skills/chatgpt-pro-review
```
