# Video Tool Reference Audit

Date: 2026-06-19

References inspected:

- `https://github.com/Newuxtreme/watch-video-skill`
- `https://github.com/jordanrendric/claude-video-vision`

Target repo:

- `https://github.com/heyNag/agent-tools`

This audit compares the current `watch-video` implementation with two public
video-oriented agent tools. The references were used for design inspiration
only. No substantial code was copied wholesale.

The `agent-tools` architecture remains unchanged:

- `packages/watch-video` is the source of truth.
- `plugins/watch-video` is the generated Claude Code plugin package.
- `codex/watch-video` is the generated Codex/generic skill package.
- `.claude-plugin/marketplace.json` is the generated marketplace catalog.
- `mcp/watch-video` is a minimal future MCP placeholder.
- There is no MCP gateway.

## Newuxtreme/watch-video-skill

What it does well:

- Provides a practical `/watch` workflow with strong first-run setup guidance.
- Includes a preflight/setup script that checks `yt-dlp`, `ffmpeg`, `ffprobe`,
  and API key readiness without exposing secrets.
- Uses duration-aware frame budgets with hard caps, making short clips dense and
  long clips sparse.
- Keeps frame extraction bounded around 100 frames and 2 fps.
- Has clear cleanup behavior for temporary work directories.
- Treats transcripts and frames as evidence rather than pretending the script
  can fully interpret visuals.
- Includes retry/rate-limit handling around transcription calls.

## jordanrendric/claude-video-vision

What it does well:

- Has rich Claude-oriented workflows and clear command ergonomics.
- Encourages transcript/caption review before expensive or frame-heavy visual
  extraction on longer videos.
- Prefers manual English captions, then English auto-captions, then other
  captions as fallback.
- Tracks caption provenance and coverage.
- Supports multiple frame formats, including PNG for UI text and optional WebP.
- Sketches useful future MCP concepts such as `video_info`, `video_analyze`,
  `video_watch`, and `video_detail`.
- Separates detailed video inspection from higher-level agent interpretation.

## What watch-video Already Did Well

- Keeps `packages/watch-video` as source of truth and regenerates public Claude
  and Codex install targets.
- Supports YouTube URLs and local video paths.
- Uses `yt-dlp` with `--` before user-provided URLs.
- Extracts metadata, audio, transcripts, frames, and a Markdown report into
  predictable `.watch-video/runs/<run-id>/` folders.
- Uses native captions before paid Whisper fallback.
- Uses Groq `whisper-large-v3-turbo` as the default fallback model.
- Keeps CI offline and no-secret.
- Includes tests for parsing, run directory safety, captions, reports, and
  helper behavior.

## Improvements Adopted Now

- Added `scripts/doctor.py` for local preflight checks.
- Added `make doctor`.
- Added automatic frame budgeting with hard caps of 100 frames and 2 fps.
- Kept manual interval mode through `--frame-mode interval`.
- Added `--fps`, capped at 2 fps.
- Added `--resolution` as an alias for `--frame-width`.
- Added `--frame-format jpeg|png|webp`, with JPEG default and PNG recommended
  for UI text.
- Improved finite-range URL handling with `yt-dlp --download-sections`.
- Improved caption selection and provenance: manual English, English variants,
  auto English, then fallback captions.
- Added caption coverage tracking and Groq/OpenAI fallback when captions are
  missing or suspiciously incomplete.
- Added Groq retry/rate-limit handling for HTTP 429, HTTP 5xx, network errors,
  and timeouts.
- Added optional OpenAI transcription with `--transcriber openai`, defaulting to
  `whisper-1` for verbose JSON segment timestamps.
- Added report modes: `general`, `tutorial`, `ui-bug`, and `notes`.
- Added optional cleanup with `--cleanup` and `--cleanup-frames`.
- Updated skill, commands, README, docs, tests, and generated public packages.

## Improvements Intentionally Deferred

- Real MCP video tools. The placeholder remains minimal; future tools can be
  added under `mcp/watch-video` when the local script API is stable.
- MCP gateway. Not planned now.
- Session cache/database and detailed `video_detail` drilldown. Useful later,
  but not needed for this simple public package.
- Full release automation and marketplace publishing workflows beyond generated
  committed package outputs.
- Contact sheets, visual clustering, OCR, or model-based frame understanding.
  These may be useful, but they would add complexity and new dependencies.
- Automatic installation or mutation of user shell/API key config. The doctor is
  read-only for now.

## License And Attribution

Both public reference repos were inspected as design references. This pass
implements original code in `agent-tools`; no substantial implementation code was
copied wholesale.

If future work copies or closely adapts code from either reference, preserve the
original license attribution in the adapted file and document the source here or
in a nearby notice.

## Future Roadmap Items

P0: correctness and safety

- Keep secret handling conservative: never print or commit keys.
- Keep `.watch-video/`, media, transcripts, frames, caches, and local env files
  ignored.
- Keep URL handling protected with `--` before user-provided URLs.
- Keep generated public packages verified against source.
- Keep CI free of live Groq/OpenAI/video network requirements.

P1: usability

- Improve report readability and artifact summaries.
- Add richer caption diagnostics when `yt-dlp` partially succeeds.
- Add better visual report aids, such as optional contact sheets.
- Improve tutorial and UI bug extraction prompts from real usage feedback.

P2: nice-to-have

- Add real `mcp/watch-video` tools: `video_info`, `video_analyze`,
  `video_watch`, and `video_detail`.
- Add optional Railway or similar deployment after real MCP tools exist.
- Add optional OCR or image-model integration only if a clear local workflow
  justifies the dependency.
