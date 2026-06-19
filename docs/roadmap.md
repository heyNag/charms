# Roadmap

This roadmap is directional. It is not a commitment to overbuild the repo.

## Phase 1: Local Watch Video

Maintain `packages/watch-video` as a useful local skill/commands/scripts package
for video analysis. Keep it easy to install into Claude and Codex. Current
baseline includes preflight checks, focused URL downloads, caption-first
transcripts, bounded auto frame extraction, report modes, and Groq fallback.

## Phase 2: Better Reports And Fallbacks

Improve report readability, caption cleanup, transcript previews, and fallback
behavior when native captions are incomplete or unavailable. Future work can add
better visual report summaries, configurable transcript provider preferences,
and richer caption diagnostics.

## Phase 3: Richer Claude/Codex Ergonomics

Make local use smoother through clearer commands, safer install behavior, and
agent-friendly instructions. Keep installed copies downstream of repo source.
Public packages should follow this shape:

- `packages/<name>` for source of truth
- `plugins/<name>` when the package targets Claude Code
- `codex/<name>` when the package targets Codex or generic skills
- `mcp/<name>` only when the package needs an MCP server

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

## Not Planned Now

An MCP gateway is not planned now. Do not build one unless the user explicitly
asks for it.
