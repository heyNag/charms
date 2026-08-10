# Installation

An Agent Plugin is a directory. Agent Plugins v1 defines how a compatible
client loads that directory; each client controls its own acquisition and
installation interface.

## Install a release

Open [Charms releases](https://github.com/heyNag/charms/releases) and select the
release tagged `agent-plugin/<name>/v<version>`. Download both assets:

```text
<name>-agent-plugin-v<version>.zip
<name>-agent-plugin-v<version>.zip.sha256
```

Verify and extract the archive:

```sh
PLUGIN=watch-video
VERSION=2026.8.10
CHECKSUM="${PLUGIN}-agent-plugin-v${VERSION}.zip.sha256"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum --check "$CHECKSUM"
else
  shasum -a 256 -c "$CHECKSUM"
fi
unzip "${PLUGIN}-agent-plugin-v${VERSION}.zip"
```

The archive expands to one directory:

```text
<name>/
├── plugin.json
├── LICENSE
├── README.md
└── skills/
```

Install or load that `<name>/` directory using the selected client's documented
Agent Plugin flow. See the Agent Plugins
[compatible clients list](https://agent-plugins.org/compatible-clients) for
the component types and transports each client currently supports.

## Use a local checkout

For clients that accept a local plugin directory, clone the repository and
select one package directory:

```sh
git clone https://github.com/heyNag/charms.git
```

For example, the `watch-video` plugin root is:

```text
charms/packages/watch-video/
```

Do not select `charms/` or `charms/packages/`; neither is a plugin root.

## Verify a package locally

Repository contributors can run:

```sh
python3 -m pip install -r requirements-dev.txt
PLUGIN=watch-video
python3 scripts/validate_plugins.py "packages/${PLUGIN}"
```

The validator checks the v1 manifest schema, Agent Skills conformance,
Charms package invariants, path containment, and source hygiene.

## Runtime setup

Installation makes a plugin discoverable. It does not install external
programs, create accounts, copy credentials, or grant permissions. Complete
the requirements in the selected package README before using the skill.

Never place access tokens, browser cookies, local session data, or generated
media inside the plugin directory.
