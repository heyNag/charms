# Decisions

Architecture decisions for `agent-tools`.

## Repository Scope

Use `agent-tools` as the repo name and scope. The repo holds skills, commands,
helper scripts, Claude Code plugins, optional Skillshare discovery, and future
MCP server shapes.

## Source-Only Packages

Use `packages/<name>` as the package source and Claude Code plugin root. The
portable skill lives at `packages/<name>/skills/<name>`. Codex, OpenCode,
generic Agent Skills, and Skillshare use that skill folder directly.

This avoids committed per-target copies and keeps one editable source path for
each skill.

## Package And MCP Separation

Keep local package source under `packages/<name>` and MCP server source under
`mcp/<name>`. Local skill/script packages should not be forced into server
architecture.

## No MCP Gateway

Do not build an MCP gateway, router, proxy, or shared control plane unless the
user explicitly asks for it.

## Claude Desktop Artifacts

Claude Desktop / claude.ai custom skills need lowercase `skill.md`. Build those
folders under ignored `.dist/` with `make build-packages`; do not commit them.

## Optional Skillshare Discovery

Keep Skillshare discovery source-first. `skillshare-hub.json` points to
`packages/<name>/skills/<name>`. `.skillignore` hides `.dist/` and defensive
local generated leftovers.

## Package Manifests

Use `packages/<name>/tool.json` to declare public status, install targets, tags,
and MCP presence. Use `packages/<name>/.claude-plugin/plugin.json` for Claude
plugin metadata and version. Use `SKILL.md` frontmatter for agent-visible
trigger metadata.

## Manual Skill Releases

Ordinary pushes and pull requests verify the repo but do not release skills.
Public skill releases use the manual `Release Skill` GitHub Actions workflow.
The workflow computes a UTC date-based package version, updates
`packages/<name>/.claude-plugin/plugin.json`, refreshes indexes/artifacts,
verifies, commits, pushes, and creates a skill-scoped GitHub Release with a tag
named `<skill>@<version>`.

GitHub Packages are intentionally unused until there is a real package artifact
such as an npm package, Docker image, binary, or MCP container.

## Watch Video Defaults

`watch-video` uses Groq `whisper-large-v3-turbo` as the default transcription
fallback, prefers native captions before paid transcription, uses OpenAI
`whisper-1` when `--transcriber openai` is requested, and keeps frame extraction
bounded with automatic budgeting and hard caps.

## Codex Reset Credit Safety

`codex-reset-credit` is read-only. It may inspect local Codex auth/session state
and the reset-credit endpoint, but it must not redeem credits, modify Codex
state, print secrets, or expose raw account/auth data.

## X Bookmarks Backends

`x-bookmarks` prefers Bird cookie auth because it uses the user's local browser
session and avoids paid X API credits. X API v2 remains optional.
