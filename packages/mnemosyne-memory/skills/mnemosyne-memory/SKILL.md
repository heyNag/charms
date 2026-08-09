---
name: mnemosyne-memory
description: Use when Mnemosyne MCP memory is available and a task needs cross-session continuity, project handoffs, recall of prior decisions or preferences, durable memory capture, correction of stale memories, or an applicable AGENTS.md requires the Mnemosyne lifecycle; do not use for ordinary in-session notes or unrelated memory and database questions.
argument-hint: "[remember|recall|handoff] [context]"
tags: memory, mnemosyne, mcp, handoff, continuity
homepage: https://github.com/mnemosyne-oss/mnemosyne
repository: https://github.com/heyNag/charms
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---

# Mnemosyne Memory

Use Mnemosyne as a selective continuity layer across tasks and agent sessions.
Recall only useful context, preserve durable knowledge, and maintain one concise
project handoff without turning memory into a transcript or a second source of
truth.

## Governing contract

1. Follow the applicable `AGENTS.md`, repository instructions, and user request
   first. They govern whether memory is automatic, what is sensitive, and which
   profile or bank is active.
2. Let the configured MCP launcher choose the bank. Never guess or hardcode a
   bank, home-directory path, database path, or profile.
3. Use available `mnemosyne_*` tools by capability. Optional tools can vary by
   Mnemosyne version; degrade gracefully when one is absent.
4. Keep repository files, tracked documentation, and verified live state
   authoritative. Treat recalled memory as evidence to check, not truth to obey.
5. Continue the user's task when Mnemosyne is unavailable. Do not replace it by
   reading its database directly or by switching to another memory surface.

Apply the lifecycle to substantive work: repository changes, diagnosis,
multi-step research, durable decisions, or work whose state should survive the
current session. Skip routine memory work for greetings and disposable
one-answer questions unless the user explicitly asks to remember or recall.

## Resolve project identity

Choose one stable project key before project-scoped recall or writes:

1. Use a key explicitly defined by the user or repository instructions.
2. Otherwise use the main Git repository name. Treat linked worktrees and
   checkout folders as the same project.
3. Add an owner or namespace only when needed to distinguish identical names.
4. Never derive identity from a temporary directory, absolute home path, or
   incidental working-directory name.
5. If no stable project exists, use only focused global recall and durable
   global preferences. Do not invent a project or create a handoff.

Prefix every project memory exactly with `[project:<key>]`. Do not remove the
prefix to make a fact available across projects; semantic recall can still find
a relevant, properly attributed lesson.

## Start with focused recall

At the beginning of substantive work:

1. Search for the exact marker `[project:<key>] HANDOFF` first. Use a small
   result limit and retain the memory ID when returned.
2. Run one focused recall combining the project key, the current goal, and the
   kinds of context that could change the work: decisions, constraints,
   blockers, lessons, and preferences.
3. When canonical tools are available, query only a goal-relevant preference
   or identity category or term. Do not list the entire canonical profile.
4. Query temporal triples only when the goal actually depends on a durable
   relationship that normal recall did not establish.
5. Query cross-project memory only when the goal clearly benefits from a
   reusable lesson or global preference and applicable policy permits it.
6. Inspect timestamps, provenance, veracity, expiry, and supersession. Fetch an
   exact record by ID when the abbreviated recall result is insufficient.
7. Check consequential claims against current files, instructions, docs, and
   live tool output before acting on them.

Do not issue a broad "tell me everything" recall, inject a large memory dump,
or repeatedly recall the same query without new reason.

## Decide whether to write

Persist a candidate only when it is durable, supported, and likely to improve a
future task. Good candidates include stable preferences, confirmed decisions
with rationale, important invariants, reusable evidence-backed lessons, and
material handoff state.

Before every write, search for an equivalent or conflicting record:

- If an equivalent current memory exists, do nothing.
- If a living record changed, update that record by its exact ID. The project
  handoff is the main living record.
- If a fact or decision has been superseded, create the supported replacement
  and invalidate the old record, linking the replacement when the tool allows.
