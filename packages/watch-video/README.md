# watch-video

`watch-video` is a local video inspection package for agents. It turns a URL or
local video into a small bundle of evidence:

- metadata
- focused audio clip
- transcript JSON and Markdown
- optional frames
- a concise report

It is designed for local use by Claude Code, Codex, OpenCode, and similar
agent tools. The skill format is portable; full video processing still needs a
local runtime with `yt-dlp`, `ffmpeg`, and `ffprobe`.

In the `agent-tools` repo, source lives under `packages/watch-video`. Public
install targets are generated from that source into
`generated/claude/plugins/watch-video`,
`generated/claude/custom-skills/watch-video`,
`generated/codex/skills/watch-video`, and `generated/agent-skills/watch-video`.

Claude Code marketplace metadata points at the generated plugin package under
`generated/claude/plugins/watch-video`. Codex users can copy
`generated/codex/skills/watch-video` into their local skills directory. Claude
Desktop / claude.ai custom skill users can ZIP
`generated/claude/custom-skills/watch-video`. OpenCode and generic Agent Skills
users can use `generated/agent-skills/watch-video`.

Skillshare users should install from the hub or direct source package path:

```sh
skillshare install heyNag/agent-tools/packages/watch-video --track
skillshare sync
```

Optional Claude Desktop no-terminal packaging: paste
`https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/watch-video`
into `https://skill-compiler.statechange.ai/`, preview the files, download the
`.skill`, and import it in Claude Desktop.

## Requirements

Run package-local commands from `packages/watch-video/` or from an installed
skill folder unless the command shows a repo-root path.

```sh
brew install yt-dlp ffmpeg jq
```

Set `GROQ_API_KEY` for Whisper fallback:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

Run preflight before the first real video:

```sh
python3 scripts/doctor.py
```

Groq is the default transcription fallback. OpenAI is optional with
`--transcriber openai` and `OPENAI_API_KEY`; it defaults to `whisper-1` for
verbose JSON segment timestamps.

## Quickstart

From the source package directory, Codex install, or agent-generic install:

```sh
python3 scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

From the generated Claude plugin package root, use the skill subdirectory:

```sh
python3 skills/watch-video/scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

Focused local examples:

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

## Source Files

```text
SKILL.md              # skill instructions for local agents
scripts/watch.py      # orchestration CLI
scripts/groq_transcribe.py
scripts/extract_frames.py
scripts/doctor.py
```

The source package also includes command prompts, plugin metadata, tests, and
`tool.json`.

Generated install packages contain a subset of those files:

- Claude plugin package: `README.md`, `LICENSE`, `.claude-plugin/plugin.json`,
  commands, and `skills/watch-video/`.
- Codex skill package: `README.md`, `LICENSE`, `SKILL.md`, and
  `scripts/`.
- Claude custom-skill package: `README.md`, `LICENSE`, lowercase `skill.md`,
  and `scripts/`.
- Agent-generic skill package: `README.md`, `LICENSE`, `SKILL.md`, and
  `scripts/`.
