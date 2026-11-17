# Plugin packages

Each immediate child is a product release boundary. Native products are
complete Agent Plugin v1 roots; pstack is a bundle with separate host roots:

```text
packages/
├── watch-video/
├── x-bookmarks/
└── pstack/
    ├── claude-code/
    └── codex/
```

The native watch-video and x-bookmarks plugins follow this contract:

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

For native packages, `plugin.json` is the only plugin manifest and version
source. Versions are `YEAR.MONTH.RELEASE`, such as `2026.11.0`, and releases are tagged
`<name>--v<version>`. The sole skill is an immediate child of `skills/` and
has the same name as the plugin. Charms currently bundles no MCP servers, so
its plugin roots do not contain `mcp.json`.

Native packages carry no `.claude-plugin/` directory. After a release is
published and verified, the repository's `.claude-plugin/marketplace.json` and
`.agents/plugins/marketplace.json` list the plugin at its latest release commit
for Claude Code and Codex respectively.

Pstack uses a trusted bundle profile: exact upstream Claude plus generated Codex,
one upstream lock and a separate bundle version. Its skills, dormant
resources, fixtures and host manifests are validated without weakening the
native plugin contract. See [pstack integration](../docs/pstack.md).

See [Plugin format](../docs/plugin-format.md) for the complete package
invariants, [Development](../docs/development.md) for the validation
workflow, and [Releasing](../docs/releasing.md) for versions and releases.
