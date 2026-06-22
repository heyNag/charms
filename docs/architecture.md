# Architecture

`agent-tools` is a public source-only workspace for agent skills, Claude Code
plugins, optional Skillshare discovery, helper scripts, and future MCP server
shapes.

## Repo Shape

```text
packages/             source packages and Claude Code plugin roots
.claude-plugin/       Claude Code marketplace catalog
skillshare-hub.json   optional Skillshare hub index
.dist/                ignored local build artifacts
mcp/                  deployable MCP server shapes, one folder per MCP server
scripts/              install, build, test, and release helpers
.github/workflows/    CI and manual skill release workflow
docs/                 orientation and project memory
```

There is no committed `generated/` directory.

## Packages

Current packages:

```text
packages/watch-video
packages/codex-reset-credit
packages/x-bookmarks
```

Each package is directly consumable as a Claude Code plugin source and contains
a portable skill folder:

```text
packages/<name>/skills/<name>
```

Package manifests live at:

```text
packages/<name>/tool.json
packages/<name>/.claude-plugin/plugin.json
```

## Distribution

Public install surfaces consume source paths:

```text
Claude Code       -> packages/<name>
Codex             -> packages/<name>/skills/<name>
OpenCode/generic  -> packages/<name>/skills/<name>
Skillshare hub    -> packages/<name>/skills/<name>
Claude Desktop    -> .dist/claude/custom-skills/<name> built locally
```

The root `.claude-plugin/marketplace.json` is generated from package manifests
and points to `./packages/<name>`. `skillshare-hub.json` is generated from
`tool.json`, `.claude-plugin/plugin.json`, and skill frontmatter, and points to
`packages/<name>/skills/<name>`.

Run:

```sh
make build-packages
make public-check
```

## MCP

`mcp/` is for deployable MCP server shapes. The current placeholder is:

```text
mcp/watch-video
```

It exposes a status tool only. It does not wrap video processing yet.

Future MCP work can add real tools such as `video_info`, `video_analyze`,
`video_watch`, and `video_detail` inside `mcp/watch-video`.

## No Gateway

There is no MCP gateway. Do not add a gateway, router, proxy, or shared MCP
control plane unless explicitly requested.

There is also no global session-start bootstrap today. Current packages are
task/domain tools invoked by users, native skill discovery, or agent judgment.

## Source Of Truth

Edit source paths:

```text
packages/<name>/
mcp/watch-video/
scripts/
docs/
```

Installed copies, `.dist/` artifacts, local auth state, and run artifacts are
not source of truth.
