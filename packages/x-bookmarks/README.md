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

The Python helpers need Python 3.9 or newer. They check the version first and
stop with one line on an older `python3`. Each answers `--version` with the
installed plugin version.

The API fetch helper can instead use an existing OAuth user access token from
`X_API_ACCESS_TOKEN` or `X_API_BEARER_TOKEN`. Do not print either variable.
When X rejects the saved login with `401`, the fetch helper refreshes it once
and repeats the request; a token from the environment is never refreshed.
`--include-write-scope` is an option of `x_api_auth.py`, not a fetch-helper
option, and is only for a separate workflow that changes X bookmarks. Each
setup requests the read-only scopes plus only that run's
`--include-write-scope` or `--scope` flags, so rerunning setup without them
drops write access; unknown scope names are rejected. A new setup calls back
to `http://127.0.0.1:8739/callback`, which the X app must list exactly; a
setup saved earlier keeps its callback URL, and `--status` shows it. Setup
waits up to 5 minutes for the browser callback and ignores requests to other
paths. If
another setup run, or another program listening on 127.0.0.1, holds the
callback port, setup exits with an error; stop it or pass `--redirect-uri` with
a free loopback port registered in the X app.

Two more options of `x_api_auth.py`: `--no-browser` prints the authorization
URL without opening a browser, for a machine reached over SSH, and `--refresh`
renews the saved login now, without printing it. The
[X API v2 notes](skills/x-bookmarks/references/x-api-v2.md#auth) say how to
approve access from another machine.

Default local-only state lives outside this repo:

```text
~/.config/x-bookmarks/config.json
~/.config/x-bookmarks/tokens.json
~/.local/state/x-bookmarks/state.json
~/.config/bird/
```

`X_BOOKMARKS_CONFIG_DIR`, `X_BOOKMARKS_TOKEN_FILE`, and
`X_BOOKMARKS_STATE_FILE` override the x-bookmarks defaults. Keep every override
outside the plugin and source checkout. The three files are readable only by
your account (mode 600). A folder the helpers create for them is private too;
a folder that already exists keeps its permissions.

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
python3 scripts/fetch_bookmarks_bird.py --all --since-last --update-state --pretty
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
python3 scripts/fetch_bookmarks_api.py --all --since-last --update-state --pretty
python3 scripts/fetch_bookmarks_api.py --folders --pretty
```

"New since last time" works the same through both backends:
`fetch_bookmarks_bird.py` and `fetch_bookmarks_api.py` take the same review
flags and share one saved cutoff, because a bookmark's ID is the post's ID in
both. A review can therefore change backend from one run to the next.

`--update-state` saves the newest 50 fetched bookmark IDs as the review
cutoff, but only when the fetch reached the end of the list (`--all` without
`--max-pages`), and the API helper refuses it with `--query`. A reviewed post
bookmarked again moves to the top and is listed as new. In a partial fetch
such posts look just like the cutoff, so `--since-last` then returns every
fetched bookmark with `cutoff_mode` `unfiltered` and saves nothing. The JSON
`meta` reports `cutoff_reached` (true when the fetch reached the end of the
list, or when an early stop asked for below found the cutoff),
`state_updated`, and `cutoff_mode`; `created_at_fallback` means no saved
bookmark was still present, so post creation time was used and results may
skip or repeat bookmarks.

A full review costs one request per 100 bookmarks through the API and one per
20 through Bird. `--stop-after-known N` (5 to 50), with `--all --since-last`,
stops the fetch at the first N already reviewed bookmarks in a row and reports
`cutoff_mode` `early_stop`. This is opt-in because it is a bet: when at least
N reviewed posts were bookmarked again in their old order, they pass for the
cutoff, and new bookmarks below them are missed. Reviewed posts bookmarked
again in any other order do not stop the fetch.

`--since-last` and `--update-state` read the review state before the first
request or Bird run. A state file that cannot be read or is damaged stops the
run there, with the file's name and a fix, so it costs no API calls. If the
state cannot be saved after a fetch, the bookmarks are still printed,
`state_updated` stays false, and the exit status is 1.

`fetch_bookmarks_bird.py` runs `bird bookmarks --json` and prints `data` and
`meta` like the API helper. Each post is Bird's own object with `url`,
`created_at` and `source` added. It was written against the output of Bird
0.8.0 and refuses output it does not recognise, so a changed Bird cannot move
the cutoff by mistake; `fetch_bookmarks_bird.sh` still prints Bird's JSON
unchanged. It takes Bird's browser options (`--cookie-source`,
`--chrome-profile`, `--chrome-profile-dir`, `--firefox-profile`), refuses
`--auth-token` and `--ct0` because command arguments are visible to other
processes, and stops a Bird run after 10 minutes unless `--bird-timeout` says
otherwise. With `--stop-after-known`, it runs Bird in steps of 5, 10, 20 and
then 40 pages until the reviewed bookmarks show.

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
