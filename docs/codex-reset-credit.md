# codex-reset-credit

`codex-reset-credit` checks Codex reset credits and local Codex rate-limit reset
windows without exposing auth secrets or modifying local Codex state.

Source paths:

```text
packages/codex-reset-credit
packages/codex-reset-credit/skills/codex-reset-credit
```

## Install Paths

- Claude Code: `/plugin install codex-reset-credit@agent-tools`
- Codex: copy `packages/codex-reset-credit/skills/codex-reset-credit`
- OpenCode: copy `packages/codex-reset-credit/skills/codex-reset-credit`
- Claude Desktop: build `.dist/claude/custom-skills/codex-reset-credit`
- Skillshare: install
  `heyNag/agent-tools/packages/codex-reset-credit/skills/codex-reset-credit`

## Usage

```sh
python3 packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py --no-live
python3 packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py --json
python3 packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py --thread-id <thread-id>
```

## Safety Rules

- Read-only.
- Never print access tokens, refresh tokens, account IDs, raw auth contents, or
  unredacted auth paths.
- Use `--no-live` when only local session snapshots are needed.

## Evidence Boundary

- Reset-credit data comes from the live Codex/ChatGPT backend endpoint.
- Rate-limit windows come from local Codex session `token_count` events.
- Local session snapshots may be stale.
