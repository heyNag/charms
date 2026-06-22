# x-bookmarks

`x-bookmarks` is a local bookmark inspection package for agents. It fetches,
searches, and digests saved X/Twitter posts, then turns them into useful next
actions.

The skill format is portable; live fetching needs either the `bird` CLI with
browser cookie access or local X API v2 OAuth state.

The package root is a Claude Code plugin source. The portable skill source is:

```text
packages/x-bookmarks/skills/x-bookmarks
```

Codex, OpenCode, generic Agent Skills, and optional Skillshare installs all use
that same skill folder. Claude Desktop custom-skill ZIP contents are built
locally under `.dist/claude/custom-skills/x-bookmarks`.

## Requirements

Preferred no-credit backend:

```sh
bird --version
bird check --plain
```

Optional official API backend:

```sh
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/x_api_auth.py --status
```

Local-only state lives outside this repo:

```text
~/.config/x-bookmarks/config.json
~/.config/x-bookmarks/tokens.json
~/.local/state/x-bookmarks/state.json
~/.config/bird/
```

Do not commit credentials, tokens, bookmark exports, or search indexes.

## Agent UI Metadata

`skills/x-bookmarks/agents/openai.yaml` gives agent UIs a human-readable
display label while the internal package name stays crisp:

```yaml
interface:
  display_name: "X/Twitter Bookmarks"
  short_description: "Fetch, search, and digest saved posts"
  default_prompt: "Use $x-bookmarks to fetch my latest X/Twitter bookmarks and summarize concrete next actions."
```

## Quickstart

From the repo root:

```sh
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/x_api_auth.py --status
packages/x-bookmarks/skills/x-bookmarks/scripts/fetch_bookmarks_bird.sh --count 25
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/fetch_bookmarks_api.py --count 25 --pretty
```

From the skill folder:

```sh
cd packages/x-bookmarks/skills/x-bookmarks
python3 scripts/x_api_auth.py --status
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
```

Common workflows:

```sh
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
python3 scripts/fetch_bookmarks_api.py --count 100 --since-last --update-state --pretty
python3 scripts/fetch_bookmarks_api.py --folders --pretty
```

## Package Files

```text
.claude-plugin/plugin.json       Claude Code plugin metadata
skills/x-bookmarks/SKILL.md      skill instructions
skills/x-bookmarks/agents/       display metadata for agent UIs
skills/x-bookmarks/references/   backend and API notes
skills/x-bookmarks/scripts/      local helper CLIs
commands/x-bookmarks.md          Claude Code slash command prompt
tests/                           offline helper tests
tool.json                        package manifest
```

After editing source:

```sh
make build-packages
make public-check
```