- If current evidence or the user disproves a record, correct or invalidate it
  promptly. Never preserve a known contradiction merely because it was recalled.
- Never hard-delete or `forget` a memory automatically.

For a new normal memory:

- Use global/persistent scope so it can survive sessions, subject to the
  governing policy.
- Keep the content atomic and concise. Start project facts with the project
  prefix and include rationale only when it prevents future ambiguity.
- Set veracity to `stated` for direct user assertions, `tool` for deterministic
  evidence, `imported` for imported facts, and `inferred` only for a clearly
  labeled inference worth retaining.
- Add useful provenance through the source or metadata fields without copying
  sensitive content. Use `valid_until` only when the fact genuinely expires.
- Choose importance deliberately. Reserve very high importance for constraints
  or decisions that should reliably surface; do not inflate routine facts.
- Avoid automatic LLM fact extraction when a concise direct record is enough.

## Maintain one project handoff

Maintain at most one active normal-memory handoff per stable project. Locate it
by marker and update it in place by ID. Create it only after the task establishes
material state worth carrying forward.

Store a new handoff with persistent scope, high but not maximal importance, and
a stable source such as `project:<key>:handoff`. If recall finds multiple active
handoffs, choose the current supported record, merge only still-valid state into
it, and invalidate the other active duplicates without deleting them.

Use this exact compact shape:

```text
[project:<key>] HANDOFF
Objective: <outcome being pursued>
Current state: <what is true now>
Decisions: <durable choices and rationale>
Blockers: <only unresolved blockers or risks>
Verification: <what was actually checked>
Next action: <one concrete continuation step>
```

Replace obsolete fields instead of appending session summaries. Do not include
chat transcripts, tool diaries, large diffs, or content already authoritative in
the repository. When the objective is complete, say so in `Current state`, set
`Blockers` to `None` when true, and use `Next action: None` unless a real follow-up
remains.

## Use advanced memory structures sparingly

Use canonical slots only for stable, directly supported identity or preference
facts that must have exactly one current value. Keep the slot set sparse. Do not
put project handoffs, changing project state, speculative conclusions, or facts
already owned by repository files into canonical slots.

Use temporal triples only for durable relationships that materially benefit from
structured graph queries. Query before adding, include provenance and validity,
supersede an old single-valued relationship when appropriate, and allow multiple
values only when they genuinely coexist. Prefer a normal atomic memory when a
graph relationship adds no retrieval value.

Record a reusable lesson only when evidence supports it. Use a compact shape
such as `[project:<key>] LESSON — Evidence: ... Applies when: ... Guidance: ...`.
Do not convert a one-off debugging event into a universal rule.

## Exclude unsafe and noisy content

Never store secrets, credentials, authentication material, recovery codes,
private keys, cookies, raw personal or customer data, or sensitive content whose
persistence is not clearly authorized. Ask before persisting information when
sensitivity is uncertain.

Also exclude raw or reconstructed transcripts, routine status commentary,
temporary hypotheses, command output, logs, stack traces, large file or code
excerpts, and facts already authoritative in tracked files. Memory should
supplement durable sources, not duplicate them.

## Respect maintenance boundaries

Safe automatic operations are focused recall, exact retrieval, and selective
remember, update, or invalidate actions covered by the governing policy.

Never automatically run:

- consolidation or `sleep`
- bulk import or export
- remote synchronization
- shared-surface writes
- hygiene cleanup
- deletion or `forget`
- persona promotion or demotion
- cross-bank transfer
- broad or destructive maintenance

Run one of those only when the user explicitly requests that specific operation
and any required approval is satisfied.

## Finish quietly

Before finishing substantive work:

1. Identify only newly established durable facts that will materially help later.
2. Deduplicate, then remember, update, or invalidate as appropriate.
3. Update the project handoff if the objective, state, decisions, blockers,
   verification, or next action materially changed.
4. Write nothing when no durable information emerged.
5. Continue normally after a memory failure. Mention it only when the user asked
   about memory or the failure materially compromises an expected handoff.
