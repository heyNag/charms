# Security

Security rules for this repo:

- Never commit real API keys, including Groq or OpenAI keys.
- Use environment variables or gitignored `.env.local` for local secrets.
- `.env.local` must remain ignored and untracked.
- Do not echo full keys.
- Do not print secrets in logs, reports, commit messages, or issue comments.
- CI must not require secrets.
- Live Groq/OpenAI verification may source `.env.local` only inside a subshell.
- Generated artifacts under `.watch-video/` stay ignored.

## Safe Key Shape Checks

These examples verify key shape without printing the key.

Check an already-exported key:

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
