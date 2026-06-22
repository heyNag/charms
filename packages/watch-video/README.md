# watch-video

`watch-video` is a local video inspection package for agents. It turns a URL or
local video into a small evidence bundle:

- metadata
- focused audio clip
- transcript JSON and Markdown
- optional frames
- a concise report

The package root is a Claude Code plugin source. The portable skill source is:

```text
packages/watch-video/skills/watch-video
```

Codex, Cursor, OpenCode, generic Agent Skills, and optional Skillshare installs
all use that same skill folder directly or through the root `skills/` symlink
index. Claude Desktop custom-skill ZIP contents are built locally under
`.dist/claude/custom-skills/watch-video`.

Install commands for each target live in
[docs/installing-skills.md](../../docs/installing-skills.md).

## Requirements

```sh
brew install yt-dlp ffmpeg jq
python3 packages/watch-video/skills/watch-video/scripts/doctor.py
```

Groq is the default transcription fallback when captions are missing or
incomplete:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

OpenAI transcription is optional with `--transcriber openai` and
`OPENAI_API_KEY`; it defaults to `whisper-1` for verbose JSON segment
timestamps.

## Quickstart

From the repo root:

```sh
python3 packages/watch-video/skills/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

From the skill folder:

```sh
cd packages/watch-video/skills/watch-video
python3 scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" --duration 30 --transcriber none
```

Focused examples:

```sh
python3 scripts/watch.py ./screen-recording.mov --start 00:15 --end 00:45 --mode ui-bug --frame-format png
python3 scripts/watch.py "$URL" --mode tutorial --duration 60 --transcriber groq
python3 scripts/watch.py "$URL" --transcriber none --frame-mode interval --frame-interval 10
```

Common options:

- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--frame-mode auto|interval`
- `--fps` for an explicit FPS override, capped at 2
- `--resolution` as an alias for `--frame-width`
- `--frame-format jpeg|png|webp`
- `--cleanup` and `--cleanup-frames`

Outputs are written under `.watch-video/runs/<run-id>/` by default.

## Package Files

```text
.claude-plugin/plugin.json       Claude Code plugin metadata
skills/watch-video/SKILL.md      skill instructions
skills/watch-video/scripts/      local helper CLIs
commands/                        Claude Code slash command prompts
tests/                           offline helper tests
tool.json                        package manifest
```

After editing source:

```sh
make build-packages
make public-check
```
