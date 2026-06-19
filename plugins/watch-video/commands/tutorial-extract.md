---
description: Extract setup steps, commands, tools, and implementation checklist from a tutorial video.
argument-hint: <video-url-or-path> [focus]
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: watch-video command -->

Use `watch-video` on the tutorial source: $ARGUMENTS

Prefer:

```sh
python3 scripts/watch.py "<source>" --mode tutorial --frame-mode auto
```

For tutorials longer than 10 minutes, ask for a focused section first unless the
user clearly wants a broad skim. Review transcript/captions before extracting
many frames.

Focus on practical extraction:

- tools, services, libraries, and versions mentioned
- setup commands and configuration files
- implementation sequence
- decisions, tradeoffs, and assumptions
- errors or warnings shown on screen
- a short checklist the user can follow

Use timestamps for evidence. Summarize transcript content; paste exact commands
only when visible or spoken clearly enough to be useful.
