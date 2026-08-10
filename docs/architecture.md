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

Each plugin has its own UTC date version, tag, release, archive, runtime
prerequisites, trust boundary, and failure surface. Host clients control
permissions for each installation. Installing one plugin never requires loading
the other four.

## Discovery

Agent Plugins uses fixed component locations. Clients load each package's
`plugin.json` first, then discover immediate skill directories under that
package's `skills/`. Only files within that package root participate in
discovery.

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

Each package's `plugin.json` and `skills/<name>/SKILL.md` form its canonical
portable metadata and discovery surface.

## Validation boundary

Repository validation is stricter than the portable minimum in deliberate
ways:

- every immediate child directory of `packages/` must be a plugin root;
- the directory name, manifest name, and single skill name must match;
- versions must use valid UTC `YYYY.M.D` date versioning with an optional
  same-day `.N` sequence;
- all discovered paths must remain inside their plugin root;
- symlinks and special files are rejected from release archives;
- manifest client-extension keys are allowed only in the v1 reverse-domain form;
- local credentials and runtime artifacts must remain untracked.

The vendored schema gives deterministic validation. The official Agent Skills
reference implementation validates every `SKILL.md`.
