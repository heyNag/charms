# watch-video

`watch-video` is a local video inspection package for agents. It turns a URL or
local video into a small evidence bundle that can include:

- metadata
- a focused audio clip when usable media is available
- transcript JSON and Markdown
- scene-aware frames with near-duplicate removal
- a concise report

Captions and metadata are probed before any media download. For URLs with
usable captions, transcript detail skips media unless `--timestamps` pins cue
frames.
Frame selection is content-aware: scene changes by default, keyframe-first for
fast skims with uniform fallback when fewer than four keyframes are available,
and uniform sampling as the static-footage fallback. Sampled frame candidates
have exact timestamps and pass through deduplication so held slides do not burn
the frame budget; selected transcript-cue frames bypass deduplication.

This directory is an [Agent Plugins v1](https://agent-plugins.org/specification)
plugin root. A compatible client with Agent Skills support loads `plugin.json`
here and discovers the skill from the standard fixed location:

```text
skills/watch-video
```

The plugin is independently versioned. Installation and update behavior is
defined by the client loading this package.

## Requirements

Supported operating systems: macOS and Linux.

```sh
# macOS with Homebrew
brew install yt-dlp ffmpeg
python3 skills/watch-video/scripts/doctor.py
```

`doctor.py --install` installs missing binaries through Homebrew when it is
available on macOS. On Linux, and on macOS without Homebrew, it prints manual
installation commands and never executes `sudo`.

Groq is the default transcription fallback when captions are missing or
incomplete:

```sh
export GROQ_API_KEY="..."
export GROQ_MODEL="whisper-large-v3-turbo"
```

Or store the key once. By default it is written to
`~/.config/watch-video/.env` with mode 600; `WATCH_VIDEO_CONFIG_DIR` overrides
the configuration directory, and environment variables take precedence:

```sh
python3 skills/watch-video/scripts/doctor.py --set-key groq
```

OpenAI transcription is optional with `--transcriber openai` and
`OPENAI_API_KEY`; it defaults to `whisper-1` for verbose JSON segment
timestamps.

## Quickstart

From the plugin root:

```sh
python3 skills/watch-video/scripts/watch.py \
  "https://www.youtube.com/watch?v=DTCyvo6cC54" \
  --duration 30 \
  --transcriber none \
  --frame-mode auto \
  --max-frames 8
```

From the skill folder:

```sh
cd skills/watch-video
python3 scripts/watch.py "https://www.youtube.com/watch?v=DTCyvo6cC54" --duration 30 --transcriber none
```

Focused examples:

```sh
SOURCE_URL="https://www.youtube.com/watch?v=DTCyvo6cC54"
python3 scripts/watch.py "$SOURCE_URL" --detail transcript         # usable captions skip media; fallback may download audio
python3 scripts/watch.py "$SOURCE_URL" --detail efficient          # keyframe-first skim with uniform fallback
python3 scripts/watch.py ./screen-recording.mov --start 00:15 --end 00:45 --mode ui-bug --frame-format png
python3 scripts/watch.py "$SOURCE_URL" --mode tutorial --duration 60 --transcriber groq
python3 scripts/watch.py "$SOURCE_URL" --timestamps 4:32,7:10      # pin transcript-cue frames
```

Common options:

- `--detail transcript|efficient|balanced|full` (default `balanced`, or
  `WATCH_VIDEO_DETAIL`; agents ask the user per video unless the request
  already implies a level)
- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--timestamps T1,T2,...` to pin frames at exact moments
- `--from-run DIR` to reuse a prior run's usable media; runs without media and
  focused URL downloads are rejected
- `--sub-langs` yt-dlp caption selector (default English variants; pass
  `"es,es.*"` for a Spanish video)
- `--max-frames N` (hard caps: 100, or 300 in `full` detail)
- `--resolution` as an alias for `--frame-width` (default 512; 1024 for UI text)
- `--frame-format jpeg|png|webp`
- `--no-dedup` to keep near-duplicate sampled frames; `--frame-mode interval`
  with `--frame-interval`, or `--fps` (uniform-sampling overrides)
- `--start/--end/--duration` for focused ranges
- `--out-dir` for a custom artifact directory; `WATCH_VIDEO_RUNS_DIR` or
  `XDG_STATE_HOME` can set the default base
- `--cleanup` removes media and audio; add `--cleanup-frames` to remove frames

Fallback audio above the 24 MiB safety threshold is chunked to stay below the
providers' 25 MB upload limit, stitched back into source time, and tolerates
partial chunk failures. Local videos pick up sidecar subtitle files
automatically (`video.en.vtt` next to `video.mp4`).

Outputs are written outside the plugin under `$WATCH_VIDEO_RUNS_DIR` when set,
otherwise under `$XDG_STATE_HOME/watch-video/runs` or
`~/.local/state/watch-video/runs`.

## Portable package files

```text
plugin.json                      Agent Plugins v1 manifest
LICENSE                          MIT license terms
README.md                        requirements and usage guidance
skills/watch-video/SKILL.md      skill instructions
skills/watch-video/scripts/      local helper CLIs
```

## Development

In a Charms source checkout, run the package tests from the repository root:

```sh
python3 -m unittest discover -s packages/watch-video/tests -p 'test_*.py'
```
