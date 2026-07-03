# watch-video

`watch-video` is a local video inspection package for agents. It turns a URL or
local video into a small evidence bundle:

- metadata
- focused audio clip
- transcript JSON and Markdown
- scene-aware frames with near-duplicate removal
- a concise report

Captions are probed before any download, so transcript-only requests on
captioned URLs never fetch media. Frame selection is content-aware: scene
changes by default, keyframe-only for fast skims, uniform sampling as the
static-footage fallback, with exact timestamps and a dedup pass that stops
held slides from burning the frame budget.

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
brew install yt-dlp ffmpeg jq   # or: python3 .../scripts/doctor.py --install
python3 packages/watch-video/skills/watch-video/scripts/doctor.py
```

Groq is the default transcription fallback when captions are missing or
incomplete:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

Or store the key once (written to `~/.config/watch-video/.env`, mode 600;
environment variables take precedence):

```sh
python3 packages/watch-video/skills/watch-video/scripts/doctor.py --set-key groq
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
python3 scripts/watch.py "$URL" --detail transcript                # captions only, no download
python3 scripts/watch.py "$URL" --detail efficient                 # fast keyframe skim
python3 scripts/watch.py ./screen-recording.mov --start 00:15 --end 00:45 --mode ui-bug --frame-format png
python3 scripts/watch.py "$URL" --mode tutorial --duration 60 --transcriber groq
python3 scripts/watch.py "$URL" --timestamps 4:32,7:10             # pin transcript-cue frames
```

Common options:

- `--detail transcript|efficient|balanced|full` (default `balanced`, or
  `WATCH_VIDEO_DETAIL`; agents ask the user per video unless the request
  already implies a level)
- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--timestamps T1,T2,...` to pin frames at exact moments
- `--from-run DIR` to reuse a previous run's media for a second pass
- `--sub-langs` yt-dlp caption selector (default English variants; pass
  `"es,es.*"` for a Spanish video)
- `--max-frames N` (hard caps: 100, or 300 in `full` detail)
- `--resolution` as an alias for `--frame-width` (default 512; 1024 for UI text)
- `--frame-format jpeg|png|webp`
- `--no-dedup`; `--frame-mode interval` with `--frame-interval`, or `--fps`
  (uniform-sampling overrides)
- `--start/--end/--duration` for focused ranges, `--out-dir` for artifacts
- `--cleanup` and `--cleanup-frames`

Whisper fallback audio larger than the 24 MB upload cap is chunked, stitched
back into source time, and tolerates partial chunk failures. Local videos pick
up sidecar subtitle files automatically (`video.en.vtt` next to `video.mp4`).

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
