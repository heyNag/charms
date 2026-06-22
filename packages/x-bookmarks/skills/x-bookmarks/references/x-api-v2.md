# X API v2 Notes

## Endpoints

- `GET /2/users/me` resolves the authenticated user.
- `GET /2/users/{id}/bookmarks` returns bookmarked posts for the authenticated
  user. The path user ID must be the authenticated user.
- `GET /2/users/{id}/bookmarks/folders` returns bookmark folders.
- `GET /2/users/{id}/bookmarks/folders/{folder_id}` returns post IDs in a
  bookmark folder. The helper hydrates those IDs with `GET /2/tweets`.

## Auth

Use OAuth 2.0 Authorization Code Flow with PKCE. The local callback used by the
helper is:

```text
http://localhost:8739/callback
```

Default scopes:

```text
tweet.read users.read bookmark.read offline.access
```

Only include `bookmark.write` when the workflow needs to create or delete
bookmarks.

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
- Local "new since last review" state lives in
  `~/.local/state/x-bookmarks/state.json`.
- X API access level and pricing can change; use Bird first when paid API
  access is not desired.

Official docs:

- https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token
- https://docs.x.com/x-api/users/get-bookmarks
- https://docs.x.com/x-api/users/get-bookmark-folders
- https://docs.x.com/x-api/users/get-bookmarks-by-folder-id
- https://docs.x.com/x-api/fundamentals/rate-limits
