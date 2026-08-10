# x-bookmarks

`x-bookmarks` is a local bookmark inspection package for agents. It fetches,
searches, and digests saved X/Twitter posts, then turns them into useful next
actions.

The skill format is portable; live fetching needs either the `bird` CLI with
browser cookie access or X API v2 OAuth credentials.

This directory is an [Agent Plugins v1](https://agent-plugins.org/specification)
plugin root. A compatible client with Agent Skills support loads `plugin.json`
here and discovers the skill from the standard fixed location:

```text
skills/x-bookmarks
```

The plugin is independently versioned. Installation and update behavior is
defined by the client loading this package.

## Requirements

Preferred no-credit backend:

```sh
bird --version
bird check --plain
```

Optional official API backend with saved local OAuth state:

```sh
python3 skills/x-bookmarks/scripts/x_api_auth.py --status
```

The API fetch helper can instead use an existing OAuth user access token from
`X_API_ACCESS_TOKEN` or `X_API_BEARER_TOKEN`. Do not print either variable.
`--include-write-scope` is an option of `x_api_auth.py`, not a fetch-helper
option, and is only for a separate workflow that changes X bookmarks.

Default local-only state lives outside this repo:

```text
~/.config/x-bookmarks/config.json
~/.config/x-bookmarks/tokens.json
~/.local/state/x-bookmarks/state.json
~/.config/bird/
```

`X_BOOKMARKS_CONFIG_DIR`, `X_BOOKMARKS_TOKEN_FILE`, and
`X_BOOKMARKS_STATE_FILE` override the x-bookmarks defaults. Keep every override
outside the plugin and source checkout.

Do not commit credentials, tokens, bookmark exports, or search indexes.

## Quickstart

Choose one configured backend. From the plugin root, use Bird:

```sh
skills/x-bookmarks/scripts/fetch_bookmarks_bird.sh --count 25
```

Or use X API v2:

```sh
python3 skills/x-bookmarks/scripts/x_api_auth.py --status
python3 skills/x-bookmarks/scripts/fetch_bookmarks_api.py --count 25 --pretty
```

From the skill folder, use Bird with:

```sh
cd skills/x-bookmarks
scripts/fetch_bookmarks_bird.sh --count 25
```

Or use X API v2 with:

```sh
cd skills/x-bookmarks
python3 scripts/x_api_auth.py --status
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
```

Common workflows:

```sh
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
python3 scripts/fetch_bookmarks_api.py --all --since-last --update-state --pretty
python3 scripts/fetch_bookmarks_api.py --folders --pretty
```

## Portable package files

```text
plugin.json                      Agent Plugins v1 manifest
LICENSE                          MIT license terms
README.md                        requirements and usage guidance
skills/x-bookmarks/SKILL.md      skill instructions
skills/x-bookmarks/references/   backend and API notes
skills/x-bookmarks/scripts/      local helper CLIs
```

## Development

In a Charms source checkout, run the package tests from the repository root:

```sh
python3 -m unittest discover -s packages/x-bookmarks/tests -p 'test_*.py'
```
