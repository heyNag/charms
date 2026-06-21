# agent-tools

`agent-tools` is a public workspace for agent skills, commands, plugins, helper
scripts, generated install packages, and future MCP servers.

Public tools:

- `watch-video` - inspect short videos, tutorials, demos, screen recordings,
  and UI bug videos.
- `codex-reset-credit` - check Codex reset credits and local rate-limit reset
  windows without exposing auth secrets.
- `x-bookmarks` - fetch, search, and digest X/Twitter bookmarks using Bird
  cookie auth or optional X API v2.

## New Here

Choose the path that matches what you are trying to do:

- Install and use a tool: start with the install section for your agent below.
- Understand source versus generated files: read
  [docs/architecture.md](docs/architecture.md) and
  [docs/distribution-targets.md](docs/distribution-targets.md).
- Optional Skillshare hub install, if you already use Skillshare: read
  [docs/skillshare.md](docs/skillshare.md).
- Add a new skill: follow
  [docs/adding-a-skill.md](docs/adding-a-skill.md) step by step.
- Update or release an existing skill: follow
  [docs/updating-a-skill.md](docs/updating-a-skill.md).
- Check security rules before live credentials or local auth: read
  [docs/security.md](docs/security.md).

Normal development edits happen under `packages/<name>/`. Public install
folders under `generated/`, the Claude marketplace catalog under
`.claude-plugin/`, and `skillshare-hub.json` are rebuilt from `packages/`; do
not patch them by hand.

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
cp -R generated/codex/skills/watch-video ~/.codex/skills/watch-video
rm -rf ~/.codex/skills/codex-reset-credit
cp -R generated/codex/skills/codex-reset-credit ~/.codex/skills/codex-reset-credit
rm -rf ~/.codex/skills/x-bookmarks
cp -R generated/codex/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

## Optional: Skillshare

If you already use Skillshare, this repo publishes a curated hub index so the
web UI shows only canonical source packages:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

In the Skillshare web UI, use `Search > Hub`, add/select that hub URL in the
hub manager/source selector, then search for `watch`, `codex`, `bookmarks`, or
another keyword. Do not paste the hub URL into the keyword search box. This is
an optional install path; the main public install paths are Claude Code, Codex,
Claude Desktop, and OpenCode.

CLI users can save the hub once:

```sh
skillshare hub add https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json --label agent-tools
skillshare hub default agent-tools
skillshare search --hub agent-tools watch
```

Direct package install also works:

```sh
skillshare install heyNag/agent-tools/packages/watch-video --track
skillshare install heyNag/agent-tools/packages/codex-reset-credit --track
skillshare install heyNag/agent-tools/packages/x-bookmarks --track
skillshare sync
```

Avoid installing from `generated/` through Skillshare. Those folders are
target-specific outputs for Claude Code, Claude Desktop, Codex, and OpenCode.
The root `.skillignore` hides `generated/` during Skillshare repo discovery;
GitHub Code Search may still show generated copies because it scans every
committed `SKILL.md`.

## Install For Claude Desktop Or Claude.ai Skills

Claude custom skills use a ZIP containing a skill folder with lowercase
`skill.md`. Use the Claude custom-skill bundles generated from `packages/`:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
make rebuild-generated
cd generated/claude/custom-skills
zip -r watch-video.zip watch-video
zip -r codex-reset-credit.zip codex-reset-credit
zip -r x-bookmarks.zip x-bookmarks
```

Upload the ZIP in Claude's `Customize > Skills` flow. The lowercase `skill.md`
file is generated from `packages/<name>/SKILL.md`.

Optional no-terminal path: use the third-party
[Skills Compiler](https://skill-compiler.statechange.ai/) to package a public
generated custom-skill folder into a Claude Desktop `.skill` file. Paste one of
these folder URLs, preview the files, download the `.skill`, then import it in
Claude:

```text
https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/watch-video
https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/codex-reset-credit
https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/x-bookmarks
```

This is a convenience path only. The repo source of truth is still
`packages/<name>/`, and the generated Claude custom-skill folder is still
produced by `make rebuild-generated`.

## Install For OpenCode

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.config/opencode/skills
rm -rf ~/.config/opencode/skills/watch-video
cp -R generated/agent-skills/watch-video ~/.config/opencode/skills/watch-video
rm -rf ~/.config/opencode/skills/codex-reset-credit
cp -R generated/agent-skills/codex-reset-credit ~/.config/opencode/skills/codex-reset-credit
rm -rf ~/.config/opencode/skills/x-bookmarks
cp -R generated/agent-skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

The same `generated/agent-skills/<name>` folders also work for agent-compatible
skill locations such as `.agents/skills/<name>` or `~/.agents/skills/<name>`.

## Local Development Install

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
./scripts/install-all.sh
```

