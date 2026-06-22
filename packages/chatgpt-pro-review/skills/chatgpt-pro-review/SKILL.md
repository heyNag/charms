---
name: chatgpt-pro-review
description: Use when the user asks for ChatGPT Pro review, Extended Pro review, external second-pass review, plan hardening, implementation review, PR review, code-review comment resolution, or review of another agent's work.
argument-hint: "[plan|implementation|pr|eval] [context]"
tags: review, chatgpt, pro, planning, code-review
allowed-tools: Read, Grep, Bash
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
---

# ChatGPT Pro Review

Use this skill to prepare a focused context packet for ChatGPT Pro or Extended
Pro, get a second-pass review, and verify the response locally before acting on
it.

## Principles

- Treat ChatGPT Pro as the reviewer, not the builder.
- Treat the current local agent as the reconciler. Do not blindly accept review
  feedback.
- Keep the packet scoped to the decision under review: plan, diff, PR,
  code-review response, test failure, or eval/reporting method.
- Redact secrets, auth tokens, customer data, unrelated private files, and large
  irrelevant context.
- Before submitting private repo context to ChatGPT, confirm the user authorized
  sending that specific context. If approval is unclear, ask first.
- Ask before implementing feedback that changes product behavior, architecture,
  security posture, data handling, or scope.
- If no approved browser or ChatGPT transport is available, prepare a
  copy/paste packet and ask the user to send it manually.

## Transport

Choose the available path:

- If the current agent has an approved browser/control integration and the user
  authorized sending the packet, open or reuse ChatGPT and submit the packet.
- Prefer Extended Pro when the model picker is visible and the user has access.
- If the user provides a ChatGPT thread URL, use that thread only when the
  current task fits its context. Otherwise start a clean thread or ask which
  thread to use.
- If transport is unavailable, show the packet in a fenced block for manual
  paste, then ask the user to paste ChatGPT Pro's response back.

## Workflow

1. Define the review target.
   - Identify whether this is plan hardening, implementation review,
     PR/comment resolution, or eval/reporting methodology.
   - Write the exact decision ChatGPT Pro should review.

2. Gather local context.
   - Include branch, base branch, PR or issue links, changed-file list, diff
     summary, key snippets, plan docs, tests run, known failures, open
     questions, and repo constraints.
   - Prefer summaries plus essential snippets over dumping whole files.
   - Include commands already run and their relevant outcomes.

3. Build the review packet.
   - Use one prompt template from this skill.
   - Include the output contract.
   - Keep the packet self-contained enough for ChatGPT Pro to reason without
     repository access.

4. Send or hand off.
   - If browser transport is available and authorized, submit the packet to
     ChatGPT Pro.
   - If transport is unavailable or not authorized, show the packet for manual
     paste.

5. Reconcile the response.
   - Check every actionable claim against the current repo, diff, tests, PR
     state, and project conventions.
   - Classify each item as `FIX`, `DEFER`, `DISMISS`, or `QUESTION`.
   - Implement `FIX` items only when they are in scope and do not need user
     approval.

6. Report back.
   - Include ChatGPT Pro's verdict.
   - Summarize what was fixed, deferred, dismissed, or left as a question.
   - List local verification commands and results.

## ChatGPT Output Contract

Ask ChatGPT Pro to respond in this shape:

```text
Verdict: SIGNED OFF | BLOCKED

Required changes:
- ...

Risks:
- ...

Tests or verification:
- ...

Reasoning notes:
- ...
```

`SIGNED OFF` means ChatGPT Pro found no blocking issue for the stated decision.
`BLOCKED` means it found at least one required change or unresolved question.

## Prompt Templates

### Plan Hardening

```text
You are ChatGPT Pro reviewing this plan before implementation.

Decision to review:
[exact decision]

Context packet:
[branch, issue/PR links, plan, constraints, risks, open questions]

Use this output contract:
- Verdict: SIGNED OFF or BLOCKED
- Required changes
- Risks
- Tests or verification
- Reasoning notes

Focus on missing decisions, weak assumptions, sequencing risk, and whether the
plan reaches the stated workflow goal.
```

### Implementation Review

```text
You are ChatGPT Pro reviewing this implementation for ship readiness.

Decision to review:
[exact decision]

Context packet:
[branch, diff summary, changed files, key snippets, tests run, known failures,
repo patterns]

Use this output contract:
- Verdict: SIGNED OFF or BLOCKED
- Required changes
- Risks
- Tests or verification
- Reasoning notes

Focus on correctness, edge cases, regressions, missing tests, and whether the
diff is shippable for the stated scope.
```

### PR Or Review Comment Resolution

```text
You are ChatGPT Pro reviewing whether PR or code-review comments were resolved
correctly.

Decision to review:
[exact decision]

Context packet:
[PR URL, branch, review comments, responses, fixes, relevant diffs, tests run,
unresolved questions]

Use this output contract:
- Verdict: SIGNED OFF or BLOCKED
- Required changes
- Risks
- Tests or verification
- Reasoning notes

Focus on whether any response or fix is incomplete, inconsistent with the repo,
or likely to fail review.
```

### Eval Or Reporting Methodology

```text
You are ChatGPT Pro reviewing this evaluation or reporting methodology.

Decision to review:
[exact decision]

Context packet:
[metrics, datasets/reports, method, assumptions, comparison criteria, known
limitations, relevant code or queries]

Use this output contract:
- Verdict: SIGNED OFF or BLOCKED
- Required changes
- Risks
- Tests or verification
- Reasoning notes

Focus on comparability, confounders, missing evidence, and whether the
recommendation follows from the reported data.
```

## Reconciliation Report

Report back in this shape:

```text
ChatGPT Pro verdict: SIGNED OFF | BLOCKED

Reconciled actions:
- FIX: ...
- DEFER: ...
- DISMISS: ...
- QUESTION: ...

Local verification:
- ...

Traceability:
- Prompt summary: ...
- Response summary: ...
```
