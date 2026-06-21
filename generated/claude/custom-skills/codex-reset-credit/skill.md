---
name: codex-reset-credit
description: Check Codex reset-credit status and local Codex rate-limit reset windows without exposing auth secrets or modifying local Codex state.
argument-hint: "[--json] [--no-live] [--thread-id THREAD]"
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---
<!-- BEGIN GENERATED FROM SOURCE: packages/codex-reset-credit/SKILL.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->


# codex-reset-credit

Use this skill only when a user explicitly asks about Codex reset credits,
available reset credits, reset-credit expiry, Codex quota usage, local
rate-limit windows, or when Codex limits reset.

This skill is read-only. It must not redeem credits, consume credits, modify
Codex Desktop, edit auth/session files, or change usage-limit state.

## Operating Rules

- Run the helper script from this skill directory.
- Never print access tokens, refresh tokens, account IDs, credit IDs, email
  addresses, profile image URLs, or raw auth file contents.
- Do not show auth file paths. If a local file path is needed for debugging,
  ask first and prefer redacted paths.
- Prefer the direct answer first: available reset credits, next reset-credit
  expiry, and local rate-limit reset windows.
- State the evidence boundary:
  - reset credits come from the live Codex/ChatGPT backend endpoint
  - rate-limit windows come from local Codex session `token_count` snapshots
  - local snapshots can be stale if Codex has not emitted recent token-count
    events
- If auth/session state is missing or the endpoint fails, report the plain
  safe error and any local-only rate-limit data that was still available.

## Invocation

From this skill directory:

```sh
python3 scripts/check_reset_credits.py
```

Useful options:

```sh
python3 scripts/check_reset_credits.py --json
python3 scripts/check_reset_credits.py --no-live
python3 scripts/check_reset_credits.py --thread-id <thread-id>
python3 scripts/check_reset_credits.py --session-file <absolute-path-to-rollout.jsonl>
python3 scripts/check_reset_credits.py --timezone America/Los_Angeles
```

Use `--no-live` when the user only wants local rate-limit reset windows or when
network/backend access is not appropriate. Use `--json` when another tool or
agent needs structured sanitized output.

## Response Shape

Unless the user asks for raw JSON, return:

1. Reset credits available
2. Next credit expiry, if known
3. Primary rate-limit reset window
4. Secondary rate-limit reset window, if present
5. Evidence boundary and any staleness warning
6. Safe error details, if any

Keep the answer short. Do not paste full JSON unless requested.

## Failure Handling

- Missing Codex auth: say local Codex auth was not found or not usable.
- Endpoint error: say the live reset-credit endpoint failed and include the
  safe HTTP/network category.
- Missing session snapshots: say no local Codex rate-limit snapshots were found.
- In all cases, do not reveal tokens, account IDs, auth file contents, or raw
  local auth paths.

## Source Note

This package was ported from Nag's local dotfiles skill. Keep future edits in
this repo under `packages/codex-reset-credit`, then run
`make rebuild-generated`.
