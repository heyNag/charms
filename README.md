# agent-tools

`agent-tools` is a collection of agent tools, skills, commands, plugins, helper
scripts, and future MCP servers.

The current public tool is `watch-video`, a local video inspection package for
short clips, tutorials, demos, screen recordings, and UI bug videos.

## Install For Claude Code

```text
/plugin marketplace add heyNag/agent-tools
/plugin install watch-video@agent-tools
```

After installing, try:

```text
/watch-video:watch <video-url-or-path>
```

If your Claude Code version shows a different command name, run `/plugin list`
or `/plugin details watch-video@agent-tools`.

## Install For Codex Or Generic Skills

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/watch-video
cp -R codex/watch-video ~/.codex/skills/watch-video
```

## Local Development Install

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
./scripts/install-all.sh
```

## Requirements

```sh
brew install yt-dlp ffmpeg jq
```

Check local readiness:

```sh
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
work with the current verbose JSON response.

## Quick Test

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

Useful flags include `--transcriber groq|openai|none`, `--mode
general|tutorial|ui-bug|notes`, `--frame-mode auto|interval`, `--fps`,
`--resolution`, `--frame-format jpeg|png|webp`, `--cleanup`, and
`--cleanup-frames`.

## Repo Structure

```text
packages/             source of truth for tools
plugins/              Claude Code publishable plugins
codex/                Codex and generic skill packages
mcp/                  future deployable MCP servers
docs/                 project memory and agent orientation
scripts/              build, install, test, and helper scripts
.github/workflows/    CI
```

`plugins/` and `codex/` are generated from `packages/`, but they are committed as
public install targets.

## What To Edit

Edit source files here:

```text
packages/watch-video/
mcp/watch-video/
scripts/
docs/
```

Do not edit generated public install copies directly:

```text
plugins/watch-video/              generated from packages/watch-video/
codex/watch-video/                generated from packages/watch-video/
.claude-plugin/marketplace.json   generated from packages/*/tool.json and plugin metadata
```

Generated directories include `GENERATED.md` files with exact source-path
mappings. Generated Markdown and Python files also include an in-file generated
notice when the format allows comments. JSON and LICENSE files are covered by
the nearest `GENERATED.md` marker.

After changing `packages/watch-video`, run:

```sh
make build-packages
make audit-generated
make verify-generated-clean
```

Future tools should follow this pattern:

- `packages/<name>/tool.json`
- `plugins/<name>` when the tool targets Claude Code
- `codex/<name>` when the tool targets Codex or generic skills
- `mcp/<name>` only when an MCP server is needed

There is no MCP gateway for now.

## Troubleshooting

If marketplace install fails, run these from the repo root:

```sh
claude plugin validate .
claude plugin validate plugins/watch-video
```

## Docs

Start with [docs/README.md](docs/README.md).

Future agents should read `docs/README.md`, `docs/architecture.md`, and
`docs/agent-guidelines.md` before making structural changes.

## Security

Do not commit real API keys, `.env.local`, `.watch-video/` artifacts, media
files, transcripts, frames, caches, or local build outputs. Keep CI no-secret and
free of live Groq/video/Claude requirements. See [docs/security.md](docs/security.md).

## Checks

```sh
make test
make syntax
make mcp-build
make build-packages
make verify-packages
make audit-generated
make verify-generated-clean
```
