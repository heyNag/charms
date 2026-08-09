# Installing Skills

Use this guide to install the current public skills:

```text
watch-video
codex-reset-credit
x-bookmarks
chatgpt-pro-review
mnemosyne-memory
```

For skill-specific requirements and examples, read:

- [watch-video.md](watch-video.md)
- [codex-reset-credit.md](codex-reset-credit.md)
- [x-bookmarks.md](x-bookmarks.md)
- [chatgpt-pro-review.md](chatgpt-pro-review.md)
- [mnemosyne-memory.md](mnemosyne-memory.md)

## Pick A Target

| Target | Best Path |
|---|---|
| Claude Code | Install from the Claude Code marketplace catalog. |
| Codex, Cursor, Copilot, Gemini CLI, and other Agent Skills hosts | `npx skills add heyNag/charms` (see below). |
| Codex (manual) | Copy `packages/<name>/skills/<name>` into `~/.codex/skills/<name>`. |
| Cursor (manual) | Use `.cursor-plugin/plugin.json`, which points at the root `skills/` symlink index. |
| OpenCode | Use `.opencode/plugins/charms.js` or copy the skill folder. |
| Claude Desktop / claude.ai | Download the ZIP attached to the skill's GitHub release, or build it locally. |
| Skillshare | Use the optional hub or direct package skill path. |

## Claude Code

Add the marketplace once:

```text
/plugin marketplace add heyNag/charms
```

Install the skill you want:

```text
/plugin install watch-video@charms
/plugin install codex-reset-credit@charms
/plugin install x-bookmarks@charms
/plugin install chatgpt-pro-review@charms
/plugin install mnemosyne-memory@charms
```

Invoke:

```text
/watch-video:watch <video-url-or-path>
/codex-reset-credit:codex-reset-credit
/x-bookmarks:x-bookmarks digest
/chatgpt-pro-review:chatgpt-pro-review implementation
Ask Claude to use mnemosyne-memory for project continuity.
```

If command names differ in your Claude Code version, run `/plugin list` or
`/plugin details <name>@charms`.

## Agent Skills CLI (Codex, Cursor, Copilot, Gemini CLI, and more)

The [Agent Skills](https://agentskills.io) installer discovers all public
skills in this repo and installs them into whatever agents it detects:

```sh
npx skills add heyNag/charms            # pick skills interactively
npx skills add heyNag/charms -g         # install globally for your user
npx skills add heyNag/charms --list     # list without installing
```

Useful flags: `--skill <name>` to select one skill, `-a codex -a cursor` to
target specific hosts, `--copy` to copy instead of symlinking. Update later
with `npx skills update <name>`.

## Codex

Clone or update the repo, then copy the skill folder:

```sh
git clone https://github.com/heyNag/charms.git
cd charms
SKILL=watch-video
mkdir -p ~/.codex/skills
rm -rf "$HOME/.codex/skills/$SKILL"
cp -R "packages/$SKILL/skills/$SKILL" "$HOME/.codex/skills/$SKILL"
```

Change `SKILL` to `codex-reset-credit`, `x-bookmarks`,
`chatgpt-pro-review`, or `mnemosyne-memory` for the other skills.

Local development shortcut from this repo:

```sh
./scripts/install-codex.sh
```

## Cursor

Use a checkout-based plugin flow by pointing Cursor at this repo root. The
manifest at `.cursor-plugin/plugin.json` reads skills from the root `skills/`
symlink index.

```sh
git clone https://github.com/heyNag/charms.git
cd charms
make build-root-indexes
```

If your Cursor version expects manually copied skills, copy
`packages/<name>/skills/<name>` into the skill location that Cursor documents
for that version.

## OpenCode

Plugin install:

```json
{
  "plugin": ["charms@git+https://github.com/heyNag/charms.git"]
}
```

Restart OpenCode after editing `opencode.json`.

Direct copy fallback:

```sh
git clone https://github.com/heyNag/charms.git
cd charms
SKILL=watch-video
mkdir -p ~/.config/opencode/skills
rm -rf "$HOME/.config/opencode/skills/$SKILL"
cp -R "packages/$SKILL/skills/$SKILL" "$HOME/.config/opencode/skills/$SKILL"
```

## Claude Desktop Or Claude.ai Skills

Each skill release attaches a ready-to-upload ZIP
(`<name>-claude-custom-skill-<version>.zip`) to its GitHub release - download
it and upload in Claude's `Customize > Skills` flow.

To build the same artifact locally instead (Claude custom skills use lowercase
`skill.md`, so this repo builds upload artifacts under ignored `.dist/`):

```sh
git clone https://github.com/heyNag/charms.git
cd charms
make build-packages
SKILL=watch-video
cd .dist/claude/custom-skills
zip -r "$SKILL.zip" "$SKILL"
```

Upload the ZIP in Claude's `Customize > Skills` flow. Do not commit `.dist/` or
ZIP files.

## Skillshare

Hub URL:

```text
https://raw.githubusercontent.com/heyNag/charms/main/skillshare-hub.json
```

In the Skillshare web UI, use `Search > Hub`, add/select that hub URL, then
search for `watch`, `codex`, `bookmarks`, `memory`, or another keyword.

Direct CLI install:

```sh
skillshare install heyNag/charms/packages/watch-video/skills/watch-video
skillshare install heyNag/charms/packages/codex-reset-credit/skills/codex-reset-credit
skillshare install heyNag/charms/packages/x-bookmarks/skills/x-bookmarks
skillshare install heyNag/charms/packages/chatgpt-pro-review/skills/chatgpt-pro-review
skillshare install heyNag/charms/packages/mnemosyne-memory/skills/mnemosyne-memory
skillshare sync
```

Direct package installs remain updateable from their recorded GitHub source;
`--track` is unnecessary and would preserve a checkout of the broader Charms
repository rather than one independently named package skill.

## Update Later

Use [updating-a-skill.md](updating-a-skill.md) for target-specific update
flows.
