---
description: Check Codex reset credits and local rate-limit reset windows.
argument-hint: "[--json] [--no-live] [--thread-id THREAD]"
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: codex-reset-credit command -->

Use the `codex-reset-credit` skill with the user's arguments: $ARGUMENTS

Run `scripts/check_reset_credits.py` from the installed skill, or
`packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py`
when working from this repository.

Default to the concise text report. Use `--json` only when structured output is
requested. Use `--no-live` when the user only wants local rate-limit windows or
when live endpoint access is not appropriate.

Return the direct answer first: available reset credits, next expiry, primary
and secondary reset windows, then the evidence boundary. Never print access
tokens, refresh tokens, account IDs, raw auth file contents, credit IDs, email
addresses, profile image URLs, or unredacted auth paths.
