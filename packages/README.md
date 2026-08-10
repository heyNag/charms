# Plugin packages

Each immediate child of this directory is a complete Agent Plugin v1 root and
an independently versioned product:

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

`plugin.json` is the only plugin manifest and version source. The sole skill
is an immediate child of `skills/` and has the same name as the plugin.
Charms currently bundles no MCP servers, so its plugin roots do not contain
`mcp.json`.

See [Plugin format](../docs/plugin-format.md) for the complete package
invariants and [Development](../docs/development.md) for the validation
workflow.
