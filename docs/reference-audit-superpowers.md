# Reference Audit: obra/Superpowers

Audit date: 2026-06-22

Reference inspected:

```text
https://github.com/obra/Superpowers
cloned commit: 896224c
```

This audit inspected repository code and structure, including manifests, hooks,
OpenCode/Pi plugin code, skills, target-specific docs, scripts, and tests. It
does not copy Superpowers code into `agent-tools`.

## What Superpowers Does Well

- Keeps one canonical skills directory and lets thin target wrappers expose it
  to multiple harnesses.
- Treats target support as a real integration, not just copied files.
- Uses session-start bootstrap injection for methodology skills that must
  auto-trigger before agent work begins.
- Documents target tool mappings so skills can describe actions instead of
  hard-coding one harness's tool names.
- Maintains target-specific manifests for Claude Code, Codex, Cursor, Kimi,
  Gemini, OpenCode, and Pi.
- Has target-specific tests for plugin loading, hook behavior, explicit skill
  requests, and sync scripts.
- Uses generated or synchronized package shapes carefully rather than letting
  every target drift by hand.
- Keeps skill authoring guidance focused on trigger quality, pressure testing,
  and avoiding workflow summaries in discovery metadata.

## What Agent Tools Already Does Well

- Keeps package source under `packages/<name>` and marks it with `SOURCE.md`.
- Rebuilds public target outputs under `generated/` from package source.
- Commits generated targets for Claude Code, Claude Desktop / claude.ai, Codex,
  and OpenCode/generic Agent Skills.
- Generates `.claude-plugin/marketplace.json` and `skillshare-hub.json`.
- Keeps release version bumps behind the manual `Release Skill` workflow.
- Runs a no-secret public check with tests, syntax, MCP placeholder build,
  package verification, generated audits, and install dry-run.
- Keeps MCP separate under `mcp/` and does not create a gateway.

## Adopted Now

- Added `docs/target-tool-mapping.md` so future package authors understand the
  action vocabulary and target differences.
- Updated package `SKILL.md` descriptions to be trigger-oriented. Public
  package descriptions remain in `tool.json`.
- Added metadata verification so public skill frontmatter descriptions must
  stay trigger-oriented.
- Updated onboarding docs to point at target mapping and trigger-focused skill
  descriptions.
- Added this reference audit so future agents know what was learned and what
  was intentionally not copied.

## Intentionally Not Copied

- No session-start bootstrap injection. Current `agent-tools` packages are
  task/domain tools, not a global methodology that must auto-trigger in every
  conversation.
- No target runtime config mutation. Public outputs remain generated install
  bundles, and install scripts remain explicit/local.
- No OpenCode/Pi plugin implementation yet. The current OpenCode target is the
  generic Agent Skills folder under `generated/agent-skills/<name>`.
- No full LLM eval harness. Current CI stays offline, deterministic, and
  no-secret.
- No large contribution-policy voice or PR gate copied from Superpowers. This
  repo keeps lightweight maintainer guidance in `docs/agent-guidelines.md`.

## Gaps Worth Considering

P0: correctness and safety

- Keep `make public-check` passable before committing intentional generated
  changes.
- Keep generated-target audits strict so manual edits cannot drift from source.
- Keep `SKILL.md` trigger metadata aligned with `tool.json` and
  `skillshare-hub.json`.

P1: usability

- Add target-specific install/update smoke tests where they can run without
  live secrets or paid services.
- Add optional target validation commands for Claude Code, Codex, and OpenCode
  when local CLIs exist.
- Add clearer target tool mapping whenever a new target is added.

P2: nice-to-have

- Consider a first-class OpenCode plugin wrapper only if the generic Agent
  Skills copy path becomes painful.
- Consider a Codex plugin wrapper only if Codex plugin distribution becomes
  preferable to generated skill folders.
- Consider slow/manual behavior evals for high-impact skill wording changes,
  but keep CI deterministic.

## License And Attribution

Superpowers is MIT licensed. This audit borrows design ideas only. No
substantial code, scripts, manifests, or skill text were copied into
`agent-tools`.

If future work copies or closely adapts code from Superpowers, preserve the MIT
license attribution and document the copied source path in this file or a
dedicated attribution note.
