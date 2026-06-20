# Watch Video

`watch-video` is the first local agent tool in this repo. It helps agents inspect
YouTube URLs, local videos, screen recordings, tutorials, demos, and UI bug
videos.

Source of truth:

```text
packages/watch-video
```

This source package has a `SOURCE.md` marker.

Public install targets:

```text
generated/claude/plugins/watch-video
generated/codex/skills/watch-video
```

These public install targets are generated from `packages/watch-video` and have
`GENERATED.md` markers. Edit the source package first, then run
`make rebuild-generated`. The generated markers list exact source paths, such as
`packages/watch-video/scripts/` producing
`generated/claude/plugins/watch-video/skills/watch-video/scripts/`.

When generator wording or public package paths change, always remove and
regenerate outputs with `make rebuild-generated`; do not move generated files or
edit them in place.

## Install

Claude Code marketplace install:

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

Codex or generic skill install:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/watch-video
cp -R generated/codex/skills/watch-video ~/.codex/skills/watch-video
```

Local development install from source:

```sh
./scripts/install-all.sh
```

Preflight:

```sh
python3 packages/watch-video/scripts/doctor.py
```

## Current Design

The `watch.py` flow is:

1. Accept a source URL or local path.
2. Parse focused range options early.
3. For finite URL ranges, pass `--download-sections` to `yt-dlp` where possible.
4. Extract metadata with `yt-dlp` for URLs and `ffprobe` for media details.
5. Prefer native captions, with manual English before auto English and fallback
   to other languages when needed.
6. Track caption provenance, language, coverage seconds, and coverage ratio.
7. Extract a focused audio clip with `ffmpeg`.
8. Use Groq Whisper fallback when captions are missing or suspiciously short.
9. Optionally use OpenAI transcription with `--transcriber openai`.
10. Extract frames with `ffmpeg` using automatic frame budgeting by default.
11. Generate transcript files and a Markdown report.

Default Groq model:

```text
whisper-large-v3-turbo
```

Default OpenAI transcription model:

```text
whisper-1
```

`whisper-1` is used for OpenAI because the current script needs verbose JSON
with segment timestamps.

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
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

If `GROQ_API_KEY` is only in `.env.local`, source it only inside the live command
subshell:

```sh
bash -lc 'set -a; source .env.local >/dev/null 2>&1; set +a; python3 packages/watch-video/scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" --duration 30 --transcriber groq --frame-mode auto --max-frames 8'
```

## Modes And Frames

Report modes:

```text
general
tutorial
ui-bug
notes
```

Frame extraction defaults to `--frame-mode auto`, capped at 100 frames and 2 fps.
Use `--frame-mode interval --frame-interval 10` when you need a predictable
interval. Use `--frame-format png --resolution 1280` for UI text. JPEG is the
default, PNG is best for sharp screen recordings, and WebP is optional depending
on the local `ffmpeg` build.

Use `--cleanup` to remove downloaded media and audio after the report is written.
Add `--cleanup-frames` only when frame files should also be removed.

Current CLI option surface:

- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--frame-mode auto|interval`
- `--fps` for explicit FPS, capped at 2
- `--resolution` as an alias for `--frame-width`
- `--frame-format jpeg|png|webp`
- `--cleanup` and `--cleanup-frames`

## Future Improvements

- Better visual report summaries.
- More transcript provider configuration.
- More robust caption fallback and language handling.
- Real MCP tools later under `mcp/watch-video`, such as `video_info`,
  `video_analyze`, `video_watch`, and `video_detail`.
- No MCP gateway.
