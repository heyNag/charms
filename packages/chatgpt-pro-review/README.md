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

## Source

```text
packages/chatgpt-pro-review/skills/chatgpt-pro-review
```

The package root `packages/chatgpt-pro-review` is also the Claude Code plugin
root.

## Install Targets

- Claude Code: `/plugin install chatgpt-pro-review@agent-tools`
- Codex: copy `packages/chatgpt-pro-review/skills/chatgpt-pro-review`
- Cursor: root `skills/chatgpt-pro-review` symlink through `.cursor-plugin/plugin.json`
- OpenCode: root plugin wrapper or copy `packages/chatgpt-pro-review/skills/chatgpt-pro-review`
- Claude Desktop: build `.dist/claude/custom-skills/chatgpt-pro-review`
- Skillshare: install `heyNag/agent-tools/packages/chatgpt-pro-review/skills/chatgpt-pro-review`

## Privacy

Do not send private repo context, secrets, auth tokens, customer data, or
sensitive unpublished code to ChatGPT unless the user explicitly approves that
specific context. When in doubt, prepare a paste packet and ask the user before
submitting it.

## Local Development

```sh
make build-packages
make public-check
```
