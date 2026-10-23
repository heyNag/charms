# Charms

Charms is a monorepo of five independent, portable
[Agent Plugins v1](https://agent-plugins.org/specification). Each plugin has a
root `plugin.json` manifest and one
[Agent Skill](https://agentskills.io/specification) under `skills/`.

| Plugin | Purpose | Plugin root |
| --- | --- | --- |
| `chatgpt-pro-review` | Prepare scoped ChatGPT Pro review packets and reconcile the result with local evidence. | [`packages/chatgpt-pro-review/`](packages/chatgpt-pro-review/) |
| `codex-reset-credit` | Report Codex reset credits and local rate-limit windows without exposing authentication data. | [`packages/codex-reset-credit/`](packages/codex-reset-credit/) |
| `mnemosyne-memory` | Apply a selective Mnemosyne recall, persistence, correction, and project-handoff workflow. | [`packages/mnemosyne-memory/`](packages/mnemosyne-memory/) |
| `watch-video` | Inspect video metadata, captions or transcripts, and representative frames. | [`packages/watch-video/`](packages/watch-video/) |
| `x-bookmarks` | Fetch, search, and digest saved X/Twitter posts through Bird or X API v2. | [`packages/x-bookmarks/`](packages/x-bookmarks/) |

The repository root holds the shared `charms` marketplace and the development
and release tooling; it is not itself a plugin. Every directory in `packages/`
is its own installation, version, security, and release boundary.

## Install a plugin

Claude Code and Codex install plugins from the `charms` marketplace in this
repository. Replace `watch-video` with any plugin from the table.

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
tests, Python and shell syntax checks, linting, secret and artifact checks, and
a working-tree whitespace check. Marketplace validation needs the release tags,
so run `git fetch --tags` first if your clone lacks them.

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
