---
name: x-bookmarks
description: Fetch, search, and turn X/Twitter bookmarks into action using Bird cookie auth or X API v2. Use when the user asks about X/Twitter bookmarks, bookmark digests, bookmark search, saved posts, no-credit X bookmark access, or recurring review of bookmarked posts.
argument-hint: "[digest|search QUERY|folders|since-last] [--count N]"
tags: x, twitter, bookmarks, bird, local
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---
<!-- BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/SKILL.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->


# x-bookmarks

Use this skill when a user asks to fetch, search, review, summarize, digest, or
act on X/Twitter bookmarks, saved posts, bookmark folders, or recurring
bookmark reviews.

## Operating Rules

- Prefer Bird via `bird.fast` first because it uses the logged-in browser
  session and avoids paid X API credits.
- Use X API v2 only when Bird cannot work, when the user explicitly asks for
  the official API path, or when folder/API-specific behavior is needed.
- Keep OAuth scopes read-only by default:
  `tweet.read users.read bookmark.read offline.access`.
- Add `bookmark.write` only when the user explicitly asks to create or delete
  bookmarks.
- Do not ask for browser cookies, `auth_token`, `ct0`, OAuth tokens, access
  tokens, refresh tokens, or client secrets in chat.
- Do not print tokens, cookies, account IDs, raw local auth files, bookmark
  exports, or search indexes.
- Store local auth and review state outside this repo:
  `~/.config/x-bookmarks/`, `~/.local/state/x-bookmarks/`, and
  `~/.config/bird/`.
- If auth fails, report the status and a safe fix command without exposing
  secrets.

## Invocation

From this skill directory, check both local backends:

```sh
command -v bird >/dev/null && bird check --plain
python3 scripts/x_api_auth.py --status
```

Fetch recent bookmarks:

```sh
scripts/fetch_bookmarks_bird.sh --count 25
python3 scripts/fetch_bookmarks_api.py --count 25 --pretty
```

Search fetched bookmarks locally:

```sh
scripts/fetch_bookmarks_bird.sh --all
python3 scripts/fetch_bookmarks_api.py --all --query "agents mcp" --pretty
```

Fetch new results since the last recorded review:

```sh
scripts/fetch_bookmarks_bird.sh --count 100
python3 scripts/fetch_bookmarks_api.py --count 100 --since-last --update-state --pretty
```

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

Use OAuth 2.0 Authorization Code Flow with PKCE. The local callback is:

```text
http://localhost:8739/callback
```

Required read scopes:

```text
tweet.read users.read bookmark.read offline.access
```

If local auth is missing and the user wants the official API path:

1. Ask the user to create or select an X Developer app.
2. Ask them to enable OAuth 2.0 / PKCE user authentication.
3. Ask them to add the callback URL exactly.
4. Ask for the OAuth 2.0 Client ID.
5. If the app has a client secret, collect it through a safe local channel.
   Prefer a hidden local prompt and pass it with `--client-secret-stdin`.
6. Run `python3 scripts/x_api_auth.py --client-id CLIENT_ID`.
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
metadata, links, and expanded quoted posts. If the user asks for "new",
"since last time", or recurring review, use `--since-last --update-state`.

## Failure Handling

- Missing Bird: recommend installing Bird and offer the X API fallback.
- Bird cookie failure: ask the user to log in to `x.com` in a supported browser
  and allow any browser cookie or Keychain prompt.
- Missing X API auth: explain that API access requires a personal Developer app
  and OAuth setup.
- X API `402`: auth is working, but the Developer account cannot fulfill API
  bookmark requests. Use Bird unless the user explicitly wants API credits.
- X API `429`: report the rate-limit reset time from the helper.
- Missing scopes: ask the user to update scopes and rerun OAuth setup.
