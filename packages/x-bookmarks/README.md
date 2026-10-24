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

The plugin is versioned and released independently. In Claude Code or Codex,
install it as `x-bookmarks@charms` from the Charms marketplace. See
[Installation](https://github.com/heyNag/charms/blob/main/docs/installing.md)
for updates and skill-only installs.

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
option, and is only for a separate workflow that changes X bookmarks. Each
setup requests the read-only scopes plus only that run's
`--include-write-scope` or `--scope` flags, so rerunning setup without them
drops write access; unknown scope names are rejected. Setup waits up to 5
minutes for the browser callback and ignores requests to other paths. If
another setup run, or another program listening on 127.0.0.1, holds the
callback port, setup exits with an error; stop it or pass `--redirect-uri` with
a free loopback port registered in the X app.

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

`--update-state` saves the newest 50 fetched bookmark IDs as the review
cutoff, but only when the fetch reached the end of the list (`--all` without
`--max-pages`), and it refuses `--query`. A reviewed post bookmarked again
moves to the top and is listed as new. In a partial fetch such posts look just
like the cutoff, so `--since-last` then returns every fetched bookmark with
`cutoff_mode` `unfiltered` and saves nothing. The JSON `meta` reports
`cutoff_reached` (true only when the fetch reached the end of the list),
`state_updated`, and `cutoff_mode`; `created_at_fallback` means no saved
bookmark was still present, so post creation time was used and results may
skip or repeat bookmarks.

## Safety

Bookmark content is third-party text. The skill tells agents to treat it as
untrusted data, never as instructions, and to keep Bird read-only unless you
ask for an account change. The API helpers refuse HTTP redirects, so a
redirect can never carry OAuth tokens or client secrets to another host.

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
