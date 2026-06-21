# Target Tool Mapping

`agent-tools` keeps package instructions as agent-agnostic as practical. Source
skills should describe actions and evidence needs, while each target maps those
actions to its own tools, install shape, and runtime limits.

This repo currently targets:

```text
Claude Code
Claude Desktop / claude.ai custom skills
Codex
OpenCode / generic Agent Skills
```

Skillshare is an optional installer/discovery path, not a runtime target.

## Source Rule

Write source skills in `packages/<name>/SKILL.md` first.

Prefer action wording:

- read or inspect a file
- run a local command
- edit source files
- ask the user a question
- inspect generated artifacts
- report evidence and uncertainty

Avoid hard-coding one target's tool names in the main workflow unless the skill
is explicitly target-specific. Put target-specific notes in the package README,
the matching docs page, or this mapping doc.

## Discovery Metadata

`SKILL.md` frontmatter should help an agent decide whether to load the skill.

Use trigger-oriented descriptions:

```yaml
description: Use when the user asks to inspect a YouTube URL, local video, screen recording, tutorial, demo, UI bug video, or visible/spoken video evidence.
```

Avoid using the frontmatter description as a full workflow summary. Put workflow
steps in the body after the agent has already decided to load the skill.
`make verify-skill-metadata` enforces that public skill frontmatter
descriptions start with `Use when ` and describe trigger conditions.

Keep `tool.json` descriptions public-facing and human-readable. The build and
hub checks keep `tool.json`, `SKILL.md`, generated outputs, and
`skillshare-hub.json` aligned.

## Target Differences

| Action | Claude Code | Claude Desktop / claude.ai | Codex | OpenCode / generic |
|---|---|---|---|---|
| Install package | `/plugin install <name>@agent-tools` | Upload ZIP from `generated/claude/custom-skills/<name>` | Copy `generated/codex/skills/<name>` | Copy `generated/agent-skills/<name>` |
| Skill file | `skills/<name>/SKILL.md` inside plugin | lowercase `skill.md` | top-level `SKILL.md` | top-level `SKILL.md` |
| Commands | Claude slash command Markdown under `commands/` | No slash command wrapper from this repo | No slash command wrapper from this repo | No slash command wrapper from this repo |
| Local scripts | Best local target when shell access is available | Instruction bundle only unless the host exposes local tools | Best local target when shell access is available | Best local target when shell access is available |
| Local auth/files | Available when user grants local shell/file access | Usually unavailable in hosted Claude custom skill upload | Available in local Codex contexts when permitted | Available in local OpenCode contexts when permitted |
| Updates | Marketplace update/install flow | Rebuild/download/import a new skill ZIP | Pull repo and copy generated skill folder | Pull repo and copy generated agent-skill folder |

## Practical Mapping

| Skill action | Claude Code guidance | Codex guidance | OpenCode / generic guidance | Claude Desktop guidance |
|---|---|---|---|---|
| Read bundled instructions or references | Use the installed skill files | Use the installed skill files | Use the installed skill files | Use bundled files inside the uploaded skill |
| Run helper scripts | Run scripts from `skills/<name>/scripts/` in the Claude plugin or `packages/<name>/scripts/` in the repo | Run scripts from the copied Codex skill or repo package | Run scripts from the copied generic skill or repo package | Only possible if the host provides local execution |
| Edit repo source | Edit `packages/<name>/` | Edit `packages/<name>/` | Edit `packages/<name>/` | Usually not applicable from hosted custom skills |
| Rebuild generated outputs | `make rebuild-generated` from repo root | same | same | same before creating ZIPs |
| Verify generated outputs | `make public-check` | same | same | same |
| Ask for missing auth/context | Ask in chat and avoid printing secrets | Ask in chat and avoid printing secrets | Ask in chat and avoid printing secrets | Ask in chat and avoid printing secrets |

## Runtime Boundary

The package format can be portable even when the live behavior is not.

- `watch-video` needs local `yt-dlp`, `ffmpeg`, `ffprobe`, and optional
  transcription API keys for full behavior.
- `codex-reset-credit` needs local Codex auth/session state for live answers.
- `x-bookmarks` needs local Bird browser-cookie access or local X API OAuth
  state for live bookmark access.

Hosted or upload-only targets can carry instructions and scripts, but they may
not be able to run local helpers or read local auth state.

## No Global Bootstrap Today

Some multi-target skill projects inject a bootstrap instruction at session start
so a methodology skill auto-activates in every conversation. `agent-tools` does
not do that today.

Current skills are domain/task packages. They should be invoked by the user, by
target-native skill discovery, or by an agent deciding the trigger matches the
task. Do not add session-start hooks, global bootstrap injection, or target
runtime config mutation unless the user explicitly asks for that architecture.

If this repo later adds broad process skills that must auto-trigger, design that
as a separate target-porting project and keep it thin, target-specific, and
documented before implementation.
