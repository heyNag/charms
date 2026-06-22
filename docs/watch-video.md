# watch-video

`watch-video` inspects YouTube URLs, local videos, screen recordings,
tutorials, demos, and UI bug videos using local tools.

Source paths:

```text
packages/watch-video
packages/watch-video/skills/watch-video
```

## Flow

1. Accept a source URL or local file path.
2. Fetch metadata where possible.
3. Prefer native captions/transcripts.
4. Extract a focused audio clip.
5. Use Groq Whisper fallback when captions are missing or insufficient.
6. Optionally extract bounded frames.
7. Write a report and artifacts under `.watch-video/runs/<run-id>/`.

Expected outputs:

```text
metadata.json
audio.mp3
transcript.json
transcript.md
report.md
frames/
```

## Install Paths

- Claude Code: `/plugin install watch-video@agent-tools`
- Codex: copy `packages/watch-video/skills/watch-video`
- OpenCode: copy `packages/watch-video/skills/watch-video`
- Claude Desktop: build `.dist/claude/custom-skills/watch-video`
- Skillshare: install `heyNag/agent-tools/packages/watch-video/skills/watch-video`

## Requirements

```sh
brew install yt-dlp ffmpeg jq
python3 packages/watch-video/skills/watch-video/scripts/doctor.py
```

Default Groq model:

```text
whisper-large-v3-turbo
```

## Short Test

```sh
python3 packages/watch-video/skills/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

Groq live test, only when `.env.local` exists and must not be printed:

```sh
bash -lc 'set -a; source .env.local >/dev/null 2>&1; set +a; python3 packages/watch-video/skills/watch-video/scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" --duration 30 --transcriber groq --frame-mode auto --max-frames 8'
```

## Useful Options

- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--frame-mode auto|interval`
- `--fps`
- `--resolution`
- `--frame-format jpeg|png|webp`
- `--cleanup`

## Future Improvements

- better visual report summaries
- configurable transcript providers
- robust caption fallback diagnostics
- real MCP tools later: `video_info`, `video_analyze`, `video_watch`,
  `video_detail`
