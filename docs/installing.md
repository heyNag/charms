# Installation

Charms publishes one marketplace, `charms`, at
`.claude-plugin/marketplace.json` in this repository. Claude Code and Codex both
install from it.

Each marketplace entry pins one released plugin to its release tag and full
release commit SHA. Marketplace installs therefore only receive released,
immutable content; unreleased commits on `main` never reach them. A plugin
appears in the marketplace after its first release.

The examples use `watch-video`. Replace it with any plugin under `packages/`.

## Claude Code

Add the marketplace once, then install a plugin:

```sh
claude plugin marketplace add heyNag/charms
claude plugin install watch-video@charms
```

The `/plugin` menu offers the same steps.

To update, refresh the marketplace and then the plugin:

```sh
claude plugin marketplace update charms
claude plugin update watch-video@charms
```

Restart Claude Code to apply an update. Auto-update is off by default for
third-party marketplaces; enable it for `charms` in `/plugin` > Marketplaces.

## Codex

Codex requires CLI 0.147.0 or newer, the first release that installs root Agent
Plugins `plugin.json` packages from a marketplace.

```sh
codex plugin marketplace add heyNag/charms
codex plugin add watch-video@charms
```

Codex re-checks Git marketplaces at session start. To refresh on demand:

```sh
codex plugin marketplace upgrade charms
```

Codex reads the Claude-format `.claude-plugin/marketplace.json` directly, so
Charms has no `.agents/plugins/marketplace.json`.

## Install only the skill

Hosts without a plugin system can install a package's skill directory directly.
These channels follow `main`, not releases.

With [Skillshare](https://skillshare.runkids.cc):

```sh
skillshare install github.com/heyNag/charms/packages/watch-video/skills/watch-video
skillshare sync
```

Update it later with `skillshare update watch-video`.

With the [skills CLI](https://github.com/vercel-labs/skills):

```sh
npx skills add heyNag/charms
```

Use one channel per machine. Installing the same skill as a plain skill and as
a plugin loads it twice, as `/watch-video` and `/watch-video:watch-video`.

## Release ZIP

Each GitHub release carries the plugin as a portable directory for archival or
offline use. Releases are tagged `<name>--v<version>` and attach two assets:

```text
<name>-agent-plugin-v<version>.zip
<name>-agent-plugin-v<version>.zip.sha256
```

Download, verify, and extract one release. Set `VERSION` to the release you
want:

```sh
PLUGIN=watch-video
VERSION="<version>"
TAG="${PLUGIN}--v${VERSION}"
ZIP="${PLUGIN}-agent-plugin-v${VERSION}.zip"
gh release download "$TAG" --repo heyNag/charms
gh release verify-asset "$TAG" "$ZIP" --repo heyNag/charms
unzip "$ZIP"
```

`gh release verify-asset` checks the asset against the immutable release's
attestation. The checksum file also works with `sha256sum --check "$ZIP.sha256"`
or `shasum -a 256 -c "$ZIP.sha256"`.

The archive expands to one directory:

```text
<name>/
├── plugin.json
├── LICENSE
├── README.md
└── skills/
```

Load that `<name>/` directory using the selected client's documented Agent
Plugin flow. See [Compatibility](compatibility.md) for client support.

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

Do not select `charms/` or `charms/packages/`; neither is a plugin root. A
checkout contains whatever commit you have, released or not.

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
