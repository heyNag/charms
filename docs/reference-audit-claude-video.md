# Claude Video Reference Audit

Date: 2026-06-19

Reference repo: `/Users/nag/Documents/claude-video`

Target repo: `/Users/nag/projects/personal/agent-tools`

This audit compares the local `claude-video` reference implementation with the
current `watch-video` package. The goal is to learn useful patterns while
preserving the `agent-tools` architecture:

- `packages/watch-video` remains the local skill, commands, and plugin source of
  truth.
- `mcp/watch-video` remains a minimal deployable MCP placeholder.
- `scripts/` remains helper, install, and test tooling.
- `docs/` remains project memory and orientation.
- No MCP gateway is planned now.

No files in `/Users/nag/Documents/claude-video` were modified.

## Reference Strengths

The reference repo is a polished Claude-focused video analysis skill. The
strongest ideas are:

- Clear `/watch` workflow with setup preflight, invocation steps, frame-reading
  guidance, failure handling, token budgeting, and cleanup guidance.
- A dedicated setup script that checks `yt-dlp`, `ffmpeg`, `ffprobe`, and API key
  readiness before each run, while staying silent on success.
- Duration-aware frame budgets. Short clips get denser frame coverage, long
  videos stay sparse, and extraction is capped at 100 frames and 2 fps.
- Safer downloader behavior, including `--` before URLs, treating subtitle-only
  `yt-dlp` failures as warnings when a video file exists, and preferring English
  VTT captions when multiple subtitle files are present.
- Whisper fallback with a small mono audio payload, verbose JSON, timestamped
  segments, retry handling, rate-limit handling, and a non-default User-Agent for
  Groq requests.
- Practical packaging around Claude and Codex plugin manifests, hook metadata,
  and a release/build script.
- User-facing docs that explain when to run focused ranges, how frame count
  affects cost, and what data leaves the machine.

## What Agent Tools Already Covers

`agent-tools` already covers the core shape needed for a practical local agent
workspace:

- `packages/watch-video/SKILL.md` describes a tool-neutral skill for YouTube
  URLs, local videos, screen recordings, tutorials, demos, and UI bug videos.
- `watch.py` accepts URL or local path sources, `--start`, `--end`,
  `--duration`, `--out-dir`, `--transcriber groq|none`, `--frames`,
  `--frame-interval`, `--max-frames`, and `--frame-width`.
- URL handling uses `yt-dlp` with native and auto captions, metadata capture,
  and `--` before the URL.
- Local videos are handled without requiring network access.
- Audio extraction uses `ffmpeg`, and Groq transcription uses the OpenAI-compatible
  Groq endpoint with `response_format=verbose_json`.
- Default Groq model is `whisper-large-v3-turbo`, matching the repo decision.
- Outputs are predictable under `.watch-video/runs/<run-id>/` and include
  `metadata.json`, `audio.mp3`, `transcript.json`, `transcript.md`, `report.md`,
  and `frames/`.
- Tests cover importability, time parsing, range normalization, frame count caps,
  run directory collision handling, transcript formatting, VTT parsing, rolling
  auto-caption cleanup, report artifact paths, and missing Groq key errors.
- CI is offline and does not require secrets.
- Docs already explain architecture, security, roadmap, local live testing, and
  MCP placeholder direction.

## Changes Applied During This Audit

Two small hardening changes were made because they are simple, testable, and
directly useful:

- Lowered the hard frame cap from 200 to 100. This keeps visual extraction closer
  to a safe agent context budget while preserving the default 80-frame behavior.
- Fixed caption selection so English VTT files are preferred when multiple VTT
  files exist. Non-English captions still work as fallback when no English VTT
  file is present.

These changes were implemented independently; no substantial reference code was
copied.

## Gaps Worth Considering

The following gaps are worth considering as future improvements:

- Setup and preflight ergonomics. The reference setup script provides a smooth
  first-run path and dependency diagnostics. `agent-tools` currently relies on
  README instructions, Make targets, and clear runtime errors.
- Duration-aware frame budgeting. `watch-video` currently uses a fixed frame
  interval plus a max-frame cap. The reference's adaptive budget is better for
  both short dense clips and long sparse scans.
- Groq retry handling. `groq_transcribe.py` has clear errors but does not yet
  retry transient HTTP, network, or 429 failures.
- Caption fallback richness. `watch-video` prefers captions before Groq, but
  language fallback and subtitle failure reporting could be more expressive.
- Report quality. The current report is readable and artifact-oriented, but it
  could eventually include richer visual summaries, key frames, or more explicit
  "what to inspect next" sections.
- Plugin packaging. The current Claude plugin metadata is intentionally minimal.
  The reference has fuller marketplace-style packaging and hooks.

## Intentionally Deferred

These reference features should not be copied into `agent-tools` right now:

- A Claude-specific setup wizard that writes API keys into a new config location.
  This repo's current security model favors environment variables and gitignored
  `.env.local` for local live tests.
- OpenAI Whisper fallback. Groq `whisper-large-v3-turbo` is the current default
  decision; other providers can be added later if needed.
- Session hooks that run on every Claude startup. They may be useful later, but
  install behavior should stay predictable and tool-neutral for now.
- Marketplace/release packaging. Useful eventually, but not needed for the
  personal workspace phase.
- Any MCP gateway. Real MCP tools can be added under `mcp/watch-video` later,
  but a gateway is explicitly not planned now.

## License And Attribution

The reference repo appears to be MIT licensed with copyright held by Bradley
Bonanno. It was inspected as design inspiration only.

No substantial code was copied into `agent-tools` during this audit. If future
work copies or adapts reference code directly, preserve the MIT license notice
and document the copied source in the relevant file or docs.

## Recommended Improvements

P0: correctness and safety

- Keep `yt-dlp` invocation guarded with `--` before user-provided URLs.
- Keep secrets out of logs, docs, committed files, reports, and CI.
- Keep generated `.watch-video/` artifacts ignored and untracked.
- Keep frame extraction capped at 100 frames or lower unless a user explicitly
  asks for a larger local-only experiment.
- Add tests around any future downloader, caption, transcript, or artifact path
  behavior changes.

P1: usability

- Add an optional `watch-video doctor` or `scripts/setup` style preflight that
  checks `yt-dlp`, `ffmpeg`, `ffprobe`, and `GROQ_API_KEY` without printing
  secrets.
- Consider adaptive frame budgeting for short, medium, long, and focused clips.
- Add retry and rate-limit handling to Groq transcription.
- Improve caption diagnostics so reports distinguish "no captions", "caption
  download warning", and "caption parse failed".
- Add a concise report section optimized for tutorial extraction and UI bug
  evidence.

P2: nice-to-have

- Add optional provider abstraction for future transcription backends.
- Add richer plugin packaging once local usage stabilizes.
- Add optional image contact sheets or thumbnails for easier frame browsing.
- Add real MCP tools under `mcp/watch-video` when the local script API is stable.
- Explore Railway or similar deployment only after real MCP tools exist.
