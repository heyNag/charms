# Roadmap

This roadmap is directional. It is not a commitment to overbuild the repo.

## Phase 1: Source-Only Skills

Maintain the current source-only package shape:

```text
packages/<name>
packages/<name>/skills/<name>
```

Keep `watch-video`, `codex-reset-credit`, and `x-bookmarks` easy to install in
Claude Code, Codex, Claude Desktop custom skills, OpenCode, and optional
Skillshare.

## Phase 2: Better Reports And Fallbacks

Improve `watch-video` report readability, caption cleanup, transcript previews,
and fallback behavior when native captions are incomplete or unavailable.

## Phase 3: Richer Agent Ergonomics

Improve commands, install docs, target mapping, and troubleshooting. Keep local
installed copies downstream of package source.

## Phase 4: Real MCP Tools

When the local package surface is stable, add real tools under
`mcp/watch-video`, such as `video_info`, `video_analyze`, `video_watch`, and
`video_detail`.

## Phase 5: Optional Deployment

If useful, make `mcp/watch-video` deployable to Railway or a similar platform.
Deployment should build on the independent MCP folder shape, not on a gateway.

## Phase 6: More Agent Tools

Add more packages only when they have a clear local workflow or agent need. New
packages should follow `docs/adding-a-skill.md`.

## MCP Gateway Constraint

Do not add an MCP gateway, router, proxy, or shared MCP control plane unless the
user explicitly asks for it.
