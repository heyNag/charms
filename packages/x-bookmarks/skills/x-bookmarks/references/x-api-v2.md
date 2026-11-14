# X API v2 Notes

## Endpoints

- `GET /2/users/me` resolves the authenticated user.
- `GET /2/users/{id}/bookmarks` returns bookmarked posts for the authenticated
  user. The path user ID must be the authenticated user.
- `GET /2/users/{id}/bookmarks/folders` returns bookmark folders.
- `GET /2/users/{id}/bookmarks/folders/{folder_id}` returns post IDs in a
  bookmark folder. The helper hydrates those IDs with `GET /2/tweets`. X
  documents `folder_id` as 1 to 19 digits, and `--folder-id` accepts nothing
  else, so no other text can reach the request path.

## Auth

Use OAuth 2.0 Authorization Code Flow with PKCE. The helper's default local
callback for a new setup is:

```text
http://127.0.0.1:8739/callback
```

X's developer documentation says to use `http://127.0.0.1`, not `localhost`,
for local development, and that a callback URL must match the app's entry
exactly. The helper listens on 127.0.0.1 only, so a `localhost` callback also
depends on the browser resolving that name to IPv4. A setup saved with another
loopback callback keeps it; `x_api_auth.py --status` shows the saved URL and,
for a `localhost` one, the command that switches it. Pass `--redirect-uri`
when the X Developer app uses another loopback callback.

Default scopes:

```text
tweet.read users.read bookmark.read offline.access
```

Bundled helpers do not change the X account and need only these scopes. Do not
pass `--include-write-scope` to `x_api_auth.py` for the bundled fetch workflows.
Request `bookmark.write` only for a separate, explicitly authorized workflow
that creates or deletes bookmarks. Setup never reuses saved scopes: each run
requests these defaults plus only its own `--include-write-scope`/`--scope`
flags, and rejects scope names X does not document.

The callback server answers only the redirect path, ignores other requests,
and gives up after 5 minutes, even while a slow client is still connected. If
another setup run, or another program listening on 127.0.0.1, holds the
callback port, setup exits with an error: stop it or pass `--redirect-uri` with
a free loopback port registered in the app. A program listening on all
interfaces or on IPv6 is not detected; the browser may reach it instead, and
setup then times out. API and token requests refuse redirects so credentials
never follow a response to another host.

Setup prints the authorization URL and opens it in the default browser.
`--no-browser` only prints it, for a machine where no browser can start, such
as one reached over SSH. The browser that approves access is sent back to the
callback URL, so it must reach the port on the machine where setup is running:
open the URL on that machine, or forward the port first, which for the default
callback is `ssh -L 8739:127.0.0.1:8739 HOST`, and open the URL on your own.

The fetch helper also accepts an existing OAuth user access token from
`X_API_ACCESS_TOKEN` or `X_API_BEARER_TOKEN`. `x_api_auth.py --status` checks
saved local OAuth files only and does not inspect either variable.

A saved access token is refreshed when it is within two minutes of its
recorded expiry. If X still answers `401`, because the token was revoked or
ran out early, the fetch helper refreshes it once and repeats that one
request, so pages already fetched are not requested again. A second `401`
ends the run. A token from the environment is never refreshed, since the
helper holds no refresh token for it. `x_api_auth.py --refresh` refreshes the
saved login on request, without printing it.

## Query Shape

Bookmark lookup supports `max_results`, `pagination_token`, `tweet.fields`,
`user.fields`, `media.fields`, `place.fields`, `poll.fields`, and `expansions`.
The helper does not use `since_id` for bookmarks.

The helper requests enough fields for useful agent summaries:

- post text, long-form `note_tweet`, language, entities, attachments, quoted
  posts, and public metrics
- author username, display name, profile image, verification, and public metrics
- media URL, preview URL, type, dimensions, alt text, and variants

## Rate Limits

The helper reports `x-rate-limit-limit`, `x-rate-limit-remaining`, and
`x-rate-limit-reset` when available. On `429`, it exits with status 75 and
reports the reset time, when X sends a usable one, instead of waiting silently.

## Limitations

- X returns post creation time, not the time a post was bookmarked. Review
  state therefore stores the newest 50 reviewed bookmark IDs per scope and, in
  a fetch that reached the end of the list, stops where those still bookmarked
  begin. A reviewed post bookmarked again moves to the top, so it is listed as
  new. Only when none is present in such a full fetch does it compare post
  creation time, reported as `meta.cutoff_mode: "created_at_fallback"`.
- A fetch that stops with pages left (a `--count` window, or
  `--all --max-pages`) cannot tell the cutoff from reviewed posts bookmarked
  again above unfetched new ones, so `--since-last` returns every fetched
  bookmark as `meta.cutoff_mode: "unfiltered"`.
- `--update-state` saves the cutoff only when the fetch reached the end of the
  list (`--all` without `--max-pages`; `meta.cutoff_reached`), and refuses
  `--query`.
- `--stop-after-known N` (5 to 50, with `--all --since-last`) trades that
  certainty for fewer requests. It stops at the first N saved bookmarks in a
  row, in saved order with gaps allowed, treats the fetch as complete, and
  reports `meta.cutoff_mode: "early_stop"` and `meta.stopped_early: true`.
  At least N reviewed posts bookmarked again in their old order, with nothing
  between them, look the same; new bookmarks below them are then missed and,
  with `--update-state`, marked as reviewed. Without a row that long the
  fetch reads to the end as usual.
- Local "new since last review" state defaults to
  `~/.local/state/x-bookmarks/state.json`; `X_BOOKMARKS_STATE_FILE` overrides
  that default, and `--state-file PATH` overrides it for one invocation. Keep
  the selected path outside the plugin and source checkout.
- X API access level and pricing can change; use Bird first when paid API
  access is not desired.

Official docs:

- https://docs.x.com/fundamentals/developer-apps
- https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token
- https://docs.x.com/x-api/users/get-bookmarks
- https://docs.x.com/x-api/users/get-bookmark-folders
- https://docs.x.com/x-api/users/get-bookmarks-by-folder-id
- https://docs.x.com/x-api/fundamentals/rate-limits
