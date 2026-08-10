---
name: x-bookmarks
description: Use when the user asks to fetch, search, review, summarize, digest, or act on X/Twitter bookmarks, saved posts, bookmark folders, no-credit bookmark access, or recurring bookmark reviews.
license: MIT
compatibility: Requires Python 3.11+ and either the Bird CLI with browser-cookie access or X API v2 OAuth credentials; live bookmark retrieval requires network access.
---

# x-bookmarks

Use this skill when a user asks to fetch, search, review, summarize, digest, or
act on X/Twitter bookmarks, saved posts, bookmark folders, or recurring
bookmark reviews.

## Operating Rules

- Prefer Bird via `bird.fast` first because it uses the logged-in browser
  session and avoids paid X API credits.
- Use X API v2 only when Bird cannot work, when the user explicitly asks for
  the official API path, or when API-specific behavior such as listing folders
  is needed.
- Bundled helpers do not change the X account. Keep OAuth scopes to:
  `tweet.read users.read bookmark.read offline.access`.
- Do not pass `--include-write-scope` to `x_api_auth.py` for the bundled fetch
  workflows. Request `bookmark.write` only for a separate, explicitly
  authorized write workflow.
- Do not ask for browser cookies, `auth_token`, `ct0`, OAuth tokens, access
  tokens, refresh tokens, or client secrets in chat.
- Do not print tokens, cookies, or raw local auth files. Helper JSON can contain
  account IDs and bookmark content; keep raw output local and expose only the
  fields needed for the user's request.
- Default local auth and review state lives under `~/.config/x-bookmarks/`,
  `~/.local/state/x-bookmarks/`, and `~/.config/bird/`.
- `X_BOOKMARKS_CONFIG_DIR`, `X_BOOKMARKS_TOKEN_FILE`, and
  `X_BOOKMARKS_STATE_FILE` can override the x-bookmarks defaults. Keep every
  override outside the plugin and source checkout.
- If auth fails, report the status and a safe fix command without exposing
  secrets.

## Invocation

From this skill directory, check the configured backend; do not require both.
For Bird:

```sh
bird check --plain
```

For X API v2 with saved local OAuth state:

```sh
python3 scripts/x_api_auth.py --status
```

The API fetch helper can instead use an existing OAuth user access token from
`X_API_ACCESS_TOKEN` or `X_API_BEARER_TOKEN`. Never print either variable.

Fetch recent bookmarks with one backend:

```sh
# Bird
scripts/fetch_bookmarks_bird.sh --count 25

# X API v2
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
```

Fetch bookmarks for local inspection or search. Bird emits JSON for the agent
to inspect; the API helper also provides the bundled `--query` filter:

```sh
scripts/fetch_bookmarks_bird.sh --all
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
```

For the API backend, fetch new results since the last recorded review:

```sh
python3 scripts/fetch_bookmarks_api.py --all --since-last --update-state --pretty
```

Bird can fetch a recent window with
`scripts/fetch_bookmarks_bird.sh --count 100`, but it does not maintain a
persisted review cutoff.

List bookmark folders or fetch a folder:

```sh
python3 scripts/fetch_bookmarks_api.py --folders --pretty
python3 scripts/fetch_bookmarks_api.py --folder-id FOLDER_ID --count 50 --pretty
bird bookmarks --folder-id FOLDER_ID -n 50 --json
```

Open X login when Bird needs a browser session:

```sh
scripts/open_x_login.sh
```

## Backend Selection

1. Use Bird first for fetch, digest, search, and review workflows.
2. If Bird is missing, tell the user to install Bird from `https://bird.fast/`
   or their managed toolchain.
3. If Bird cookie auth fails, open `https://x.com` with
   `scripts/open_x_login.sh` when tool access allows it, then ask the user to
   finish logging in and retry `bird check --plain`.
4. If browser cookie extraction still fails, ask which browser/profile to use
   and pass Bird's `--cookie-source`, `--chrome-profile`,
   `--chrome-profile-dir`, or `--firefox-profile` flags.
5. Use X API v2 when Bird is unavailable/broken or the user wants the official
   API path.

For Bird details, read `references/bird-fast.md` before changing install,
browser auth, or no-credit backend behavior.

## X API Setup

Use OAuth 2.0 Authorization Code Flow with PKCE. The default local callback is:

```text
http://localhost:8739/callback
```

Use `--redirect-uri` when the X Developer app is configured with another
loopback callback.

Required read scopes:

```text
tweet.read users.read bookmark.read offline.access
```

If local auth is missing and the user wants the official API path:

1. Ask the user to create or select an X Developer app.
2. Ask them to enable OAuth 2.0 / PKCE user authentication.
3. Ask them to add the selected callback URL exactly.
4. Ask for the OAuth 2.0 Client ID.
5. For a public client without a client secret, run:

   ```sh
   python3 scripts/x_api_auth.py --client-id CLIENT_ID
   ```

6. For a confidential client, collect the secret through a hidden local prompt
   and pass it through standard input:

   ```sh
   read -rs X_API_CLIENT_SECRET
   printf '\n'
   printf '%s\n' "$X_API_CLIENT_SECRET" |
     python3 scripts/x_api_auth.py --client-id CLIENT_ID --client-secret-stdin
   unset X_API_CLIENT_SECRET
   ```

   The helper stores the confidential-client secret in its private local
   configuration so it can refresh tokens.

7. If the helper cannot open the browser, ask the user to open the printed URL
   and approve access.
8. Run `python3 scripts/x_api_auth.py --status`, then a small test fetch.

For endpoint, scope, and rate-limit details, read `references/x-api-v2.md`
before changing API behavior.

## Response Shape

Unless the user asks for a narrower format, return:

1. Short summary
2. Action groups: try, read, save-for-project, share, discard
3. High-signal bookmarks with author, URL, and why they matter
4. Concrete next actions
5. Backend used and any auth/rate-limit caveats

When asked to search, run a local query over fetched bookmark text, author
metadata, links, and expanded quoted posts. For API-backed requests for "new",
"since last time", or recurring review, use
`--all --since-last --update-state` so the saved cutoff cannot advance past
unfetched bookmarks.
Bird can fetch a recent window but does not persist the last reviewed bookmark.

## Failure Handling

- Missing Bird: recommend installing Bird and offer the X API fallback.
- Bird cookie failure: ask the user to log in to `x.com` in a supported browser
  and allow any browser cookie or Keychain prompt.
- Missing X API auth: explain that API access requires a personal Developer app
  and OAuth setup.
- X API `402`: this usually indicates an API payment, credit, or access-plan
  restriction. Use Bird or review the Developer account's access.
- X API `429`: report the rate-limit reset time from the helper.
- Missing scopes: ask the user to update scopes and rerun OAuth setup.
