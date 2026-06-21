# Security

Security rules for this repo:

- Never commit real API keys, including Groq or OpenAI keys.
- Never commit Codex auth/session files or copied local account data.
- Never commit X/Twitter cookies, OAuth tokens, client secrets, bookmark
  exports, search indexes, or copied Bird config.
- Use environment variables or gitignored `.env.local` for local secrets.
- `.env.local` must remain ignored and untracked.
- Do not echo full keys.
- Do not print secrets in logs, reports, commit messages, or issue comments.
- CI must not require secrets.
- Live Groq/OpenAI verification may source `.env.local` only inside a subshell.
- Runtime artifacts under `.watch-video/` stay ignored.
- X bookmark local state under `.x-bookmarks/`, `tokens.json`, `state.json`,
  bookmark exports, search indexes, and local SQLite databases stay ignored.
- Committed generated package outputs and discovery metadata live under
  `generated/`, `.claude-plugin/`, and `skillshare-hub.json`; they are rebuilt
  from package source metadata and must not contain secrets, local-only paths,
  or runtime artifacts.
- Local ZIP archives made from `generated/claude/custom-skills/` for Claude
  custom skill upload are ignored. Rebuild them when needed instead of
  committing them.
- Third-party skill packagers such as Skills Compiler may fetch public GitHub
  folders and produce Claude Desktop `.skill` files. Use them only for public
  generated outputs, preview the bundled files before importing, and never paste
  private repo URLs, secrets, local auth files, or uncommitted local artifacts.

For `codex-reset-credit`, never print or commit Codex access tokens, refresh
tokens, account IDs, raw auth file contents, credit IDs, email addresses, profile
image URLs, or unredacted auth paths. The helper may read local Codex auth and
session files, but it must not modify them.

For `x-bookmarks`, never print or commit X/Twitter cookies, OAuth access tokens,
refresh tokens, client secrets, raw auth files, bookmark exports, search
indexes, or copied Bird config. Local state belongs outside this repo:

```text
~/.config/x-bookmarks/
~/.local/state/x-bookmarks/
~/.config/bird/
```

## Safe Key Shape Checks

These examples verify key shape without printing the key.

Check an exported key:

```sh
python3 - <<'PY'
import os
key = os.environ.get("GROQ_API_KEY", "")
ok = bool(key) and key.startswith("gsk_") and 40 <= len(key) <= 240
print("GROQ_API_KEY shape:", "ok" if ok else "missing-or-invalid")
raise SystemExit(0 if ok else 2)
PY
```

Source `.env.local` only inside a subshell:

```sh
bash -lc 'set -a; source .env.local >/dev/null 2>&1; set +a; python3 - <<'"'"'PY'"'"'
import os
key = os.environ.get("GROQ_API_KEY", "")
ok = bool(key) and key.startswith("gsk_") and 40 <= len(key) <= 240
print("GROQ_API_KEY shape:", "ok" if ok else "missing-or-invalid")
raise SystemExit(0 if ok else 2)
PY'
```

Printing the length is acceptable when useful:

```sh
python3 - <<'PY'
import os
key = os.environ.get("GROQ_API_KEY", "")
print("GROQ_API_KEY length:", len(key) if key else 0)
PY
```

## Unsafe Examples

Do not run:

```sh
echo "$GROQ_API_KEY"
cat .env.local
env | grep GROQ_API_KEY
set -x; source .env.local
```

Do not paste API keys into docs, tests, reports, command output, commit
messages, or PR descriptions.
