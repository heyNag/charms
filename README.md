# agent-tools

`agent-tools` is a public workspace for agent skills, commands, helper scripts,
Claude Code plugins, optional Skillshare discovery, and future MCP servers.

Current public skills:

- `watch-video` - inspect short videos, tutorials, demos, screen recordings,
  and UI bug videos.
- `codex-reset-credit` - check Codex reset credits and local rate-limit reset
  windows without exposing auth secrets.
- `x-bookmarks` - fetch, search, and digest X/Twitter bookmarks using Bird
  cookie auth or optional X API v2.

## Source-Only Shape

This repo follows a source-only package layout inspired by projects that expose
one shared skills tree to multiple agent targets.

```text
packages/<name>/                 package source and Claude Code plugin root
packages/<name>/skills/<name>/   portable skill folder for Codex/OpenCode/etc.
packages/<name>/commands/        optional Claude Code slash commands
.claude-plugin/marketplace.json  Claude Code marketplace catalog
skillshare-hub.json              optional Skillshare hub index
.dist/                           ignored local build artifacts
mcp/                             future deployable MCP server shapes
docs/                            project memory and onboarding docs
scripts/                         build, install, test, and release helpers
```

There is no committed `generated/` target-copy folder. Claude Code installs
`packages/<name>` directly. Codex and OpenCode copy
`packages/<name>/skills/<name>` directly. Claude Desktop custom-skill bundles
are built locally under `.dist/` when needed.

Normal edits happen under `packages/<name>/`.

## Install For Claude Code

```text
/plugin marketplace add heyNag/agent-tools
/plugin install watch-video@agent-tools
/plugin install codex-reset-credit@agent-tools
/plugin install x-bookmarks@agent-tools
```

After installing, try:

```text
/watch-video:watch <video-url-or-path>
/codex-reset-credit:codex-reset-credit
/x-bookmarks:x-bookmarks digest
```

If your Claude Code version shows a different command name, run `/plugin list`
or `/plugin details <plugin>@agent-tools`.

## Install For Codex

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/watch-video
cp -R packages/watch-video/skills/watch-video ~/.codex/skills/watch-video
rm -rf ~/.codex/skills/codex-reset-credit
cp -R packages/codex-reset-credit/skills/codex-reset-credit ~/.codex/skills/codex-reset-credit
rm -rf ~/.codex/skills/x-bookmarks
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

Local development shortcut:

```sh
./scripts/install-codex.sh
```

## Install For OpenCode

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.config/opencode/skills
rm -rf ~/.config/opencode/skills/watch-video
cp -R packages/watch-video/skills/watch-video ~/.config/opencode/skills/watch-video
rm -rf ~/.config/opencode/skills/codex-reset-credit
cp -R packages/codex-reset-credit/skills/codex-reset-credit ~/.config/opencode/skills/codex-reset-credit
rm -rf ~/.config/opencode/skills/x-bookmarks
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

## Install For Claude Desktop Or Claude.ai Skills

Claude custom skills use lowercase `skill.md`, so this repo builds local
artifacts under ignored `.dist/`:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
make build-packages
cd .dist/claude/custom-skills
zip -r watch-video.zip watch-video
zip -r codex-reset-credit.zip codex-reset-credit
zip -r x-bookmarks.zip x-bookmarks
```

Upload the ZIP in Claude's `Customize > Skills` flow. Do not commit `.dist/` or
ZIP files.

## Optional Skillshare

If you already use Skillshare, use the curated hub:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

In the Skillshare web UI, use `Search > Hub`, add/select that hub URL, then
search for `watch`, `codex`, `bookmarks`, or another keyword.

CLI users can install directly from the canonical skill folders:

```sh
skillshare install heyNag/agent-tools/packages/watch-video/skills/watch-video --track
skillshare install heyNag/agent-tools/packages/codex-reset-credit/skills/codex-reset-credit --track
skillshare install heyNag/agent-tools/packages/x-bookmarks/skills/x-bookmarks --track
skillshare sync
```

## Requirements

`watch-video` needs local video tooling:

```sh
brew install yt-dlp ffmpeg jq
python3 packages/watch-video/skills/watch-video/scripts/doctor.py
```

Groq is optional but recommended when captions are missing or incomplete:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

`codex-reset-credit` uses local Codex auth/session files when available. It is
read-only and must not print tokens, account IDs, raw auth contents, or modify
Codex state.

`x-bookmarks` prefers the `bird` CLI for no-credit local X/Twitter bookmark
access and can use X API v2 OAuth state when requested.

## Quick Tests

`watch-video`:

```sh
python3 packages/watch-video/skills/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

`codex-reset-credit`:

```sh
python3 packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py --no-live
```

`x-bookmarks`:

```sh
command -v bird >/dev/null && bird check --plain
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/x_api_auth.py --status
```

## Development Checks

```sh
make build-packages
make public-check
git status
```

`make build-packages` refreshes `.claude-plugin/marketplace.json`,
`skillshare-hub.json`, and ignored Claude custom-skill artifacts under
`.dist/`. `make public-check` runs tests, syntax checks, MCP placeholder build,
package verification, metadata verification, source-index drift checks, and
install dry-runs.

## Docs

Start with [docs/README.md](docs/README.md). Future agents should read
`docs/architecture.md`, `docs/package-shape.md`, and
`docs/agent-guidelines.md` before structural changes.

## Search URLs

GitHub/Search URL:

```text
https://github.com/heyNag/agent-tools
```

Skillshare Hub URL:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

## Security

Do not commit real API keys, Codex auth/session files, X/Twitter cookies or
OAuth tokens, `.env.local`, `.watch-video/` artifacts, `.x-bookmarks/` state,
media files, transcripts, frames, caches, `.dist/`, local virtualenvs, or MCP
`dist/`/`node_modules/` outputs.
