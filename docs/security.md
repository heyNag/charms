# Security

Secret-handling rules:

- Never commit real API keys.
- Use environment variables or gitignored `.env.local`.
- `.env.local` must remain ignored and untracked.
- Do not echo full keys.
- CI must not require secrets.
- Live Groq verification may source `.env.local` only inside a subshell.
- Generated run artifacts under `.watch-video/` stay ignored.
- X/Twitter tokens, cookies, bookmark exports, and search indexes stay outside
  the repo.
- Local `.dist/` artifacts and ZIPs stay ignored.
- Secret scanners and verification scripts should report only file paths for
  suspected secrets, not matching secret text.
- ChatGPT review packets and responses can contain private context. Do not
  commit them unless they are intentional sanitized public fixtures.

Safe key shape check:

```sh
test -n "${GROQ_API_KEY:-}"
case "${GROQ_API_KEY:-}" in gsk_*) echo "Groq key shape ok";; *) echo "Groq key shape unexpected";; esac
python3 - <<'PY'
import os
key = os.environ.get("GROQ_API_KEY", "")
print({"exists": bool(key), "starts_with_gsk": key.startswith("gsk_"), "length": len(key)})
PY
```

Unsafe examples:

```sh
echo "$GROQ_API_KEY"
cat .env.local
git add .env.local
```

Do not commit:

```text
.env.local
.watch-video/
.x-bookmarks/
.dist/
*.zip
media files
transcripts
frames
Codex auth/session files
X/Twitter cookies or OAuth tokens
node_modules/
.venv/
```
