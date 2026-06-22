---
description: Fetch, search, and digest X/Twitter bookmarks.
argument-hint: "[digest|search QUERY|folders|since-last] [--count N]"
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: x-bookmarks command -->

Use the `x-bookmarks` skill with the user's arguments: $ARGUMENTS

Run scripts from the installed `x-bookmarks` skill, or
`packages/x-bookmarks/skills/x-bookmarks/scripts/` when working from this
repository.

Start by checking safe backend status:

```sh
command -v bird >/dev/null && bird check --plain
python3 scripts/x_api_auth.py --status
```

Prefer Bird for no-credit fetch/search/digest workflows. Use X API v2 only
when Bird is unavailable, when the user explicitly asks for the official API
path, or when API folder behavior is needed.

Return a concise digest with action groups, high-signal bookmarks, concrete next
actions, backend used, and any auth or rate-limit caveats. Never print cookies,
tokens, client secrets, raw auth files, bookmark exports, or search indexes.
