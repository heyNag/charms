<!-- BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/README.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->

# x-bookmarks

`x-bookmarks` is a local bookmark inspection package for agents. It fetches,
searches, and digests saved X/Twitter posts, then turns them into useful next
actions.

It is designed for local use by Claude Code, Codex, OpenCode, and similar agent
tools. The skill format is portable; live fetching needs either the `bird` CLI
with browser cookie access or local X API v2 OAuth state.

In the `agent-tools` repo, source lives under `packages/x-bookmarks`. Public
install targets are generated from that source into
`generated/claude/plugins/x-bookmarks`,
`generated/claude/custom-skills/x-bookmarks`,
`generated/codex/skills/x-bookmarks`, and `generated/agent-skills/x-bookmarks`.

Claude Code marketplace metadata points at the generated plugin package under
`generated/claude/plugins/x-bookmarks`. Codex users can copy
`generated/codex/skills/x-bookmarks` into their local skills directory. Claude
Desktop / claude.ai custom skill users can ZIP
`generated/claude/custom-skills/x-bookmarks`. OpenCode and generic Agent Skills
users can use `generated/agent-skills/x-bookmarks`.

## Requirements

Preferred no-credit backend:

```sh
bird --version
bird check --plain
```

Optional official API backend:

```sh
python3 scripts/x_api_auth.py --status
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

`agents/openai.yaml` gives agent UIs a human-readable display label while the
internal package name stays crisp:

```yaml
interface:
  display_name: "X/Twitter Bookmarks"
  short_description: "Fetch, search, and digest saved posts"
  default_prompt: "Use $x-bookmarks to fetch my latest X/Twitter bookmarks and summarize concrete next actions."
```

## Quickstart

From the source package directory, Codex install, or agent-generic install:

```sh
bird check --plain
python3 scripts/x_api_auth.py --status
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
```

From the generated Claude plugin package root, use the skill subdirectory:

```sh
python3 skills/x-bookmarks/scripts/x_api_auth.py --status
skills/x-bookmarks/scripts/fetch_bookmarks_bird.sh --count 25
```

Common workflows:

```sh
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
python3 scripts/fetch_bookmarks_api.py --count 100 --since-last --update-state --pretty
python3 scripts/fetch_bookmarks_api.py --folders --pretty
```

## Source Files

```text
SKILL.md                         # skill instructions for agents
agents/openai.yaml               # display metadata for Codex-style skill UIs
references/                      # backend and API notes
scripts/fetch_bookmarks_bird.sh  # Bird wrapper
scripts/fetch_bookmarks_api.py   # X API v2 fetch/search helper
scripts/x_api_auth.py            # local OAuth 2.0 PKCE helper
scripts/open_x_login.sh          # browser login opener
```

Generated install packages contain a subset of those files:

- Claude plugin package: `README.md`, `LICENSE`, `.claude-plugin/plugin.json`,
  commands, and `skills/x-bookmarks/`.
- Codex skill package: `README.md`, `LICENSE`, `SKILL.md`, `agents/`,
  `references/`, and `scripts/`.
- Claude custom-skill package: `README.md`, `LICENSE`, lowercase `skill.md`,
  `agents/`, `references/`, and `scripts/`.
- Agent-generic skill package: `README.md`, `LICENSE`, `SKILL.md`, `agents/`,
  `references/`, and `scripts/`.
