---
description: Analyze a video URL or local video with watch-video.
argument-hint: <video-url-or-path> [question]
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: watch-video command -->

Use the `watch-video` skill with the user's arguments: $ARGUMENTS

Run the `watch.py` script from the installed `watch-video` skill, or
`packages/watch-video/skills/watch-video/scripts/watch.py` when working from
this repository.
Prefer captions, extract a focused audio clip, use Groq Whisper only when
captions are missing or incomplete, extract frames when visual evidence matters,
then answer from `report.md`, `transcript.md`, and the frame images.

For videos longer than 10 minutes, ask for or infer a focused range first. For
videos longer than 30 seconds, review transcript/captions before frame-heavy
extraction. Use `--frame-mode auto` by default, and use `--frame-format png` or
`--resolution 1280` when screen/UI text needs sharper frames.

Return a concise summary, timestamped timeline, visible UI/actions,
commands/tools mentioned, implementation or reproduction steps, and uncertainty.
Do not paste the full transcript unless requested.
