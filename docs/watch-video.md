# watch-video

`watch-video` inspects YouTube URLs, local videos, screen recordings,
tutorials, demos, and UI bug videos using local tools.

Source paths:

```text
packages/watch-video
packages/watch-video/skills/watch-video
```

## Flow

0. Ask the user which detail level to run (`transcript`, `efficient`,
   `balanced` recommended, `full`) unless the request or environment already
   answers it.
1. Accept a source URL or local file path.
2. Probe metadata and captions first (URLs download no media for
   caption-covered transcript requests; local files pick up sidecar
   subtitles).
3. Download only what the run needs: full media for frames, audio-only for
   Whisper, nothing when captions suffice.
4. Extract a focused audio clip when media is present.
5. Use Groq Whisper fallback when captions are missing or insufficient,
   auto-chunking audio past the 24 MB upload cap.
6. Extract bounded frames: scene-aware by default, keyframe-only at
   `--detail efficient`, uniform fallback for static footage, near-duplicates
   dropped, optional `--timestamps` cue pinning.
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

Full install commands for each target are in
[`installing-skills.md`](installing-skills.md).

- Claude Code: `/plugin install watch-video@charms`
- Codex: copy `packages/watch-video/skills/watch-video`
- Cursor: root `skills/watch-video` symlink through `.cursor-plugin/plugin.json`
- OpenCode: root plugin wrapper or copy `packages/watch-video/skills/watch-video`
- Claude Desktop: build `.dist/claude/custom-skills/watch-video`
- Skillshare: install `heyNag/charms/packages/watch-video/skills/watch-video`

## Requirements

```sh
brew install yt-dlp ffmpeg jq
python3 packages/watch-video/skills/watch-video/scripts/doctor.py
```

`doctor.py --install` installs missing binaries (brew on macOS, printed
commands elsewhere); `doctor.py --set-key groq` stores a Whisper key once in
`~/.config/watch-video/.env`.

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

- `--detail transcript|efficient|balanced|full`
- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--timestamps T1,T2,...`
- `--from-run DIR`
- `--sub-langs`
- `--max-frames`
- `--resolution` (default 512)
- `--frame-format jpeg|png|webp`
- `--no-dedup`
- `--cleanup`

## Future Improvements

- better visual report summaries
- deeper caption-fallback diagnostics
- real MCP tools later only if there is a concrete server-side workflow
