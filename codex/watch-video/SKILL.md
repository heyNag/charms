---
name: watch-video
description: Analyze YouTube URLs, local videos, screen recordings, tutorials, demos, and UI bug videos using yt-dlp, ffmpeg, native captions, frame extraction, and Groq Whisper fallback.
argument-hint: "<video-url-or-path> [--start T] [--end T] [question]"
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---
<!-- BEGIN GENERATED FROM SOURCE: packages/watch-video/SKILL.md -->
<!-- Do not edit directly; edit the source path and run make build-packages. -->
<!-- END GENERATED FROM SOURCE -->


# watch-video

Use this skill when a user asks you to analyze a video URL, local video, screen
recording, tutorial, demo, UI bug recording, product walkthrough, or any task
where visible UI/actions and spoken content matter.

## Operating Rules

- Prefer native captions/transcripts when available.
- Use `yt-dlp` for URL metadata, captions, and downloading source media.
- Use `ffmpeg`/`ffprobe` for focused audio clips and frame extraction.
- Use Groq Whisper as the default fallback when captions are missing,
  unavailable, or obviously incomplete.
- Use OpenAI transcription only when explicitly requested with
  `--transcriber openai`.
- Default Groq model: `whisper-large-v3-turbo`.
- Default OpenAI transcription model: `whisper-1`, because verbose JSON segment
  timestamps are needed.
- Support focused ranges with `--start` and `--end`; use `--duration` when the
  user gives a start plus length.
- Do not paste the full transcript unless the user explicitly asks for it.
- Do not print or expose `GROQ_API_KEY`.
- For videos longer than 10 minutes, ask for or infer a focused range before
  doing frame-heavy extraction.
- For videos longer than 30 seconds, review captions/transcript before expanding
  frame extraction.
- For screen recordings or UI text, prefer higher resolution and PNG frames:
  `--frame-format png --resolution 1280`.

## Invocation

From this skill directory:

```sh
python3 scripts/watch.py "<source>" --frames --frame-mode auto
```

Useful options:

```sh
python3 scripts/doctor.py
python3 scripts/watch.py "<source>" --start 01:15 --end 02:00 --frames
python3 scripts/watch.py "<source>" --duration 30 --frame-mode auto --max-frames 8
python3 scripts/watch.py "<source>" --mode tutorial --transcriber groq
python3 scripts/watch.py "<source>" --mode ui-bug --frame-format png
python3 scripts/watch.py "<source>" --transcriber none --frames
```

Current option surface:

- `--transcriber groq|openai|none`
- `--mode general|tutorial|ui-bug|notes`
- `--frame-mode auto|interval`
- `--fps` for explicit FPS, capped at 2
- `--resolution` as an alias for `--frame-width`
- `--frame-format jpeg|png|webp`
- `--cleanup` and `--cleanup-frames`

The script writes a run directory under `.watch-video/runs/<run-id>/` and prints
the final `report.md` path. For finite URL ranges, it asks `yt-dlp` for a
focused download section so short tests do not download whole long videos when
the service supports section downloads. Quote URLs in zsh and other shells where
`?` may be treated as a glob.

## Evidence To Use

Read `report.md` first. If frames were extracted, inspect the frame images from
`frames/` before answering visual questions. Use `transcript.md` for spoken
content, but summarize and cite timestamp ranges rather than dumping the full
transcript.

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
- Missing `yt-dlp`: tell the user to run `brew install yt-dlp`.
- Missing `ffmpeg` or `ffprobe`: tell the user to run `brew install ffmpeg`.
- Missing `GROQ_API_KEY`: continue with captions/frames if available and say
  Groq fallback needs `export GROQ_API_KEY=...`.
- Missing `OPENAI_API_KEY` with `--transcriber openai`: continue with
  captions/frames if available and say OpenAI fallback needs
  `export OPENAI_API_KEY=...`.
- Groq API failure: do not retry indefinitely; report the error category and use
  available captions/frames.
- Login-required, private, or region-locked URL: say `yt-dlp` cannot fetch it
  without access and ask for a local file or accessible URL.
