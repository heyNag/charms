---
description: Analyze a UI bug or screen recording with timestamped visual evidence.
argument-hint: <video-url-or-path> [expected behavior]
allowed-tools: [Bash, Read]
---
<!-- BEGIN GENERATED FROM SOURCE: packages/watch-video/commands/ui-bug-video.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->


<!-- agent-tools-managed: watch-video command -->

Use `watch-video` on the UI bug recording: $ARGUMENTS

Prefer:

```sh
python3 scripts/watch.py "<source>" --mode ui-bug --frame-mode auto --frame-format png --resolution 1280
```

For recordings longer than 10 minutes, ask for or infer the relevant repro
window first. For videos longer than 30 seconds, inspect transcript/captions
before extracting a dense frame set.

Inspect frames closely and align them with the transcript if audio is present.
Return:

- observed symptom
- expected behavior if the user provided it
- timestamped evidence
- visible UI state, cursor/action sequence, and transitions
- likely cause ranked by confidence
- concrete next debugging checks
- uncertainty and missing evidence

Avoid over-claiming. If the video does not show enough detail, name the missing
logs, code path, browser console, network request, or repro step needed next.
