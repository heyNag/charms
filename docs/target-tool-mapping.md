# Target Tool Mapping

`agent-tools` keeps skill instructions agent-agnostic where practical. Source
skills describe actions and evidence needs; each target maps those actions to
its own tools and runtime limits.

Targets:

```text
Claude Code
Claude Desktop / claude.ai custom skills
Codex
OpenCode / generic Agent Skills
```

Skillshare is an optional installer/discovery path, not a runtime target.

## Source Rule

Write source skills in:

```text
packages/<name>/skills/<name>/SKILL.md
```

Prefer action wording:

- inspect a file
- run a local command
- edit source files
- ask the user a question
- report evidence and uncertainty

Avoid hard-coding one target's tool names in the main workflow unless the skill
is target-specific.

## Target Differences

| Action | Claude Code | Claude Desktop / claude.ai | Codex | OpenCode / generic |
|---|---|---|---|---|
| Install | `/plugin install <name>@agent-tools` | Upload ZIP built from `.dist/claude/custom-skills/<name>` | Copy `packages/<name>/skills/<name>` | Copy `packages/<name>/skills/<name>` |
| Skill file | `skills/<name>/SKILL.md` inside package plugin | lowercase `skill.md` in ZIP artifact | top-level `SKILL.md` in copied folder | top-level `SKILL.md` in copied folder |
| Commands | `packages/<name>/commands/` | No slash command wrapper | No slash command wrapper | No slash command wrapper |
| Local scripts | Best local target with shell access | Only if host exposes local tools | Best local target with shell access | Best local target with shell access |
| Updates | Plugin update/reinstall flow | Rebuild/download and import new ZIP | Pull repo and copy skill folder | Pull repo and copy skill folder |

## Runtime Boundary

- `watch-video` needs local video binaries and optional transcription API keys.
- `codex-reset-credit` needs local Codex auth/session state.
- `x-bookmarks` needs local Bird browser-cookie access or local X API OAuth
  state.

Hosted or upload-only targets can carry instructions, but they may not be able
to run helpers or access local auth state.

## No Global Bootstrap Today

Current skills are task/domain packages. They should be invoked by the user, by
target-native skill discovery, or by an agent deciding the trigger matches the
task. Do not add session-start hooks or global bootstrap injection unless the
user explicitly asks for that architecture.
