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

The repository root is development and release infrastructure, not an
installable plugin. Every directory in `packages/` is its own installation,
version, security, and release boundary.

## Install a plugin

Download the plugin ZIP and matching `.sha256` file from
[GitHub Releases](https://github.com/heyNag/charms/releases), verify it, and
extract it:

```sh
PLUGIN=watch-video
VERSION=1.0.0
CHECKSUM="${PLUGIN}-agent-plugin-v${VERSION}.zip.sha256"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum --check "$CHECKSUM"
else
  shasum -a 256 -c "$CHECKSUM"
fi
unzip "${PLUGIN}-agent-plugin-v${VERSION}.zip"
```

The extracted `<plugin>/` directory is the plugin root. Point a conformant
client at that directory using the client's local-plugin installation flow.
Agent Plugins standardizes package loading, not distribution or client user
interfaces; consult the
[compatible clients list](https://agent-plugins.org/compatible-clients) for
current client capabilities.

A source checkout works the same way: select one
`packages/<plugin>/` directory, never the repository root.

Runtime prerequisites are plugin-specific. Read the selected plugin's README
before enabling it.

## Develop

Charms requires Python 3.11 or newer for repository tooling:

```sh
python3 -m pip install -r requirements-dev.txt
make check
```

`make check` runs conformance validation, offline behavior tests, Python and
shell syntax checks, linting, secret and artifact checks, and repository
whitespace checks.

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
