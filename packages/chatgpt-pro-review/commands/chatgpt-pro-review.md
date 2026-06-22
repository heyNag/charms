---
description: Prepare a ChatGPT Pro review packet and reconcile the feedback.
argument-hint: "[plan|implementation|pr|eval] [context]"
allowed-tools: [Bash, Read, Grep]
---

<!-- agent-tools-managed: chatgpt-pro-review command -->

Use the `chatgpt-pro-review` skill with the user's arguments: $ARGUMENTS

Prepare a scoped review packet for ChatGPT Pro or Extended Pro, then reconcile
the response against current local files, diffs, tests, PR state, and repo
conventions.

Before submitting private repo context to ChatGPT, confirm the user authorized
sending that specific context. If browser transport is unavailable or approval
is unclear, produce a paste-ready packet instead.

Never include secrets, auth tokens, customer data, unrelated private files, or
large irrelevant context. Do not blindly accept ChatGPT feedback; classify each
actionable item as `FIX`, `DEFER`, `DISMISS`, or `QUESTION`.
