# Roadmap

This roadmap is directional. It is not a commitment to overbuild the repo.

## Phase 1: Local Tools

Maintain `packages/watch-video` as a useful local skill/commands/scripts package
for video analysis, `packages/codex-reset-credit` as a read-only local skill for
checking Codex reset credits and rate-limit reset windows, and
`packages/x-bookmarks` as a local X/Twitter bookmark fetch/search/digest skill.
Keep all public packages easy to install into Claude Code, Claude custom skills,
Codex, OpenCode/generic Agent Skills consumers, and Skillshare Hub users.

`watch-video` includes preflight checks, focused URL downloads, caption-first
transcripts, bounded auto frame extraction, report modes, and Groq fallback.
`codex-reset-credit` includes sanitized text/JSON reports, live reset-credit
lookup, and local-only rate-limit snapshot reads.
`x-bookmarks` includes Bird-first bookmark fetching, optional X API v2 OAuth,
local query filters, since-last review state, and safe action-oriented digest
instructions.

## Phase 2: Better Reports And Fallbacks

Improve report readability, caption cleanup, transcript previews, and fallback
behavior when native captions are incomplete or unavailable. Future work can add
better visual report summaries, configurable transcript provider preferences,
and richer caption diagnostics.

## Phase 3: Richer Agent Ergonomics

Make local use smoother through clearer commands, safer install behavior, and
agent-friendly instructions. Keep installed copies downstream of repo source.
Public packages should follow this shape:

- `packages/<name>` for source of truth
- `generated/claude/plugins/<name>` when the package targets Claude Code
- `generated/claude/custom-skills/<name>` when the package targets Claude
  Desktop or claude.ai custom skill upload
- `generated/codex/skills/<name>` when the package targets Codex
- `generated/agent-skills/<name>` when the package targets OpenCode or generic
  `SKILL.md` Agent Skills consumers
- `skillshare-hub.json` as generated discovery metadata for Skillshare Hub
  users
- `mcp/<name>` only when the package needs an MCP server

Keep skills agent-agnostic at the source level where practical. Surface-specific
packaging should be generated from `packages/<name>`, not maintained by hand.

## Phase 4: Real MCP Tools

When the local package surface is stable, add real tools under
`mcp/watch-video`. Start small with tools such as `video_info`,
`video_analyze`, `video_watch`, and `video_detail`. Metadata inspection and safe
local job launching are more useful than a large API surface.

## Phase 5: Optional Deployment

If useful, make `mcp/watch-video` deployable to Railway or a similar platform.
Deployment should build on the independent MCP folder shape, not on a gateway.

## Phase 6: More Agent Tools

Add more packages only when they have a clear local workflow or agent need. New
packages can incubate here and graduate into standalone repos later.

## MCP Gateway Constraint

Do not add an MCP gateway, router, proxy, or shared MCP control plane unless the
user explicitly asks for it. Keep MCP servers independently understandable and
deployable under `mcp/<name>`.
