# X API v2 Notes

## Endpoints

- `GET /2/users/me` resolves the authenticated user.
- `GET /2/users/{id}/bookmarks` returns bookmarked posts for the authenticated
  user. The path user ID must be the authenticated user.
- `GET /2/users/{id}/bookmarks/folders` returns bookmark folders.
- `GET /2/users/{id}/bookmarks/folders/{folder_id}` returns post IDs in a
  bookmark folder. The helper hydrates those IDs with `GET /2/tweets`.

## Auth

Use OAuth 2.0 Authorization Code Flow with PKCE. The helper's default local
callback is:

```text
http://localhost:8739/callback
```

Pass `--redirect-uri` when the X Developer app uses another loopback callback.

Default scopes:

```text
tweet.read users.read bookmark.read offline.access
```

Bundled helpers do not change the X account and need only these scopes. Do not
pass `--include-write-scope` to `x_api_auth.py` for the bundled fetch workflows.
Request `bookmark.write` only for a separate, explicitly authorized workflow
that creates or deletes bookmarks.

The fetch helper also accepts an existing OAuth user access token from
`X_API_ACCESS_TOKEN` or `X_API_BEARER_TOKEN`. `x_api_auth.py --status` checks
saved local OAuth files only and does not inspect either variable.

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
`x-rate-limit-reset` when available. On `429`, it reports the reset time instead
of waiting silently.

## Limitations

- X returns post creation time, not the time a post was bookmarked.
- Local "new since last review" state defaults to
  `~/.local/state/x-bookmarks/state.json`; `X_BOOKMARKS_STATE_FILE` overrides
  that default, and `--state-file PATH` overrides it for one invocation. Keep
  the selected path outside the plugin and source checkout.
- X API access level and pricing can change; use Bird first when paid API
  access is not desired.

Official docs:

- https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token
- https://docs.x.com/x-api/users/get-bookmarks
- https://docs.x.com/x-api/users/get-bookmark-folders
- https://docs.x.com/x-api/users/get-bookmarks-by-folder-id
- https://docs.x.com/x-api/fundamentals/rate-limits
