# chatgpt-pro-review

`chatgpt-pro-review` prepares scoped review packets for ChatGPT Pro or Extended
Pro, then helps the current agent reconcile the response against local evidence.

Use it when you want:

- plan hardening
- implementation review
- PR or code-review comment resolution
- eval or reporting methodology review
- external second-pass review of another agent's work

## Source Paths

```text
packages/chatgpt-pro-review
packages/chatgpt-pro-review/skills/chatgpt-pro-review
```

## Install Targets

- Claude Code: `/plugin install chatgpt-pro-review@agent-tools`
- Codex: copy `packages/chatgpt-pro-review/skills/chatgpt-pro-review`
- Cursor: root `skills/chatgpt-pro-review` symlink through `.cursor-plugin/plugin.json`
- OpenCode: root plugin wrapper or copy `packages/chatgpt-pro-review/skills/chatgpt-pro-review`
- Claude Desktop: build `.dist/claude/custom-skills/chatgpt-pro-review`
- Skillshare: install `heyNag/agent-tools/packages/chatgpt-pro-review/skills/chatgpt-pro-review`

## Privacy Model

This skill can prepare a packet without submitting it anywhere. Before sending
private repo context to ChatGPT, the agent should confirm that the user
authorized sending that specific context.

Never include:

- API keys, auth tokens, cookies, or raw credential files
- customer data or private third-party data
- unrelated private files
- large irrelevant context dumps

## Expected Flow

1. Identify the decision under review.
2. Gather the smallest useful local context packet.
3. Ask ChatGPT Pro for a structured verdict.
4. Reconcile every claim against local files, diffs, tests, and conventions.
5. Classify outcomes as `FIX`, `DEFER`, `DISMISS`, or `QUESTION`.

The skill is reviewer-oriented. It should not blindly apply external feedback.

## Local Development

```sh
make build-packages
make public-check
```
