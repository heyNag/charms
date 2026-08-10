---
name: watch-video
description: Use when the user asks to inspect a YouTube URL, local video, screen recording, tutorial, demo, UI bug video, or visible/spoken video evidence.
license: MIT
compatibility: Requires Python 3.11+, yt-dlp, ffmpeg, and ffprobe on macOS or Linux; remote videos and optional Groq or OpenAI transcription require network access.
---

# watch-video

Use this skill when a user asks you to analyze a video URL, local video, screen
recording, tutorial, demo, UI bug recording, product walkthrough, or any task
where visible UI/actions and spoken content matter.

## Locating The Scripts

Every command below runs a script under this skill's `scripts/` directory,
which sits next to this `SKILL.md`. Resolve that skill directory and run scripts
relative to it; do not rely on a client-specific environment variable.
Supported platforms are macOS and Linux.

## Operating Rules

- Ask the user which detail level to run for each new video (see "Ask The
  Detail Level First"); skip the question only when the request or
  environment already answers it.
- Prefer native captions/transcripts when available. For URLs the script
  probes captions first and skips the media download when usable captions
  cover transcript detail and no cue timestamps are pinned.
- Use `yt-dlp` for URL metadata, captions, and media; `ffmpeg`/`ffprobe` for
  audio clips and frames.
- Use Groq Whisper as the default fallback when captions are missing or
  obviously incomplete. Audio beyond the 24 MiB safety threshold, which is
  below providers' 25 MB upload limit, is chunked and stitched automatically;
  partial chunk failures degrade to a partial transcript instead of failing
  the run.
- Use OpenAI transcription only when explicitly requested with
  `--transcriber openai`.
- Default Groq model: `whisper-large-v3-turbo`. Default OpenAI model:
  `whisper-1` (verbose JSON segment timestamps are needed).
- Support focused ranges with `--start` and `--end`; use `--duration` when the
  user gives a start plus length. Finite URL ranges download only that section.
- Do not paste the full transcript unless the user explicitly asks for it.
- Do not print or expose `GROQ_API_KEY` or `OPENAI_API_KEY`.
- For videos longer than 10 minutes, ask for or infer a focused range before
  frame-heavy extraction.
- For videos longer than 30 seconds, review captions/transcript before
  expanding frame extraction.
- For screen recordings or UI text, prefer PNG frames at higher resolution:
  `--frame-format png --resolution 1024`.
- If a follow-up question asks about evidence already captured, answer from the
  frames and transcript in context. Run a focused second pass only when the new
  question needs visual evidence that was not captured.
- Run artifacts (downloaded media and frames) accumulate outside the plugin
  under `$WATCH_VIDEO_RUNS_DIR` when set, otherwise under
  `$XDG_STATE_HOME/watch-video/runs/` or `~/.local/state/watch-video/runs/`.
  Once follow-ups are done, use `--cleanup` to remove media and audio, add
  `--cleanup-frames` to remove frames, or delete the run directory to remove
  every artifact. Keep media when a `--from-run` second pass is likely.

## Detail Dial

`--detail` trades token cost against visual fidelity:

- `transcript` - no sampled frames unless `--timestamps` pins cue frames; with
  usable captions and no pinned cue timestamps, URLs skip media. If captions
  are missing or weak, URLs download only audio for Whisper.
- `efficient` - keyframe-first decode with uniform fallback when fewer than
  four keyframes are available, cap 50 frames. Best default for "what is this
  video about".
- `balanced` - scene-change detection with uniform fallback for static
  footage, cap 80. Use when visuals actually matter.
- `full` - detected scene-change coverage, cap 300. For long, important videos
  where broader visual coverage is worth the context cost.

Every sampled-frame engine drops near-duplicate candidates (held slides, static
screens) before spending the frame cap and reports how many were dropped.
Pinned transcript-cue frames are not deduplicated. Pass `--no-dedup` only when
near-duplicate sampled candidates are useful; engine selection and frame caps
still apply.

## Ask The Detail Level First

Before running the script on a new video, ask the user which detail level to
use through the host's normal user-input mechanism. Present the four levels
lightest to heaviest so the order
itself reads as the cost dial, keep the recommendation label on `balanced`
even though it is not first, and include the cost hints:

1. `transcript` - fastest, lowest cost; no sampled frames, and URLs with usable
   captions skip media when no cue timestamps are pinned.
2. `efficient` - keyframe-first skim with uniform fallback; up to 50 frames,
   low cost.
3. `balanced` (Recommended) - scene-aware frames; up to 80, moderate cost.
4. `full` - detected scene changes; up to 300 frames, high context cost.

Skip the question and just run when:

- the user already named a level or passed `--detail`;
- the request clearly implies one ("just summarize what they say" ->
  `transcript`; "I need every frame" -> `full`);
- `WATCH_VIDEO_DETAIL` is set - treat it as the user's standing answer;
- you are re-running the same video for a follow-up or a focused second pass -
  reuse the earlier choice;
- nobody can answer (non-interactive or autonomous run) - use `balanced` and
  say so when you report back.

For videos longer than 10 minutes, fold the focused-range question into the
same prompt instead of asking twice.

## Whisper Key Setup (Ask Once)

A key is needed only when a video has no usable captions and transcription
matters. When that happens and no key is available (environment or stored),
ask the user once through the host's normal user-input mechanism with three
options:

1. Groq key (Recommended - cheaper and faster; <https://console.groq.com/keys>)
2. OpenAI key (<https://platform.openai.com/api-keys>)
3. Skip transcription for this video (captions/frames only)

If they provide a key, store it once for subsequent runs of this skill on the
same machine and user profile:

```sh
python3 scripts/doctor.py --set-key groq    # reads the key from stdin
```

The key defaults to `~/.config/watch-video/.env` with mode 600;
`WATCH_VIDEO_CONFIG_DIR` overrides the configuration directory, and environment
variables still take precedence over the stored value. Never echo the key back,
never commit it, and confirm only the safe shape (Groq keys start with `gsk_`,
OpenAI keys with `sk-`). If the user skips, run with `--transcriber none` and
only raise the question again when a later video actually needs transcription.

## Invocation

From this skill directory:

```sh
python3 scripts/watch.py "<source>"
```

Useful patterns:

```sh
python3 scripts/doctor.py
python3 scripts/watch.py "<source>" --detail transcript
python3 scripts/watch.py "<source>" --detail efficient
python3 scripts/watch.py "<source>" --start 01:15 --end 02:00
python3 scripts/watch.py "<source>" --duration 30 --max-frames 8
python3 scripts/watch.py "<source>" --mode tutorial
python3 scripts/watch.py "<source>" --mode ui-bug --frame-format png --resolution 1024
python3 scripts/watch.py "<source>" --transcriber none
```

CLI option surface:

- `--detail transcript|efficient|balanced|full`
- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes` (report scaffold)
- `--timestamps T1,T2,...` to pin frames at exact moments
- `--from-run DIR` to reuse a prior run's usable media; runs without media and
  focused URL downloads are rejected
- `--start/--end/--duration` for focused ranges
- `--max-frames N` cap override (hard caps: 100, or 300 in full detail)
- `--resolution` (alias `--frame-width`), default 512
- `--frame-format jpeg|png|webp`
- `--sub-langs` yt-dlp caption selector (default English variants)
- `--no-dedup`, `--no-frames`; `--frame-mode interval` with `--frame-interval`,
  or `--fps` (uniform-sampling overrides)
- `--out-dir DIR` for a custom run-artifact base; `WATCH_VIDEO_RUNS_DIR` or
  `XDG_STATE_HOME` can set the default base
- `--cleanup` removes media and audio; add `--cleanup-frames` to remove frames

The script writes a run directory outside the plugin under
`$WATCH_VIDEO_RUNS_DIR`, `$XDG_STATE_HOME/watch-video/runs/`, or the fallback
`~/.local/state/watch-video/runs/`, then prints the final `report.md`. Quote
URLs in zsh and other shells where `?` may be treated as a glob.

## Transcript-Cue Frames

Scene detection can miss the moment a presenter points at something, because
"look here" is often a low visual change. Catch those with a two-pass flow:

1. Run once and read `transcript.md`. `--detail transcript` is the lowest-cost
   choice, but a URL with usable captions run at that level without pinned cue
   timestamps retains no media.
2. Scan for deictic cues - "look here", "as you can see", "watch this",
   "notice" - and judge which ones matter. That judgment is yours, not a
   regex.
3. If the earlier run retained full, untrimmed media, re-run with
   `--timestamps 4:32,7:10 --from-run <previous-run-dir>` using absolute source
   times. Otherwise rerun the original source with `--timestamps 4:32,7:10`
   and omit `--from-run`.

Cue frames use the frame cap before sampled frames, bypass deduplication, and
are labeled `transcript-cue` in the report. If requested cues exceed the cap,
an evenly spaced subset is kept. With `--detail transcript --timestamps ...`,
the selected cue frames are the only frames.

## Token Efficiency

Frame count and pixel dimensions increase context cost, but exact image-token
accounting depends on the host and model. At the same aspect ratio, a
1024px-wide frame contains roughly four times as many pixels as a 512px-wide
frame. Raise resolution only when on-screen text must be read. Prefer
`transcript` or `efficient` detail for skims, a focused `--start/--end` range
over a sparse full-video scan, and avoid rerunning for evidence already in
context.

## Evidence To Use

Inspect `report.md` first. If frames were extracted, inspect every frame image
before answering visual questions, in parallel when the host supports it;
frames are chronological and timestamped in the filename. Use
`transcript.md` for spoken content, but summarize and cite timestamp ranges
rather than dumping the full transcript.

## Response Shape

Unless the user asks for a narrower format, return:

1. Summary
2. Timeline with timestamps
3. Visible UI/actions
4. Commands/tools mentioned
5. Implementation steps or reproduction steps
6. Uncertainty and what would improve confidence

For UI bug videos, include the observed symptom, timestamped evidence, likely
cause, and next debugging checks. For tutorials, extract the commands, tools,
setup steps, decisions, and a compact implementation checklist.

## Failure Handling

- First run: use `python3 scripts/doctor.py` for dependency and safe key-shape
  checks.
- Missing `yt-dlp`, `ffmpeg`, or `ffprobe`: run
  `python3 scripts/doctor.py --install`. It uses Homebrew when available on
  macOS; otherwise it prints manual commands. On Linux it prints commands but
  never executes `sudo`. Other operating systems are reported as unsupported.
- Missing Whisper key when transcription is needed: run the ask-once flow in
  "Whisper Key Setup"; if the user declines, continue with captions/frames
  and note that transcription was skipped.
- Groq API failure: do not retry indefinitely; report the error category and
  use available captions/frames. On chunked audio, partial results are kept.
- No captions on a non-English video: pass `--sub-langs` for that language
  (for example `"es,es.*"`) or rely on the Whisper fallback.
- Subtitle failures are isolated from the later media download because media
  fetches never request subtitles; a complete metadata/caption probe failure
  can still stop the run.
- Login-required, private, or region-locked URL: say `yt-dlp` cannot fetch it
  without access and ask for a local file or accessible URL.

## Security And Data Flow

- `yt-dlp` communicates with the source host to fetch metadata, captions, and
  media. Downloaded media, frames, transcripts, and reports remain under the
  local run directory.
- When captions are missing or weak and hosted Whisper fallback is enabled, the
  extracted audio clip is uploaded to the selected provider. Groq keys go only
  to `api.groq.com`; OpenAI keys go only to `api.openai.com`.
- Stored keys default to `~/.config/watch-video/.env` with mode 600 and can be
  relocated with `WATCH_VIDEO_CONFIG_DIR`. They are written only by
  `doctor.py --set-key` from stdin; environment variables take precedence.
- Never print keys or place run artifacts inside a repository. Default run
  storage is outside the plugin package.
