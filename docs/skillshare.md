# Optional Skillshare Support

Skillshare support exists for people who already use Skillshare. It is not the
primary public install path for this repo.

## Hub URL

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

In the Skillshare web UI:

1. Open `Search`.
2. Choose `Hub`.
3. Add or select the hub URL above.
4. Search for `watch`, `codex`, `bookmarks`, or another keyword.
5. Install the matching skill.

Do not paste the hub URL into the keyword search box. The URL selects the hub;
the search box is for terms inside that hub.

## CLI

```sh
skillshare hub add https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json --label agent-tools
skillshare hub default agent-tools
skillshare search --hub agent-tools bookmarks
```

Direct installs use canonical source skill folders:

```sh
skillshare install heyNag/agent-tools/packages/watch-video/skills/watch-video --track
skillshare install heyNag/agent-tools/packages/codex-reset-credit/skills/codex-reset-credit --track
skillshare install heyNag/agent-tools/packages/x-bookmarks/skills/x-bookmarks --track
skillshare install heyNag/agent-tools/packages/chatgpt-pro-review/skills/chatgpt-pro-review --track
skillshare sync
```

## Hub Ownership

`skillshare-hub.json` is generated from:

```text
packages/*/tool.json
packages/*/.claude-plugin/plugin.json
packages/*/skills/*/SKILL.md
```

It uses:

```text
sourcePath: heyNag/agent-tools
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

`.skillignore` hides `.dist/`, `skills/`, and `commands/` so local Skillshare
discovery does not index build artifacts or root symlink indexes as separate
skills.

## Update Flow

For tracked installs:

```sh
skillshare check
skillshare update <skill-name>
skillshare sync
```

For all tracked skills:

```sh
skillshare update --all
skillshare sync
```
