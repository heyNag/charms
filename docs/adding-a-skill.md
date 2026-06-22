# Adding A Skill

Use this checklist to add a new public skill package. The example package is
`awesome-skill`.

## What You Create

Create one source package:

```text
packages/awesome-skill/
  README.md
  SOURCE.md
  tool.json
  .claude-plugin/
    plugin.json
  skills/
    awesome-skill/
      SKILL.md
      scripts/       optional
      references/    optional
      agents/        optional
  commands/          optional
  tests/             recommended
```

Do not create a committed `generated/` folder.

With the standard targets, this one source package supports:

- Claude Code: package root `packages/awesome-skill`
- Codex: skill folder `packages/awesome-skill/skills/awesome-skill`
- OpenCode/generic Agent Skills: same skill folder
- Claude Desktop / claude.ai: local `.dist/claude/custom-skills/awesome-skill`
  artifact built by `make build-packages`
- Skillshare: hub entry pointing to
  `packages/awesome-skill/skills/awesome-skill`

## Step 1: Create Folders

```sh
mkdir -p packages/awesome-skill/.claude-plugin
mkdir -p packages/awesome-skill/skills/awesome-skill
mkdir -p packages/awesome-skill/tests
```

Add optional folders only when needed:

```sh
mkdir -p packages/awesome-skill/commands
mkdir -p packages/awesome-skill/skills/awesome-skill/scripts
mkdir -p packages/awesome-skill/skills/awesome-skill/references
mkdir -p packages/awesome-skill/skills/awesome-skill/agents
```

## Step 2: Add `tool.json`

Create `packages/awesome-skill/tool.json`:

```json
{
  "name": "awesome-skill",
  "description": "Describe the skill in one public-facing sentence.",
  "tags": ["awesome", "local"],
  "targets": ["claude", "codex", "generic"],
  "surfaces": ["claude-code", "claude-desktop", "codex", "opencode"],
  "agent_agnostic": true,
  "has_mcp": false,
  "public": true
}
```

## Step 3: Add Claude Plugin Metadata

Create `packages/awesome-skill/.claude-plugin/plugin.json`:

```json
{
  "name": "awesome-skill",
  "version": "0.1.0",
  "description": "Describe the skill in one public-facing sentence.",
  "author": {
    "name": "Nagarjuna Boddu"
  },
  "repository": "https://github.com/heyNag/agent-tools",
  "license": "MIT"
}
```

`0.1.0` is a bootstrap version for the add-skill commit. Public date versions
are assigned only by the manual `Release Skill` workflow.

## Step 4: Add `SKILL.md`

Create `packages/awesome-skill/skills/awesome-skill/SKILL.md`:

```markdown
---
name: awesome-skill
description: Use when the user asks for awesome-skill help or needs the awesome workflow.
argument-hint: "[optional args]"
tags: awesome, local
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
---

# Awesome Skill

Use this skill to ...
```

The `name` must match the folder name and `tool.json`. Tags must match
`tool.json`.

## Step 5: Add Docs And Tests

Add:

```text
packages/awesome-skill/README.md
packages/awesome-skill/SOURCE.md
packages/awesome-skill/tests/test_basic.py
docs/awesome-skill.md
```

If the skill has Claude Code slash commands, add them under:

```text
packages/awesome-skill/commands/
```

## Step 6: Register Release Workflow

Add `awesome-skill` to `.github/workflows/release-skill.yml` under the
`workflow_dispatch.inputs.skill.options` list.

## Step 7: Build And Verify

```sh
make build-packages
make public-check
git status
```

`make build-packages` refreshes `.claude-plugin/marketplace.json`,
`skillshare-hub.json`, and ignored `.dist/` Claude custom-skill artifacts.

## Step 8: Commit

Commit the source package, docs, updated indexes, tests, and workflow change.
Do not commit `.dist/`, ZIPs, local state, credentials, media, transcripts, or
caches.

## New Skill Checklist

- `packages/awesome-skill/tool.json` exists.
- `packages/awesome-skill/.claude-plugin/plugin.json` exists.
- `packages/awesome-skill/skills/awesome-skill/SKILL.md` exists.
- No root `packages/awesome-skill/SKILL.md` exists.
- Tags match between `tool.json` and `SKILL.md`.
- Docs mention source paths and install paths.
- `make public-check` passes.
