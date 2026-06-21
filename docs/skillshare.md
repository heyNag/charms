# Skillshare

Skillshare can install skills from this repo, but it sees source and generated
files differently depending on the UI mode.

## Recommended Install Path

Use the curated hub index:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

In the Skillshare web UI:

1. Open `Search`.
2. Choose `Hub`.
3. Add or select the hub URL above.
4. Install `watch-video`, `codex-reset-credit`, or `x-bookmarks`.

CLI users can save the hub once:

```sh
skillshare hub add https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json --label agent-tools
skillshare hub default agent-tools
skillshare search --hub agent-tools bookmarks
```

The hub points each skill at the canonical package source:

```text
heyNag/agent-tools/packages/watch-video
heyNag/agent-tools/packages/codex-reset-credit
heyNag/agent-tools/packages/x-bookmarks
```

Direct CLI install works too:

```sh
skillshare install heyNag/agent-tools/packages/watch-video --track
skillshare install heyNag/agent-tools/packages/codex-reset-credit --track
skillshare install heyNag/agent-tools/packages/x-bookmarks --track
skillshare sync
```

Use `--track` when you want Skillshare's `check` and `update` commands to find
future repo updates.

## Why GitHub Search Can Show Duplicates

Skillshare's GitHub Search mode searches GitHub for every committed uppercase
`SKILL.md`. This repo intentionally commits generated target copies under
`generated/` for Claude Code, Claude Desktop, Codex, and OpenCode installs.
Those generated copies are useful, but they are not canonical source.

The canonical source files are:

```text
packages/watch-video/SKILL.md
packages/codex-reset-credit/SKILL.md
packages/x-bookmarks/SKILL.md
```

Generated copies include paths such as:

```text
generated/claude/plugins/<name>/skills/<name>/SKILL.md
generated/codex/skills/<name>/SKILL.md
generated/agent-skills/<name>/SKILL.md
```

That is why repo-scoped GitHub Search can show multiple cards with the same
skill name. Prefer Hub mode or direct package paths when installing from this
repo.

## `.skillignore`

The root `.skillignore` contains:

```text
generated/
```

Skillshare install/discovery honors `.skillignore`, so installing from the repo
root discovers canonical source packages instead of generated target copies.
GitHub Code Search may still show generated copies because it scans committed
files directly.

## Generated Hub Ownership

`skillshare-hub.json` is generated from:

```text
packages/*/SKILL.md
packages/*/tool.json
packages/*/plugin/plugin.json
```

Do not edit it by hand. After changing `SKILL.md` frontmatter, a package
manifest, or a plugin version, run:

```sh
make rebuild-generated
make verify-skill-metadata
make verify-packages
make verify-generated-clean
```

`make verify-packages` checks that every public agent-compatible package appears
in the hub exactly once and that hub entries point at `packages/<name>`, not
`generated/`.

## Skill Metadata Contract

Each public package must keep these fields aligned:

```text
packages/<name>/tool.json       name, description, tags, targets, public flag
packages/<name>/SKILL.md        frontmatter name, description, tags
skillshare-hub.json             generated public hub entry
```

The source `SKILL.md` frontmatter is intentionally self-describing because
Skillshare-style indexing reads skill names, descriptions, and tags directly
from skill files. `tool.json` remains the build manifest for this repo.

Run this check after adding or editing a skill:

```sh
make verify-skill-metadata
```

It fails if a package name drifts, if `SKILL.md` tags do not match
`tool.json`, if `skillshare-hub.json` points at `generated/`, or if
`.skillignore` stops hiding generated outputs from Skillshare discovery.

## Update Flow

For users who installed with `--track`:

```sh
skillshare check
skillshare update <skill-name>
skillshare sync
```

For all skills:

```sh
skillshare update --all
skillshare sync
```

If a user installed without tracking, reinstall from the hub or direct package
path and then run `skillshare sync`.
