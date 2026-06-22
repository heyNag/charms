# chatgpt-pro-review

`chatgpt-pro-review` helps an agent prepare a scoped packet for ChatGPT Pro or
Extended Pro review, then reconcile the response against local files, diffs,
tests, pull request state, and repo conventions.

Use it for:

- plan hardening
- implementation review
- PR or code-review comment resolution
- eval or reporting methodology review
- external second-pass review of another agent's work

The package root is a Claude Code plugin source. The portable skill source is:

```text
packages/chatgpt-pro-review/skills/chatgpt-pro-review
```

Codex, Cursor, OpenCode, generic Agent Skills, and optional Skillshare installs
all use that same skill folder directly or through the root `skills/` symlink
index. Claude Desktop custom-skill ZIP contents are built locally under
`.dist/claude/custom-skills/chatgpt-pro-review`.

Install commands for each target live in
[docs/installing-skills.md](../../docs/installing-skills.md).

## Privacy

Do not send private repo context, secrets, auth tokens, customer data, or
sensitive unpublished code to ChatGPT unless the user explicitly approves that
specific context. When in doubt, prepare a paste packet and ask the user before
submitting it.

## Package Files

```text
.claude-plugin/plugin.json                       Claude Code plugin metadata
skills/chatgpt-pro-review/SKILL.md               skill instructions
skills/chatgpt-pro-review/agents/                display metadata for agent UIs
commands/chatgpt-pro-review.md                   Claude Code slash command prompt
tests/                                           offline tests
tool.json                                        package manifest
```

After editing source:

```sh
make build-packages
make public-check
```
