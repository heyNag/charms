# Architecture

Charms is a monorepo containing five independent Agent Plugins. The repository
root owns shared development, validation, documentation, and release tooling.
It is not a plugin root.

```text
charms/
├── packages/
│   ├── chatgpt-pro-review/
│   ├── codex-reset-credit/
│   ├── mnemosyne-memory/
│   ├── watch-video/
│   └── x-bookmarks/
├── schemas/
│   └── agent-plugins/1.0.0/plugin.schema.json
├── scripts/
├── tests/
├── docs/
├── .github/workflows/
├── Makefile
└── requirements-dev.txt
```

## Product boundary

Each `packages/<name>/` directory is a self-contained plugin root with:

- one canonical `plugin.json`;
- one skill at `skills/<name>/SKILL.md`;
- every runtime script and reference needed by that skill;
- plugin-specific documentation, license, and offline behavior tests.

Each plugin has its own SemVer version, tag, release, archive, dependencies,
permissions, and failure surface. Installing one plugin never requires loading
the other four.

## Discovery

Agent Plugins uses fixed component locations. Clients load `plugin.json`
first, then discover immediate skill directories under `skills/`. Charms does
not use manifest fields to redirect discovery and does not expose a repository
root skill index.

Charms currently ships skills only. There is no `mcp.json` because none of
the five plugins bundles or connects an MCP server as a plugin component.
`mnemosyne-memory` instructs an agent to use a Mnemosyne server already
configured by the host; that runtime prerequisite is not a bundled server.

## Source of truth

For each plugin:

- identity, version, description, author, repository, license, and keywords
  come from `plugin.json`;
- activation metadata and operating instructions come from
  `skills/<name>/SKILL.md`;
- runtime behavior comes from files inside that skill directory;
- usage and prerequisites come from the package README;
- expected behavior comes from package tests.

There are no generated manifest mirrors, client-specific wrappers,
marketplaces, command catalogs, or aggregate plugin manifests.

## Validation boundary

Repository validation is stricter than the portable minimum in deliberate
ways:

- every immediate child of `packages/` must be a plugin root;
- the directory name, manifest name, and single skill name must match;
- versions must be valid Semantic Versioning;
- all discovered paths must remain inside their plugin root;
- symlinks and special files are rejected from release archives;
- client extension namespaces are allowed only in the v1 reverse-domain form;
- local credentials and runtime artifacts must remain untracked.

The vendored schema gives deterministic validation. The official Agent Skills
reference implementation validates every `SKILL.md`.
