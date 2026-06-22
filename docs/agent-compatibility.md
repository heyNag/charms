# Agent Compatibility

`agent-tools` keeps skill instructions portable and maps installation per
target.

## Source Pattern

```text
packages/<name>/
  .claude-plugin/plugin.json
  commands/                 optional Claude commands
  skills/<name>/
    SKILL.md
    scripts/                optional
    references/             optional
    agents/                 optional
```

## Surface Map

Claude Code:

```text
/plugin marketplace add heyNag/agent-tools
/plugin install watch-video@agent-tools
/plugin install codex-reset-credit@agent-tools
/plugin install x-bookmarks@agent-tools
```

Codex:

```sh
cp -R packages/watch-video/skills/watch-video ~/.codex/skills/watch-video
cp -R packages/codex-reset-credit/skills/codex-reset-credit ~/.codex/skills/codex-reset-credit
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

OpenCode:

```sh
cp -R packages/watch-video/skills/watch-video ~/.config/opencode/skills/watch-video
cp -R packages/codex-reset-credit/skills/codex-reset-credit ~/.config/opencode/skills/codex-reset-credit
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

Claude Desktop / claude.ai:

```sh
make build-packages
cd .dist/claude/custom-skills
zip -r watch-video.zip watch-video
zip -r codex-reset-credit.zip codex-reset-credit
zip -r x-bookmarks.zip x-bookmarks
```

Skillshare:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

## Runtime Boundary

The package format is portable. Live capability still depends on the host:

- `watch-video` needs local `yt-dlp`, `ffmpeg`, `ffprobe`, and optional API
  keys for transcription.
- `codex-reset-credit` needs local Codex auth/session state.
- `x-bookmarks` needs Bird browser-cookie access or local X API OAuth state.

Hosted or upload-only targets can carry instructions and files, but may not be
able to read local auth state or run local helper scripts.
