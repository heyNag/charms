# Decisions

Architecture decisions for `charms`.

## Repository Scope

Use `charms` as the repo name and scope. The repo holds skills, commands,
helper scripts, Claude Code plugins, and optional Skillshare discovery.

## Source-Only Packages

Use `packages/<name>` as the package source and Claude Code plugin root. The
portable skill lives at `packages/<name>/skills/<name>`. Codex, Cursor,
OpenCode, generic Agent Skills, and Skillshare use that skill folder directly
or through root symlink indexes.

This avoids committed per-target copies and keeps one editable source path for
each skill.

## Root Harness Wrappers

Keep lightweight root wrappers for harnesses that expect repository-level
metadata:

```text
.claude-plugin/plugin.json
.codex-plugin/plugin.json
.cursor-plugin/plugin.json
.opencode/plugins/charms.js
```

These wrappers point at `skills/`, a symlink index generated from
`packages/<name>/skills/<name>`. The symlink index is not an editable source
tree.

## No Current MCP Tree

Keep local package source under `packages/<name>`. Do not keep placeholder MCP
folders in the repo. Add `mcp/<name>` only when there is a real MCP tool surface
to implement, test, and document.

## No MCP Gateway

Do not build an MCP gateway, router, proxy, or shared control plane unless the
user explicitly asks for it.

## Claude Desktop Artifacts

Claude Desktop / claude.ai custom skills need lowercase `skill.md`. Build those
folders under ignored `.dist/` with `make build-packages`; do not commit them.

## Optional Skillshare Discovery

Keep Skillshare discovery source-first. `skillshare-hub.json` points to
`packages/<name>/skills/<name>`. `.skillignore` hides `.dist/` local artifacts
and the root `skills/` and `commands/` symlink indexes so discovery stays on
canonical package source.

## Package Manifests

Use `packages/<name>/tool.json` to declare public status, install targets, tags,
and package traits. Use `packages/<name>/.claude-plugin/plugin.json` for Claude
plugin metadata and version. Use `SKILL.md` frontmatter for agent-visible
trigger metadata.

## Manual Skill Releases

Ordinary pushes and pull requests verify the repo but do not release skills.
Public skill releases use the manual `Release Skill` GitHub Actions workflow.
The workflow computes a UTC date-based package version, updates
`packages/<name>/.claude-plugin/plugin.json`, refreshes indexes/artifacts,
verifies, commits, pushes, and creates a skill-scoped GitHub Release with a tag
named `<skill>@<version>`, a changelog of commits touching the package since
its previous tag, and a ready-to-upload Claude Desktop custom-skill ZIP when
the skill targets that surface.

The workflow accepts a package name string and validates the package from repo
source. New skills do not need release workflow configuration changes.

GitHub Packages are intentionally unused until there is a real package artifact
such as an npm package, Docker image, or binary.

## Watch Video Defaults

`watch-video` uses Groq `whisper-large-v3-turbo` as the default transcription
fallback, prefers native captions before paid transcription, and uses OpenAI
`whisper-1` when `--transcriber openai` is requested. Captions are probed
before any media download, and media downloads never request subtitles, so
subtitle rate limits cannot fail a run; the default caption selector is
English-preferred (never `all`, which fans out to 100+ auto-translate tracks
and gets rate-limited). Frame extraction is scene-aware by default with a
keyframe fast tier and a uniform fallback, drops near-duplicate frames before
spending the budget, defaults to 512px-wide frames, and stays bounded by hard
caps (100 frames; 300 in `full` detail). Whisper audio beyond the 24 MB upload
cap is chunked and stitched with partial-failure tolerance.

The agent asks the user which detail level to run for each new video
(`transcript`, `efficient`, `balanced` recommended, `full`, ordered lightest
to heaviest), skipping the question when the request, `--detail`,
`WATCH_VIDEO_DETAIL`, a same-video re-run, or a non-interactive context
already answers it; unanswerable runs default to `balanced`.

Whisper keys are asked for once, only when a captionless video actually needs
transcription, and stored via `doctor.py --set-key` in
`~/.config/watch-video/.env` (mode 600); environment variables take
precedence, declining falls back to captions/frames-only, and stored keys are
never printed.

## Codex Reset Credit Safety

`codex-reset-credit` is read-only. It may inspect local Codex auth/session state
and the reset-credit endpoint, but it must not redeem credits, modify Codex
state, print secrets, or expose raw account/auth data.

## X Bookmarks Backends

`x-bookmarks` prefers Bird cookie auth because it uses the user's local browser
session and avoids paid X API credits. X API v2 remains optional.

## ChatGPT Pro Review Boundary

`chatgpt-pro-review` is a reviewer/reconciler workflow. It prepares scoped
packets for ChatGPT Pro or Extended Pro and then verifies the response against
local evidence. It must not send private repo context, secrets, auth material,
customer data, or unrelated private files to ChatGPT unless the user explicitly
approves that specific context.
