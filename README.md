# agent-tools

`agent-tools` is a personal agent tooling workspace for skills, commands,
plugins, helper scripts, and MCP experiments.

This repo is intentionally practical and file-first. Local agent packages live
under `packages/`; deployable MCP server shapes live under `mcp/`; helper
scripts live under `scripts/`. There is no MCP gateway for now.

## Current Contents

- `packages/watch-video` - local video analysis skill, commands, plugin
  metadata, Python scripts, and tests.
- `mcp/watch-video` - minimal TypeScript MCP placeholder with a status tool and
  deployable folder shape for later.

## Quickstart

Install local dependencies on macOS:

```sh
brew install yt-dlp ffmpeg jq
```

Set a Groq key for Whisper fallback:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

Run a 30-second `watch-video` test:

```sh
python3 packages/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --frames \
  --frame-interval 10 \
  --max-frames 4
```

Install local copies into Claude and Codex:

```sh
./scripts/install-all.sh
```

## Repo Structure

```text
packages/             local skills, commands, plugins, and package tests
mcp/                  deployable MCP server shapes, one folder per MCP
scripts/              install, test, and helper scripts
docs/                 orientation and project memory
.github/workflows/    CI
```

## Docs

Start with [docs/README.md](docs/README.md).

Future agents should read `docs/README.md`, `docs/architecture.md`, and
`docs/agent-guidelines.md` before making structural changes.

## Security

Do not commit real API keys, `.env.local`, or `.watch-video/` artifacts. Keep CI
offline and no-secret. See [docs/security.md](docs/security.md).

## Checks

```sh
make test
make syntax
make mcp-build
```
