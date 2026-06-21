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
mcp/                  future deployable MCP servers
docs/                 project memory and agent orientation
scripts/              build, install, test, and helper scripts
.github/workflows/    CI
```

`generated/` includes Claude Code plugin packages, Claude custom-skill upload
folders, Codex skill folders, and OpenCode/generic Agent Skill folders.
`generated/` and `.claude-plugin/` are generated from `packages/`, but they are
committed as public install targets.

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
recreates them from `packages/`. Use that flow when source files, generator
templates, generated headers, or public package paths change. Do not move or
patch generated files by hand.

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
make verify-packages
make audit-generated
make verify-generated-clean
```
