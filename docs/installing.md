# Installation

Charms publishes one marketplace, `charms`, through two complete catalogs:
`.claude-plugin/marketplace.json` for Claude Code and
`.agents/plugins/marketplace.json` for Codex. Both contain the same released
native plugins.

Each marketplace entry pins one released plugin to its release tag and full
release commit SHA. Marketplace installs therefore only receive released,
immutable content; unreleased commits on `main` never reach them. A plugin
becomes installable through the marketplace after a published release is
verified and added to the selected host catalog.

The examples use the native plugin `watch-video`; substitute another plugin
listed in the selected host catalog. The [pstack bundle](pstack.md) uses
separate host roots, with local validation and capability limits described there.

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

Codex prefers `.agents/plugins/marketplace.json`. Charms keeps this catalog
complete, including every released native entry from the Claude catalog.

## Install only the skill

Hosts without a plugin system can install a native package's skill directory
directly.
These channels follow `main`, not releases: an install or update brings
whatever `main` holds at that moment. Changes reach `main` through pull
requests that passed CI, but they have not been through a release.

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

Use one channel per host. Installing the same skill as a plain skill and as
a plugin in the same host loads it twice, as `/watch-video` and
`/watch-video:watch-video`. When syncing with Skillshare, exclude hosts where
you already use the plugin.

## Release ZIP

Each native plugin release carries a portable directory for archival or
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

Pstack uses a different combined archive, `pstack-bundle-v<version>.zip`,
containing `pstack/claude-code/` and `pstack/codex/`. Select one of those child
roots. A locally built transport archive can instead contain just the selected
host subtree inside one `pstack/` folder. See
[pstack generation and inspection](pstack.md#generate-and-inspect) for the build
commands. Check the verified release and host catalog before using a
marketplace installation command for pstack.

## Use a local checkout

For clients that accept a local plugin directory, clone the repository and
select a native package directory or a pstack host root:

```sh
git clone https://github.com/heyNag/charms.git
```

For example, the `watch-video` plugin root is:

```text
charms/packages/watch-video/
```

Do not select `charms/` or `charms/packages/`; neither is a plugin root. A
checkout contains whatever commit you have, released or not.

For pstack, the roots are `charms/packages/pstack/claude-code/` and
`charms/packages/pstack/codex/`; `charms/packages/pstack/` is a release
container. Selecting a root does not establish Desktop or Cloud capability
support; read the [pstack support boundary](pstack.md#support-boundary).

## Verify a package locally

Repository contributors can run:

```sh
python3 -m pip install -r requirements-dev.txt
PLUGIN=watch-video
python3 scripts/validate_plugins.py "packages/${PLUGIN}"
```

For native plugins, the validator checks the v1 manifest schema, Agent Skills
conformance, Charms package invariants, path containment, and source hygiene.
`python3 scripts/validate_plugins.py packages/pstack` selects the repository's
dedicated bundle checks, including exact Claude source identity and Codex
payload provenance.

## Runtime setup

Installation makes a plugin discoverable. It does not install external
programs, create accounts, copy credentials, or grant permissions. Complete
the requirements in the selected package README before using the skill.

For `watch-video` local analysis, start a new session after installation and ask
**“Set up watch-video on this Mac.”** The skill detects the hardware and missing
prerequisites with `setup_local.py --preflight`, then guides the next steps.
You do not need to supply the chip, RAM, or the matching Splash build in a prompt.
For manual commands, follow the bundled
[local Mac setup](../packages/watch-video/skills/watch-video/references/local-models.md#set-up-another-mac)
after installing or updating through your chosen channel. It covers native
oMLX, the shared model directory, credentials, and an original-audio/frames
smoke test. Run its commands from the installed skill directory: `skills/watch-video`
inside a plugin, or the `watch-video` directory in a skill-only installation.
No separate repository checkout is required.

Never place access tokens, browser cookies, local session data, or generated
media inside the plugin directory.
