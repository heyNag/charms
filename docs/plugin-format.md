# Plugin format

Every Charms package conforms to Agent Plugins v1 and contains exactly one
Agent Skill with the same name.

## Manifest

`plugin.json` is located at the plugin root:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "example-plugin",
  "version": "1.0.0",
  "description": "Short purpose statement.",
  "author": {
    "name": "Nagarjuna Boddu",
    "url": "https://github.com/heyNag"
  },
  "homepage": "https://github.com/heyNag/charms",
  "repository": "https://github.com/heyNag/charms",
  "license": "MIT",
  "keywords": ["example"]
}
```

The v1 manifest schema is closed. Portable fields are limited to `$schema`,
`name`, `version`, `description`, `author`, `homepage`, `repository`,
`license`, `keywords`, and `extensions`. Component locations are fixed,
so the manifest does not declare a skill path.

Charms requires `version` to be plain Semantic Versioning, `MAJOR.MINOR.PATCH`,
with no leading zeros and no prerelease or build suffix. Every plugin starts at
`1.0.0`. See [Releasing](releasing.md) for how versions advance.

## Skill

The skill is an immediate child of `skills/`:

```text
skills/
└── example-plugin/
    ├── SKILL.md
    ├── scripts/
    ├── references/
    └── assets/
```

Only `SKILL.md` is required. Its YAML frontmatter uses fields defined by the
Agent Skills specification:

```yaml
---
name: example-plugin
description: Use when the user needs an example task completed.
license: MIT
compatibility: Requires Python 3.11+ and network access.
---
```

The description states both what the skill does and when it should activate.
Runtime requirements belong in `compatibility`, while detailed operating
rules belong in the Markdown body.

Agents use their host's normal permission and approval model for every
operation.

## Paths and containment

Every file a client discovers or executes from a plugin must resolve inside
the plugin root. Do not use symlinks that escape the package, `../` component
paths, or runtime assumptions about the repository checkout.

Skill instructions resolve scripts and references relative to the skill root.
Runtime data, authentication, caches, and generated output live outside the
plugin package in the locations documented by the skill.

## MCP

Agent Plugins v1 defines bundled MCP connections through a root `mcp.json`.
The current Charms package contract is skill-only, so Charms validation does
not accept `mcp.json`.

## Client extensions

No current Charms plugin declares client-specific extension data. Both
packages depend only on the portable Agent Plugins manifest and fixed Agent
Skills component location.

Packages contain no client-specific surfaces such as `.claude-plugin/`,
`commands/`, or `tool.json`. Claude Code and Codex install them through the
repository's `.claude-plugin/marketplace.json`.