`install-all.sh` installs every public package with the matching `claude` or
`codex` target in `packages/<name>/tool.json`.

## Requirements

`watch-video` needs local video tooling:

```sh
brew install yt-dlp ffmpeg jq
python3 packages/watch-video/scripts/doctor.py
```

Groq is optional but recommended when captions are missing or incomplete:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

Default Groq model: `whisper-large-v3-turbo`.
OpenAI transcription is also available with `--transcriber openai` and
`OPENAI_API_KEY`; the default OpenAI model is `whisper-1` so segment timestamps
work with the verbose JSON response shape used by `watch-video`.

`codex-reset-credit` uses local Codex auth/session files when available. It is
read-only and must not print tokens, account IDs, raw auth contents, or modify
Codex state. It uses Python standard-library code and has no third-party Python
dependency.

`x-bookmarks` prefers the `bird` CLI for no-credit local X/Twitter bookmark
access and can use X API v2 OAuth state when the API path is requested. Local
state belongs outside the repo under `~/.config/x-bookmarks/`,
`~/.local/state/x-bookmarks/`, and `~/.config/bird/`.

## Quick Test

`watch-video`:

```sh
python3 packages/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

For UI-heavy recordings, prefer PNG frames:

```sh
python3 packages/watch-video/scripts/watch.py ./bug.mov --mode ui-bug --frame-format png
```

`codex-reset-credit` local-only smoke test:

```sh
python3 packages/codex-reset-credit/scripts/check_reset_credits.py --no-live
```

`x-bookmarks` backend status checks:

```sh
command -v bird >/dev/null && bird check --plain
python3 packages/x-bookmarks/scripts/x_api_auth.py --status
```

## Repo Structure

```text
packages/             source of truth for tools
generated/            generated Claude/Codex/OpenCode public install packages
.claude-plugin/       generated Claude Code marketplace catalog
skillshare-hub.json   optional generated Skillshare hub index
mcp/                  future deployable MCP servers
docs/                 project memory and agent orientation
scripts/              build, install, test, and helper scripts
.github/workflows/    CI
```

`generated/` includes Claude Code plugin packages, Claude custom-skill upload
folders, Codex skill folders, and OpenCode/generic Agent Skill folders.
`generated/`, `.claude-plugin/`, and `skillshare-hub.json` are generated from
`packages/`, but they are committed as public install targets or discovery
metadata.

## What To Edit

Edit source files here:

```text
packages/watch-video/
packages/codex-reset-credit/
packages/x-bookmarks/
mcp/watch-video/
scripts/
docs/
```

Do not edit generated public install copies directly:

```text
packages/watch-video/                                -> generated/claude/plugins/watch-video/
packages/watch-video/                                -> generated/claude/custom-skills/watch-video/
packages/watch-video/                                -> generated/codex/skills/watch-video/
packages/watch-video/                                -> generated/agent-skills/watch-video/
packages/codex-reset-credit/                         -> generated/claude/plugins/codex-reset-credit/
packages/codex-reset-credit/                         -> generated/claude/custom-skills/codex-reset-credit/
packages/codex-reset-credit/                         -> generated/codex/skills/codex-reset-credit/
packages/codex-reset-credit/                         -> generated/agent-skills/codex-reset-credit/
packages/x-bookmarks/                                -> generated/claude/plugins/x-bookmarks/
packages/x-bookmarks/                                -> generated/claude/custom-skills/x-bookmarks/
packages/x-bookmarks/                                -> generated/codex/skills/x-bookmarks/
packages/x-bookmarks/                                -> generated/agent-skills/x-bookmarks/
packages/*/tool.json and packages/*/plugin/plugin.json -> .claude-plugin/marketplace.json
packages/*/SKILL.md, packages/*/tool.json, and packages/*/plugin/plugin.json -> skillshare-hub.json
```

Generated directories include `GENERATED.md` files with exact source-path
mappings. Generated Markdown, Python, shell, and YAML files also include an
in-file generated notice when the format allows comments. JSON and LICENSE
files are covered by the nearest `GENERATED.md` marker.

After changing any package under `packages/`, rebuild generated outputs from
scratch:

```sh
make rebuild-generated
make audit-generated
make verify-generated-clean
```

`make rebuild-generated` deletes only `.claude-plugin/` and `generated/`, then
recreates them from `packages/` and rewrites `skillshare-hub.json`. Use that
flow when source files, generator templates, generated headers, public package
paths, or public discovery metadata change. Do not move or patch generated
files by hand.

New tools should follow this pattern:

- `packages/<name>/tool.json`
- `generated/claude/plugins/<name>` when the tool targets Claude Code
- `generated/claude/custom-skills/<name>` when the tool targets Claude Desktop
  or claude.ai custom skill upload
- `generated/codex/skills/<name>` when the tool targets Codex
- `generated/agent-skills/<name>` when the tool targets OpenCode or generic
  `SKILL.md` Agent Skills consumers
- `mcp/<name>` only when an MCP server is needed

There is no MCP gateway.

## Agent Compatibility

The source skills are written to the Agent Skills convention: one folder per
skill, a frontmatter `SKILL.md`, and optional `scripts/`, `references/`,
`agents/`, and `commands/`. Generated public outputs adapt that source for each
surface:

- Claude Code: `generated/claude/plugins/<name>`
- Codex: `generated/codex/skills/<name>`
- Claude Desktop / claude.ai custom skills: `generated/claude/custom-skills/<name>` ZIP
- OpenCode and generic Agent Skills: `generated/agent-skills/<name>`

Runtime access still matters. `watch-video` needs local `yt-dlp` and `ffmpeg`
for full video inspection. `codex-reset-credit` needs local Codex auth/session
state. `x-bookmarks` needs Bird browser-cookie access or local X API OAuth
state. Hosted Claude skill upload can carry the instructions and bundled files,
but it cannot read your local Mac auth/session state.

## Troubleshooting

If marketplace install fails, run these from the repo root:

```sh
claude plugin validate .
claude plugin validate generated/claude/plugins/watch-video
claude plugin validate generated/claude/plugins/codex-reset-credit
claude plugin validate generated/claude/plugins/x-bookmarks
```

## Docs

Start with [docs/README.md](docs/README.md).

Future agents should read `docs/README.md`, `docs/architecture.md`,
`docs/agent-guidelines.md`, `docs/agent-compatibility.md`, and
`docs/distribution-targets.md` before making structural changes.

When adding a new skill, follow
[docs/adding-a-skill.md](docs/adding-a-skill.md).

When updating an existing skill or helping users refresh installed copies,
follow [docs/updating-a-skill.md](docs/updating-a-skill.md).

Public skill releases are manual. Use the GitHub Actions `Release Skill`
workflow to bump the selected package version using the UTC date, rebuild all
generated targets, verify, commit, push, and create a skill-scoped GitHub
Release with a tag named `<skill>@<version>`, for example
`watch-video@YYYY.M.D`.

This repo does not publish GitHub Packages yet. Skill versions are independent,
so GitHub Releases are package-level. GitHub may still show the newest skill
release as the repo's `Latest` release; that label is a GitHub UI artifact, not
a repo-wide version.

## Security

Do not commit real API keys, Codex auth/session files, X/Twitter cookies or
OAuth tokens, `.env.local`, `.watch-video/` artifacts, `.x-bookmarks/` state,
media files, transcripts, frames, caches, or local build outputs. Keep CI
no-secret and free of live Groq/video/Codex/X/Claude requirements. See
[docs/security.md](docs/security.md).

## Checks

```sh
make test
make syntax
make mcp-build
make rebuild-generated
make build-skillshare-hub
make verify-skill-metadata
make verify-packages
make audit-generated
make verify-generated-clean
```
