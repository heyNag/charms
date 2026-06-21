# X Bookmarks

`x-bookmarks` helps agents fetch, search, review, summarize, and digest saved
X/Twitter posts.

Source of truth:

```text
packages/x-bookmarks
```

This source package has a `SOURCE.md` marker.

Public install targets:

```text
generated/claude/plugins/x-bookmarks
generated/claude/custom-skills/x-bookmarks
generated/codex/skills/x-bookmarks
generated/agent-skills/x-bookmarks
```

These public install targets are generated from `packages/x-bookmarks` and have
`GENERATED.md` markers. Edit the source package first, then run
`make rebuild-generated`. The generated markers list exact source paths, such
as `packages/x-bookmarks/references/` producing
`generated/claude/plugins/x-bookmarks/skills/x-bookmarks/references/`.

## Install

Claude Code marketplace install:

```text
/plugin marketplace add heyNag/agent-tools
/plugin install x-bookmarks@agent-tools
```

After installing, try:

```text
/x-bookmarks:x-bookmarks digest
```

If your Claude Code version shows a different command name, run `/plugin list`
or `/plugin details x-bookmarks@agent-tools`.

Codex install:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/x-bookmarks
cp -R generated/codex/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

Claude Desktop / claude.ai custom skill ZIP:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
make rebuild-generated
cd generated/claude/custom-skills
zip -r x-bookmarks.zip x-bookmarks
```

OpenCode install:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.config/opencode/skills
rm -rf ~/.config/opencode/skills/x-bookmarks
cp -R generated/agent-skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

`generated/agent-skills/x-bookmarks/SKILL.md` and
`generated/claude/custom-skills/x-bookmarks/skill.md` are both generated from
`packages/x-bookmarks/SKILL.md`.

Local development install from source:

```sh
./scripts/install-all.sh
```

## Design

The `x-bookmarks` flow is:

1. Prefer Bird for local no-credit bookmark access through the logged-in browser
   session.
2. Check Bird with `bird check --plain`.
3. Fetch bookmarks with `scripts/fetch_bookmarks_bird.sh` when Bird is ready.
4. Use X API v2 only when Bird is unavailable, the user asks for the official
   API path, or API folder behavior is needed.
5. Manage X API OAuth with `scripts/x_api_auth.py` and PKCE.
6. Fetch/search API results with `scripts/fetch_bookmarks_api.py`.
7. Return action-oriented digests with backend and auth/rate-limit caveats.

The skill folder format is portable across agent surfaces, but live bookmark
access needs local Bird browser-cookie access or local X API OAuth state. Hosted
Claude custom skill upload can carry the instructions and scripts, but local
fetching is most reliable in Claude Code, Codex, or OpenCode.

## Agent UI Metadata

`packages/x-bookmarks/agents/openai.yaml` provides display metadata for
Codex-style skill UIs:

```yaml
interface:
  display_name: "X/Twitter Bookmarks"
  short_description: "Fetch, search, and digest saved posts"
  default_prompt: "Use $x-bookmarks to fetch my latest X/Twitter bookmarks and summarize concrete next actions."
```

Generated packages copy that file when the target supports bundled agent
metadata.

## Local State

Local-only state belongs outside this repo:

```text
~/.config/x-bookmarks/config.json
~/.config/x-bookmarks/tokens.json
~/.local/state/x-bookmarks/state.json
~/.config/bird/
```

Do not commit credentials, cookies, tokens, bookmark exports, search indexes, or
copied Bird config.

## Usage

Backend status checks:

```sh
command -v bird >/dev/null && bird check --plain
python3 packages/x-bookmarks/scripts/x_api_auth.py --status
```

Recent bookmarks:

```sh
packages/x-bookmarks/scripts/fetch_bookmarks_bird.sh --count 25
python3 packages/x-bookmarks/scripts/fetch_bookmarks_api.py --count 25 --pretty
```

Search and since-last review:

```sh
python3 packages/x-bookmarks/scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
python3 packages/x-bookmarks/scripts/fetch_bookmarks_api.py --count 100 --since-last --update-state --pretty
```

Folders through the API:

```sh
python3 packages/x-bookmarks/scripts/fetch_bookmarks_api.py --folders --pretty
python3 packages/x-bookmarks/scripts/fetch_bookmarks_api.py --folder-id FOLDER_ID --count 50 --pretty
```

## Response Shape

Unless the user asks for a narrower format, return:

1. Short summary
2. Action groups: try, read, save-for-project, share, discard
3. High-signal bookmarks with author, URL, and why they matter
4. Concrete next actions
5. Backend used and any auth/rate-limit caveats

## Future Improvements

- Better bookmark export normalization.
- Optional local search index for repeated reviews.
- Richer digest templates for projects, reading queues, and weekly reviews.
- Optional MCP tools under `mcp/x-bookmarks` only when a real server surface is
  needed.
- No MCP gateway.
