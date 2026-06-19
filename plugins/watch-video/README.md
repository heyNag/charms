# watch-video

`watch-video` is a local video inspection package for agents. It turns a URL or
local video into a small bundle of evidence:

- metadata
- focused audio clip
- transcript JSON and Markdown
- optional frames
- a concise report

It is designed for local use by Claude, Codex, and similar tools.

In the `agent-tools` repo, source lives under `packages/watch-video`. Public
install targets are generated from that source into `plugins/watch-video` and
`codex/watch-video`.

Claude Code users install from the marketplace package in `plugins/watch-video`.
Codex and generic skill users can copy `codex/watch-video` into their local
skills directory.

## Requirements

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

```sh
python3 scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" \
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

Outputs are written under `.watch-video/runs/<run-id>/` by default.

## Files

```text
SKILL.md              # skill instructions for local agents
scripts/watch.py      # orchestration CLI
scripts/groq_transcribe.py
scripts/extract_frames.py
scripts/doctor.py
```

The source package also includes command prompts, plugin metadata, tests, and
`tool.json`.
