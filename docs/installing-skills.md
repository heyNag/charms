# Installing Skills

Use this guide to install the current public skills:

```text
watch-video
codex-reset-credit
x-bookmarks
```

For skill-specific requirements and examples, read:

- [watch-video.md](watch-video.md)
- [codex-reset-credit.md](codex-reset-credit.md)
- [x-bookmarks.md](x-bookmarks.md)

## Pick A Target

| Target | Best Path |
|---|---|
| Claude Code | Install from the Claude Code marketplace catalog. |
| Codex | Copy `packages/<name>/skills/<name>` into `~/.codex/skills/<name>`. |
| Cursor | Use `.cursor-plugin/plugin.json`, which points at the root `skills/` symlink index. |
| OpenCode | Use `.opencode/plugins/agent-tools.js` or copy the skill folder. |
| Claude Desktop / claude.ai | Build a local `.dist/claude/custom-skills/<name>` folder and upload a ZIP. |
| Skillshare | Use the optional hub or direct package skill path. |

## Claude Code

Add the marketplace once:

```text
/plugin marketplace add heyNag/agent-tools
```

Install the skill you want:

```text
/plugin install watch-video@agent-tools
/plugin install codex-reset-credit@agent-tools
/plugin install x-bookmarks@agent-tools
```

Invoke:

```text
/watch-video:watch <video-url-or-path>
/codex-reset-credit:codex-reset-credit
/x-bookmarks:x-bookmarks digest
```

If command names differ in your Claude Code version, run `/plugin list` or
`/plugin details <name>@agent-tools`.

## Codex

Clone or update the repo, then copy the skill folder:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
SKILL=watch-video
mkdir -p ~/.codex/skills
rm -rf "$HOME/.codex/skills/$SKILL"
cp -R "packages/$SKILL/skills/$SKILL" "$HOME/.codex/skills/$SKILL"
```

Change `SKILL` to `codex-reset-credit` or `x-bookmarks` for the other skills.

Local development shortcut from this repo:

```sh
./scripts/install-codex.sh
```

## Cursor

Use a checkout-based plugin flow by pointing Cursor at this repo root. The
manifest at `.cursor-plugin/plugin.json` reads skills from the root `skills/`
symlink index.

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
make build-root-indexes
```

If your Cursor version expects manually copied skills, copy
`packages/<name>/skills/<name>` into the skill location that Cursor documents
for that version.

## OpenCode

Plugin install:

```json
{
  "plugin": ["agent-tools@git+https://github.com/heyNag/agent-tools.git"]
}
```

Restart OpenCode after editing `opencode.json`.

Direct copy fallback:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
SKILL=watch-video
mkdir -p ~/.config/opencode/skills
rm -rf "$HOME/.config/opencode/skills/$SKILL"
cp -R "packages/$SKILL/skills/$SKILL" "$HOME/.config/opencode/skills/$SKILL"
```

## Claude Desktop Or Claude.ai Skills

Claude custom skills use lowercase `skill.md`, so this repo builds local
upload artifacts under ignored `.dist/`:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
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
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

In the Skillshare web UI, use `Search > Hub`, add/select that hub URL, then
search for `watch`, `codex`, `bookmarks`, or another keyword.

Direct CLI install:

```sh
skillshare install heyNag/agent-tools/packages/watch-video/skills/watch-video --track
skillshare install heyNag/agent-tools/packages/codex-reset-credit/skills/codex-reset-credit --track
skillshare install heyNag/agent-tools/packages/x-bookmarks/skills/x-bookmarks --track
skillshare sync
```

## Update Later

Use [updating-a-skill.md](updating-a-skill.md) for target-specific update
flows.
