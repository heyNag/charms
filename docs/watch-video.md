# Watch Video

`watch-video` is the first local agent tool in this repo. It helps agents inspect
YouTube URLs, local videos, screen recordings, tutorials, demos, and UI bug
videos.

Source of truth:

```text
packages/watch-video
```

## Current Design

The `watch.py` flow is:

1. Accept a source URL or local path.
2. Extract metadata with `yt-dlp` for URLs and `ffprobe` for media details.
3. Extract a focused audio clip with `ffmpeg`.
4. Prefer native captions when available.
5. Use Groq Whisper fallback when captions are missing.
6. Extract frames with `ffmpeg` when frames are enabled.
7. Generate transcript files and a Markdown report.

Default Groq model:

```text
whisper-large-v3-turbo
```

## Outputs

Each run writes under `.watch-video/runs/<run-id>/` by default:

```text
metadata.json
audio.mp3
transcript.json
transcript.md
report.md
frames/
```

`frames/` is present when frame extraction is enabled. All generated run
artifacts are ignored by git.

## Short-Range YouTube Test

Use this URL for short-range verification:

```text
https://www.youtube.com/watch?v=DTCyvo6cC54
```

Example:

```sh
python3 packages/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber groq \
  --frames \
  --frame-interval 10 \
  --max-frames 4
```

If `GROQ_API_KEY` is only in `.env.local`, source it only inside the live command
subshell:

```sh
bash -lc 'set -a; source .env.local >/dev/null 2>&1; set +a; python3 packages/watch-video/scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" --duration 30 --transcriber groq --frames --frame-interval 10 --max-frames 4'
```

## Future Improvements

- Better visual report summaries.
- Configurable transcript providers.
- More robust caption fallback and language handling.
- Real MCP tools later under `mcp/watch-video`.
