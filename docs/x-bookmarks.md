# x-bookmarks

`x-bookmarks` fetches, searches, and digests saved X/Twitter posts using Bird
cookie auth or optional X API v2 OAuth state.

Source paths:

```text
packages/x-bookmarks
packages/x-bookmarks/skills/x-bookmarks
```

## Install Paths

Full install commands for each target are in
[`installing-skills.md`](installing-skills.md).

- Claude Code: `/plugin install x-bookmarks@agent-tools`
- Codex: copy `packages/x-bookmarks/skills/x-bookmarks`
- Cursor: root `skills/x-bookmarks` symlink through `.cursor-plugin/plugin.json`
- OpenCode: root plugin wrapper or copy `packages/x-bookmarks/skills/x-bookmarks`
- Claude Desktop: build `.dist/claude/custom-skills/x-bookmarks`
- Skillshare: install `heyNag/agent-tools/packages/x-bookmarks/skills/x-bookmarks`

## Backends

Preferred no-credit backend:

```sh
bird check --plain
packages/x-bookmarks/skills/x-bookmarks/scripts/fetch_bookmarks_bird.sh --count 25
```

Optional official API backend:

```sh
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/x_api_auth.py --status
python3 packages/x-bookmarks/skills/x-bookmarks/scripts/fetch_bookmarks_api.py --count 25 --pretty
```

## Local State

Local state belongs outside the repo:

```text
~/.config/x-bookmarks/config.json
~/.config/x-bookmarks/tokens.json
~/.local/state/x-bookmarks/state.json
~/.config/bird/
```

Never commit cookies, tokens, bookmark exports, or search indexes.

## Future Improvements

- richer digest grouping
- safer folder workflows
- local cache/index tooling if it can stay outside the repo
