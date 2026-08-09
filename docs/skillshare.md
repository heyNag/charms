# Optional Skillshare Support

Skillshare support exists for people who already use Skillshare. It is not the
primary public install path for this repo.

## Hub URL

```text
https://raw.githubusercontent.com/heyNag/charms/main/skillshare-hub.json
```

In the Skillshare web UI:

1. Open `Search`.
2. Choose `Hub`.
3. Add or select the hub URL above.
4. Search for `watch`, `codex`, `bookmarks`, `memory`, or another keyword.
5. Install the matching skill.

Do not paste the hub URL into the keyword search box. The URL selects the hub;
the search box is for terms inside that hub.

## CLI

```sh
skillshare hub add https://raw.githubusercontent.com/heyNag/charms/main/skillshare-hub.json --label charms
skillshare hub default charms
skillshare search --hub charms bookmarks
```

Direct installs use canonical source skill folders:

```sh
skillshare install heyNag/charms/packages/watch-video/skills/watch-video
skillshare install heyNag/charms/packages/codex-reset-credit/skills/codex-reset-credit
skillshare install heyNag/charms/packages/x-bookmarks/skills/x-bookmarks
skillshare install heyNag/charms/packages/chatgpt-pro-review/skills/chatgpt-pro-review
skillshare install heyNag/charms/packages/mnemosyne-memory/skills/mnemosyne-memory
skillshare sync
```

These are remote-backed GitHub subdirectory installs. Skillshare records their
source, commit, tree hash, and file hashes, so each skill can be checked and
updated by name. Do not add `--track` to these commands: that mode preserves a
Git checkout for the broader Charms repository instead of installing one
independently updateable package skill.

## Hub Ownership

`skillshare-hub.json` is generated from:

```text
packages/*/tool.json
packages/*/.claude-plugin/plugin.json
packages/*/skills/*/SKILL.md
```

It uses:

```text
sourcePath: heyNag/charms
source: packages/<name>/skills/<name>
```

Do not edit it by hand. Run:

```sh
make build-packages
make public-check
```

## Search Results

Use the hub search when you want the curated public skill list. The hub points
at canonical source skill files under `packages/*/skills/*`.

`.skillignore` uses root-anchored `/.dist/`, `/skills/`, and `/commands/`
patterns so local Skillshare discovery skips build artifacts and root symlink
indexes without hiding canonical nested `packages/*/skills/*` source.

## Update Flow

For a remote-backed skill:

```sh
skillshare check <skill-name>
skillshare update <skill-name>
skillshare sync
```

For all remote-backed skills and tracked repositories:

```sh
skillshare update --all
skillshare sync
```
