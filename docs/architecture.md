# Architecture

Charms is a monorepo containing two independent Agent Plugins. The repository
root owns the shared marketplace and the development, validation,
documentation, and release tooling. It is not a plugin root.

```text
charms/
├── .claude-plugin/
│   └── marketplace.json
├── packages/
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

Each plugin has its own semantic version, release tag, GitHub release,
archive, marketplace entry, runtime prerequisites, trust boundary, and failure
surface. Host clients control permissions for each installation. Installing
one plugin never requires loading the other.

## Discovery

Agent Plugins uses fixed component locations. Clients load each package's
`plugin.json` first, then discover immediate skill directories under that
package's `skills/`. Only files within that package root participate in
discovery.

Charms currently ships skills only. There is no `mcp.json` because neither
plugin bundles or connects an MCP server as a plugin component.

## Marketplace

`.claude-plugin/marketplace.json` is the one marketplace, named `charms`, for
both Claude Code and Codex. Codex reads this Claude-format file natively. The
repository has no `.agents/plugins/marketplace.json`: Codex reads that path
first, so a second file there would shadow the shared one.

Each entry pins one released plugin with a `git-subdir` source:

```json
{
  "name": "watch-video",
  "description": "<description from plugin.json at the release commit>",
  "version": "<version>",
  "source": {
    "source": "git-subdir",
    "url": "https://github.com/heyNag/charms.git",
    "path": "packages/watch-video",
    "ref": "watch-video--v<version>",
    "sha": "<full release commit SHA>"
  }
}
```

Both clients install from the pinned `sha`, so marketplace installs only see
released, immutable content. Commits on `main` reach them only through a new
release. Only the release workflow writes entries, after the release is
published and verified. A plugin has no entry until its first release.

Skill-only channels such as Skillshare and the skills CLI read
`packages/<name>/skills/<name>/` from `main` and do not use the marketplace.

## Release model

A release is dispatched for one plugin from `main`. It runs the full CI on the
exact commit, publishes an immutable GitHub release tagged
`<name>--v<version>` with the plugin ZIP, verifies it, and then moves that
plugin's marketplace entry to the new release in a separate commit. Version
bumps are ordinary commits made before the release. See
[Releasing](releasing.md).

## Source of truth

For each plugin:

- identity, version, description, author, repository, license, and keywords
  come from `plugin.json`;
- activation metadata and operating instructions come from
  `skills/<name>/SKILL.md`;
- runtime behavior comes from files inside that skill directory;
- usage and prerequisites come from the package README;
- expected behavior comes from package tests;
- released versions are recorded by `<name>--v<version>` tags, and the
  marketplace entry copies `version` and `description` from `plugin.json` at
  the latest release.

Each package's `plugin.json` and `skills/<name>/SKILL.md` form its canonical
portable metadata and discovery surface.

## Validation boundary

Repository validation is stricter than the portable minimum in deliberate
ways:

- every immediate child directory of `packages/` must be a plugin root;
- the directory name, manifest name, and single skill name must match;
- versions must be `MAJOR.MINOR.PATCH` semantic versions;
- all discovered paths must remain inside their plugin root;
- symlinks and special files are rejected from release archives;
- manifest client-extension keys are allowed only in the v1 reverse-domain form;
- root client surfaces such as `.agents/` are rejected, and
  `.claude-plugin/` may contain only `marketplace.json`;
- local credentials and runtime artifacts must remain untracked.

For `.claude-plugin/marketplace.json`, validation requires:

- exactly the `name`, `owner`, `metadata`, and `plugins` keys, with the name
  `charms`;
- entries sorted by name, without duplicates, each naming a package under
  `packages/`;
- each entry to match the pinned `git-subdir` shape exactly;
- the release tag to exist locally and point at the entry's `sha`;
- `plugin.json` at that `sha` to have the same version and description;
- the package's current version to be no lower than the released one.

These checks need the release tags locally; run `git fetch --tags` if they are
missing.

The vendored schema gives deterministic validation. The official Agent Skills
reference implementation validates every `SKILL.md`.
