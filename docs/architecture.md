# Architecture

Charms contains two independent native Agent Plugins and one pstack bundle.
The repository root owns the shared marketplace and the development,
validation, documentation, and release tooling. It is not a plugin root.

```text
charms/
├── .claude-plugin/
│   └── marketplace.json
├── .agents/plugins/
│   └── marketplace.json
├── packages/
│   ├── watch-video/
│   ├── x-bookmarks/
│   └── pstack/
│       ├── claude-code/
│       └── codex/
├── integrations/pstack/
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

Each native `packages/<name>/` directory is a self-contained plugin root with:

- one canonical `plugin.json`;
- one skill at `skills/<name>/SKILL.md`;
- every runtime script and reference needed by that skill;
- plugin-specific documentation, license, and offline behavior tests.

Each native plugin has its own calendar version, release tag, GitHub release,
archive, marketplace entry, runtime prerequisites, trust boundary, and failure
surface. Host clients control permissions for each installation. Installing
one plugin never requires loading the other.

Pstack is one bundle containing two selected host roots, currently unreleased.
Canonical pstack and the committed Claude tree come from one immutable upstream
commit. Claude is
copied in full; Codex is generated from canonical pstack plus maintained
adapter inputs. No downstream changes enter either upstream snapshot. Its
lock, projection, publication record and candidate-update procedure live in
`integrations/pstack/`; see [pstack integration](pstack.md).

## Discovery

Native Agent Plugins use fixed component locations. Clients load each package's
`plugin.json` first, then discover immediate skill directories under that
package's `skills/`. Only files within that package root participate in
discovery.

The native plugins ship skills only. Pstack's release container is not a
plugin root: select `claude-code/` or `codex/`. These roots retain multiple
skills and additional resources, with maintained adapter code only on the
Codex side. Provider services are configured separately; including adapter
code does not provision a service or grant credentials. See the
[pstack support boundary](pstack.md#support-boundary).

## Marketplace

Claude reads `.claude-plugin/marketplace.json`; Codex prefers
`.agents/plugins/marketplace.json`. Both complete catalogs preserve every
released native entry. Pstack publication selects its respective child at the
same immutable release commit, using the host native manifest version. No
pstack entry is written before a verified release.

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

For native packages, skill-only channels such as Skillshare and the skills CLI
read `packages/<name>/skills/<name>/` from `main` and do not use the marketplace.

## Release model

A release is dispatched for one plugin from `main`. It runs the full CI on the
exact commit, publishes an immutable GitHub release tagged
`<name>--v<version>` with the plugin ZIP, verifies it, and then moves that
plugin's entries in both catalogs to the new release in a separate commit.
For pstack, that same commit includes its publication record. Version
bumps are ordinary commits made before the release. See
[Releasing](releasing.md).

## Source of truth

For each native plugin:

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

Each native package's `plugin.json` and `skills/<name>/SKILL.md` form its
canonical portable metadata and discovery surface.

Pstack instead records the upstream version, full commit and input identities
in `integrations/pstack/upstream.lock.json` and its source manifests. The
maintained projection owns the downstream bundle version; generated
`bundle.json` identifies both targets. `published.json` records the verified
release separately from pending generated work. Claude keeps its upstream
native version; Codex uses the bundle version.

## Validation boundary

Native package validation is stricter than the portable minimum in deliberate
ways:

- every native child directory of `packages/` must be a plugin root;
- the directory name, manifest name, and single skill name must match;
- versions must be `YEAR.MONTH.RELEASE` calendar versions, and a version
  waiting for release must be the plugin's next one;
- all discovered paths must remain inside their plugin root;
- symlinks and special files are rejected from release archives;
- manifest client-extension keys are allowed only in the v1 reverse-domain form;
- local credentials and runtime artifacts must remain untracked.

Only the known `packages/pstack` integration can use the bundle validation
profile. It verifies the locked upstream manifests, exact Claude tree, Codex
payload and provenance, and artifact hygiene. A package cannot opt itself out
of native validation by declaring a profile. Root client surfaces remain
restricted: `.claude-plugin/` contains only `marketplace.json`, and `.agents/`
contains only `plugins/marketplace.json` and its directory.

For both complete catalogs, validation requires:

- exactly the `name`, `owner`, `metadata`, and `plugins` keys, with the name
  `charms`;
- entries sorted by name, without duplicates, each naming a package under
  `packages/`;
- each entry to match the pinned `git-subdir` shape exactly;
- the release tag to exist locally and point at the entry's `sha`;
- the selected host's `plugin.json` at that `sha` to have the same version and
  description;
- native entries to match across both catalogs;
- each native package's current version to be no lower than the released one;
- pstack entries, when published, to match its verified publication record and
  select the respective host root at the same bundle tag and commit.

These checks need the release tags locally; run `git fetch --tags` if they are
missing.

The vendored schema gives deterministic native validation. The official Agent
Skills reference implementation validates every native package's `SKILL.md`.
