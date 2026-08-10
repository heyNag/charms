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
  "homepage": "https://github.com/heyNag/charms/tree/main/packages/example-plugin",
  "repository": "https://github.com/heyNag/charms",
  "license": "MIT",
  "keywords": ["example"]
}
```

The v1 manifest schema is closed. Portable fields are limited to `$schema`,
`name`, `version`, `description`, `author`, `homepage`, `repository`,
`license`, `keywords`, and `extensions`. Component locations are fixed,
so the manifest does not declare a skill path.

Charms requires a SemVer `version` even though the base specification permits
other strings.

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

Charms does not use experimental tool preapprovals. Agents must apply their
host's normal permission and approval model to every operation.

## Paths and containment

Every file a client discovers or executes from a plugin must resolve inside
the plugin root. Do not use symlinks that escape the package, `../` component
paths, or runtime assumptions about the repository checkout.

Skill instructions resolve scripts and references relative to the skill root.
Runtime data, authentication, caches, and generated output live outside the
plugin package in the locations documented by the skill.

## MCP

An Agent Plugin may define bundled MCP connections with a root `mcp.json`,
but no current Charms plugin has one. Add `mcp.json` only when the plugin
actually supplies an MCP component and can meet the v1 transport, placeholder,
and path-containment contract.

## Client extensions

Client-specific data is permitted only through a reverse-domain key in
`plugin.json.extensions`, a top-level directory with the same namespace, or
both. Add an extension only against a published client contract and validate
the portable plugin without depending on that extension.
