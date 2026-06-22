# agent-tools

`agent-tools` is a public workspace for portable agent skills, Claude Code
plugins, helper commands, and local workflow scripts.

## Skills

| Skill | Use It For | Start Here |
|---|---|---|
| `watch-video` | Inspect YouTube URLs, local videos, demos, tutorials, screen recordings, and UI bug videos. | [docs/watch-video.md](docs/watch-video.md) |
| `codex-reset-credit` | Check Codex reset credits and local rate-limit reset windows without exposing auth secrets. | [docs/codex-reset-credit.md](docs/codex-reset-credit.md) |
| `x-bookmarks` | Fetch, search, and digest X/Twitter bookmarks using Bird or optional X API v2. | [docs/x-bookmarks.md](docs/x-bookmarks.md) |

## Install

Pick your target and follow [docs/installing-skills.md](docs/installing-skills.md).

Quick orientation:

- Claude Code installs packages from the marketplace catalog.
- Codex, OpenCode, generic Agent Skills, and Skillshare consume
  `packages/<name>/skills/<name>`.
- Cursor and root plugin wrappers use the root `skills/` symlink index.
- Claude Desktop / claude.ai custom skills are built locally under ignored
  `.dist/` artifacts.

## Use

After installing, invoke the skill through your agent target:

```text
Claude Code: /watch-video:watch <video-url-or-path>
Claude Code: /codex-reset-credit:codex-reset-credit
Claude Code: /x-bookmarks:x-bookmarks digest
Codex/Cursor/OpenCode: ask the agent to use watch-video, codex-reset-credit, or x-bookmarks
```

Skill-specific requirements, examples, and safety notes live in:

- [docs/watch-video.md](docs/watch-video.md)
- [docs/codex-reset-credit.md](docs/codex-reset-credit.md)
- [docs/x-bookmarks.md](docs/x-bookmarks.md)

## Repo Shape

```text
packages/<name>/                 package source and Claude Code plugin root
packages/<name>/skills/<name>/   portable skill folder
packages/<name>/commands/        optional Claude Code slash commands
skills/<name>                    root symlink index to package skill source
commands/*.md                    root symlink index to package commands
.claude-plugin/                  Claude Code marketplace and root metadata
.codex-plugin/                   Codex plugin metadata
.cursor-plugin/                  Cursor plugin metadata
.opencode/                       OpenCode plugin wrapper
skillshare-hub.json              optional Skillshare hub index
.dist/                           ignored local build artifacts
docs/                            project docs and runbooks
scripts/                         build, install, test, and release helpers
```

Normal edits happen under `packages/<name>/`. Root `skills/` and `commands/`
are maintained symlink indexes; do not edit through them.

## Development

```sh
make build-packages
make public-check
git status
```

`make build-packages` refreshes root symlink indexes, marketplace/hub indexes,
and ignored Claude custom-skill artifacts under `.dist/`. `make public-check`
runs the repo’s publishability checks and install dry-runs.

For architecture, installation, onboarding, updates, releases, and target
differences, start with [docs/README.md](docs/README.md).

## Public URLs

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
media files, transcripts, frames, caches, `.dist/`, local virtualenvs, or
`node_modules/` outputs.
