# Agent Compatibility

`agent-tools` keeps one source skill per package and generates installable
shapes for each agent surface. The portable source pattern is:

```text
packages/<name>/
  SKILL.md
  README.md
  tool.json
  scripts/       optional
  references/    optional
  agents/        optional
  commands/      optional Claude command prompts
```

Generated outputs adapt that source:

```text
generated/claude/plugins/<name>        Claude Code plugin package
generated/claude/custom-skills/<name>  Claude Desktop / claude.ai custom skill folder
generated/codex/skills/<name>          Codex skill package
generated/agent-skills/<name>          OpenCode and generic SKILL.md skill folder
skillshare-hub.json                    Skillshare discovery index, not a runtime target
```

For diagrams and exact per-target folder shapes, see
[`distribution-targets.md`](distribution-targets.md).

## Surface Map

Claude Code installs through the marketplace catalog:

```text
/plugin marketplace add heyNag/agent-tools
/plugin install watch-video@agent-tools
/plugin install codex-reset-credit@agent-tools
/plugin install x-bookmarks@agent-tools
```

Source path to edit:

```text
packages/<name>
```

Generated path consumed by Claude Code:

```text
generated/claude/plugins/<name>
```

Codex can copy the generated Codex skill package:

```sh
mkdir -p ~/.codex/skills
cp -R generated/codex/skills/watch-video ~/.codex/skills/watch-video
cp -R generated/codex/skills/codex-reset-credit ~/.codex/skills/codex-reset-credit
cp -R generated/codex/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

Claude Desktop and claude.ai custom skills use a ZIP containing the skill folder
with lowercase `skill.md`. Build from the generated Claude custom-skill bundle:

```sh
make rebuild-generated
cd generated/claude/custom-skills
zip -r watch-video.zip watch-video
zip -r codex-reset-credit.zip codex-reset-credit
zip -r x-bookmarks.zip x-bookmarks
```

Optional no-terminal path: paste the public
`generated/claude/custom-skills/<name>` GitHub folder URL into the third-party
[Skills Compiler](https://skill-compiler.statechange.ai/), preview the files,
download the `.skill`, and import it in Claude Desktop. This convenience path
uses the same generated folder; it does not change the source-of-truth rule.

OpenCode uses the generated agent-skill bundle:

```sh
mkdir -p ~/.config/opencode/skills
cp -R generated/agent-skills/watch-video ~/.config/opencode/skills/watch-video
cp -R generated/agent-skills/codex-reset-credit ~/.config/opencode/skills/codex-reset-credit
cp -R generated/agent-skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

The same portable folders can also be copied to agent-compatible locations such
as `.agents/skills/<name>` or `~/.agents/skills/<name>`.

Skillshare is optional. It is an installer and sync manager rather than a
separate runtime target. If you already use it, use Hub mode with:

```text
https://raw.githubusercontent.com/heyNag/agent-tools/main/skillshare-hub.json
```

Or install directly from the canonical source package:

```sh
skillshare install heyNag/agent-tools/packages/watch-video --track
skillshare sync
```

The hub resolves to canonical `packages/<name>` source paths. See
[`skillshare.md`](skillshare.md) for duplicate-search behavior and update flow.

## Filename Compatibility

The package source uses `SKILL.md`, which is the standard consumed by Claude
Code, Codex, and OpenCode. Generated outputs intentionally split by filename
expectation:

```text
generated/agent-skills/<name>/SKILL.md
generated/claude/custom-skills/<name>/skill.md
```

Both files are generated from the same source file:

```text
packages/<name>/SKILL.md
```

Do not edit either generated file directly. Keeping them in separate generated
folders avoids case-sensitive/case-insensitive filesystem collisions. Edit
`packages/<name>/SKILL.md`, then run:

```sh
make rebuild-generated
make audit-generated
make verify-generated-clean
```

## Runtime Boundary

The skill format is agent-agnostic. Runtime capability is not identical across
all hosts.

`watch-video` needs local tools such as `yt-dlp`, `ffmpeg`, and `ffprobe` for
full video inspection. It works best in local agent shells such as Claude Code,
Codex, and OpenCode when those binaries are installed.

`codex-reset-credit` needs local Codex auth/session state. It is useful in local
agent shells that can read those files safely. A hosted Claude custom-skill
upload can carry the instructions and scripts, but it cannot inspect local
Codex Desktop auth files on your Mac.

`x-bookmarks` needs Bird browser-cookie access or local X API OAuth state for
live bookmark fetches. The skill package is portable, but live X/Twitter access
is useful only where the agent can run local scripts and reach the user's local
auth state safely.

Keep new skills honest about this split: make the package format portable, then
document runtime assumptions in `SKILL.md`, `README.md`, and the matching docs
page.
