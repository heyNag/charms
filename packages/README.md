# Plugin packages

Each immediate child directory is a complete Agent Plugin v1 root and an
independently versioned and released product:

```text
packages/
├── chatgpt-pro-review/
├── codex-reset-credit/
├── mnemosyne-memory/
├── watch-video/
└── x-bookmarks/
```

Every plugin follows this repository contract:

```text
<name>/
├── plugin.json
├── LICENSE
├── README.md
├── skills/
│   └── <name>/
│       ├── SKILL.md
│       ├── scripts/       optional
│       ├── references/    optional
│       └── assets/        optional
└── tests/
```

`plugin.json` is the only plugin manifest and version source. Versions are
`MAJOR.MINOR.PATCH`, and releases are tagged `<name>--v<version>`. The sole
skill is an immediate child of `skills/` and has the same name as the plugin.
Charms currently bundles no MCP servers, so its plugin roots do not contain
`mcp.json`.

Packages carry no `.claude-plugin/` directory. After a plugin's first release,
the repository's `.claude-plugin/marketplace.json` lists it, pinned to its
latest release commit, for Claude Code and Codex installs.

See [Plugin format](../docs/plugin-format.md) for the complete package
invariants, [Development](../docs/development.md) for the validation
workflow, and [Releasing](../docs/releasing.md) for versions and releases.
