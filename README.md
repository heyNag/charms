# Charms

Charms contains two portable [Agent Plugins v1](https://agent-plugins.org/specification)
and an upstream-aligned pstack bundle. Native plugins have one skill each;
pstack contains separate Claude Code and Codex roots in one release.

| Plugin | Purpose | Plugin root |
| --- | --- | --- |
| `watch-video` | Analyze videos with Gemini or local models, original-audio transcription, matching transcripts, and timestamped frames. | [`packages/watch-video/`](packages/watch-video/) |
| `x-bookmarks` | Fetch, search, and digest X/Twitter bookmarks using Bird or the optional X API v2 backend. | [`packages/x-bookmarks/`](packages/x-bookmarks/) |
| `pstack` | if you want to go fast, go deep first. pstack helps you write less, but higher quality code. rigorous agent workflows you can parallelize with confidence. | [`packages/pstack/`](packages/pstack/) |

The repository root holds the shared `charms` marketplace and the development
and release tooling; it is not itself a plugin. Each product has its own release
boundary. The pstack container is not an installation root: select its
`claude-code/` or `codex/` child. See [pstack integration](docs/pstack.md) for
the pinned baseline, local development, and current capability limits.
Pstack is unreleased and is not yet advertised by the marketplaces.

## Install a plugin

Claude Code and Codex install plugins from the `charms` marketplace in this
repository. Replace `watch-video` with another released plugin.

Claude Code:

```sh
claude plugin marketplace add heyNag/charms
claude plugin install watch-video@charms
```

Codex (CLI 0.147.0 or newer):

```sh
codex plugin marketplace add heyNag/charms
codex plugin add watch-video@charms
```

The marketplace pins each plugin to its latest release commit, so these
installs only receive released versions. Unreleased changes on `main` never
reach them.

Hosts without a plugin system can install just the skill with
[Skillshare](https://skillshare.runkids.cc) or the
[skills CLI](https://github.com/vercel-labs/skills). Skill-only installs follow
`main`, not releases:

```sh
skillshare install github.com/heyNag/charms/packages/watch-video/skills/watch-video
npx skills add heyNag/charms
```

Use one channel per machine. A skill installed both ways loads twice.

Each GitHub release also carries the plugin as a ZIP with a SHA-256 checksum
for archival or offline use.

See [Installation](docs/installing.md) for updates, other clients, and release
ZIPs. Runtime prerequisites are plugin-specific. Read the selected plugin's
README before enabling it.

## Develop

Charms requires Python 3.11 or newer for repository tooling:

```sh
python3 -m pip install -r requirements-dev.txt
make check
```

`make check` runs conformance and marketplace validation, offline behavior
tests, Python and shell syntax checks, Ruff and ShellCheck, a check of the
links between the documents, secret and artifact checks, and a working-tree
whitespace check. Marketplace validation needs the release tags, so run
`git fetch --tags` first if your clone lacks them. `make coverage` reports
test coverage.

Changes reach `main` through pull requests that are merged once CI is green,
because skill-only installs follow `main`. See
[Development](docs/development.md#branches-and-pull-requests).

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md)
- [Plugin format](docs/plugin-format.md)
- [Installation](docs/installing.md)
- [Compatibility](docs/compatibility.md)
- [Development](docs/development.md)
- [Security](docs/security.md)
- [Releasing](docs/releasing.md)

Charms is licensed under the [MIT License](LICENSE).
