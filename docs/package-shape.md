# Package Shape

`agent-tools` uses packages as the durable source boundary.

```text
packages/<name>/
```

A package can own a skill, Claude Code slash commands, helper scripts,
references, agent UI metadata, plugin metadata, tests, and docs.

## Current Shape

```text
packages/<name>/
  README.md
  SOURCE.md
  tool.json
  .claude-plugin/
    plugin.json
  skills/
    <name>/
      SKILL.md
      scripts/       optional
      references/    optional
      agents/        optional
  commands/          optional Claude Code slash commands
  tests/             optional offline tests
```

The source skill is:

```text
packages/<name>/skills/<name>/SKILL.md
```

Do not add a duplicate root-level `packages/<name>/SKILL.md`.

## Why `packages/` Instead Of Top-Level `skills/`

The repo contains more than standalone skills. A package also needs Claude Code
plugin metadata, optional commands, tests, package docs, and future MCP
association. Keeping that bundle under `packages/<name>` makes the ownership
boundary clear while still exposing a standard `skills/<name>/SKILL.md` folder
inside the package.

## Source-Only Distribution

There is no committed `generated/` folder.

Target mapping:

```text
Claude Code marketplace source  -> packages/<name>
Codex skill source              -> packages/<name>/skills/<name>
OpenCode/generic skill source   -> packages/<name>/skills/<name>
Skillshare hub source           -> packages/<name>/skills/<name>
Claude Desktop local artifact   -> .dist/claude/custom-skills/<name>
```

`.dist/` is ignored and local-only.

## Adding Another Skill Inside A Package

If a package later owns multiple skills, add:

```text
packages/<name>/skills/<other-skill>/SKILL.md
```

Update `tool.json`, build checks, install docs, and release notes in the same
change. Do not leave unreferenced skill folders behind.
