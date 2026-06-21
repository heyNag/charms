#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/x-bookmarks/scripts/fetch_bookmarks_api.py
# Do not edit directly; edit the source path and run make rebuild-generated.
# END GENERATED FROM SOURCE

"""Fetch and search X bookmarks through X API v2."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from x_api_auth import AuthError, get_valid_token

BASE_URL = "https://api.x.com/2"
MAX_RESULTS = 100
DEFAULT_STATE_FILE = Path(
    os.environ.get("X_BOOKMARKS_STATE_FILE", "~/.local/state/x-bookmarks/state.json")
).expanduser()

TWEET_FIELDS = ",".join(
    [
        "attachments",
        "author_id",
        "conversation_id",
        "created_at",
        "display_text_range",
        "entities",
        "lang",
        "note_tweet",
        "public_metrics",
        "referenced_tweets",
        "text",
    ]
)
EXPANSIONS = ",".join(
    [
        "author_id",
        "attachments.media_keys",
        "referenced_tweets.id",
        "referenced_tweets.id.author_id",
        "referenced_tweets.id.attachments.media_keys",
    ]
)
USER_FIELDS = ",".join(
    [
        "id",
        "name",
        "profile_image_url",
        "public_metrics",
        "username",
        "verified",
        "verified_type",
    ]
)
MEDIA_FIELDS = ",".join(
    [
        "alt_text",
        "duration_ms",
        "height",
        "media_key",
        "preview_image_url",
        "type",
        "url",
        "variants",
        "width",
    ]
)


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.headers = headers or {}

    @property
    def reset_at(self) -> str | None:
        value = self.headers.get("x-rate-limit-reset")
        if not value:
            return None
        try:
            stamp = datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone()
        except ValueError:
            return value
        return stamp.strftime("%Y-%m-%d %H:%M:%S %z")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_json_bytes(raw: bytes) -> Any:
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def rate_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("x-rate-limit-limit", "x-rate-limit-remaining", "x-rate-limit-reset"):
        value = headers.get(key) if hasattr(headers, "get") else None
        if value:
            result[key] = str(value)
    return result


def problem_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                parts = [str(first.get(key)) for key in ("title", "detail", "type") if first.get(key)]
                if parts:
                    return " - ".join(parts)
        if payload.get("detail"):
            return str(payload["detail"])
        if payload.get("title"):
            return str(payload["title"])
    return str(payload) if payload else "empty response"


def api_get(path: str, token: str, params: dict[str, str] | None = None) -> tuple[Any, dict[str, str]]:
    query = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "agent-tools-x-bookmarks/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = parse_json_bytes(response.read())
            return payload, rate_headers(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = parse_json_bytes(raw)
        except json.JSONDecodeError:
            payload = raw.decode("utf-8", errors="replace")
        headers = rate_headers(exc.headers)
        raise ApiError(exc.code, f"HTTP {exc.code}: {problem_summary(payload)}", headers) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, f"request failed: {exc.reason}") from exc


def common_post_params(page_size: int, pagination_token: str | None = None) -> dict[str, str]:
    params = {
        "max_results": str(page_size),
        "tweet.fields": TWEET_FIELDS,
        "expansions": EXPANSIONS,
        "user.fields": USER_FIELDS,
        "media.fields": MEDIA_FIELDS,
    }
    if pagination_token:
        params["pagination_token"] = pagination_token
    return params


def get_me(token: str) -> dict[str, Any]:
    payload, _headers = api_get("/users/me", token, {"user.fields": "id,username,name"})
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ApiError(0, "could not resolve authenticated X user")
    return data


def fetch_bookmark_pages(
    token: str,
    user_id: str,
    count: int,
    fetch_all: bool,
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    bookmarks: list[dict[str, Any]] = []
    next_token: str | None = None
    last_headers: dict[str, str] = {}
    pages = 0

    while True:
        remaining = None if fetch_all else count - len(bookmarks)
        if remaining is not None and remaining <= 0:
            break
        page_size = MAX_RESULTS if remaining is None else max(1, min(MAX_RESULTS, remaining))
        payload, last_headers = api_get(
            f"/users/{user_id}/bookmarks",
            token,
            common_post_params(page_size, next_token),
        )
        bookmarks.extend(normalize_posts(payload))
        pages += 1
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        next_token = meta.get("next_token") if isinstance(meta, dict) else None
        if not next_token:
            break
        if max_pages is not None and pages >= max_pages:
            break

    return bookmarks, last_headers


def fetch_folders(
    token: str,
    user_id: str,
    count: int,
    fetch_all: bool,
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    folders: list[dict[str, Any]] = []
    next_token: str | None = None
    last_headers: dict[str, str] = {}
    pages = 0

    while True:
        remaining = None if fetch_all else count - len(folders)
        if remaining is not None and remaining <= 0:
            break
        page_size = MAX_RESULTS if remaining is None else max(1, min(MAX_RESULTS, remaining))
        params = {"max_results": str(page_size)}
        if next_token:
            params["pagination_token"] = next_token
        payload, last_headers = api_get(f"/users/{user_id}/bookmarks/folders", token, params)
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if isinstance(data, list):
            folders.extend(item for item in data if isinstance(item, dict))
        pages += 1
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        next_token = meta.get("next_token") if isinstance(meta, dict) else None
        if not next_token:
            break
        if max_pages is not None and pages >= max_pages:
            break

    return folders, last_headers


def fetch_folder_post_ids(
    token: str,
    user_id: str,
    folder_id: str,
    count: int,
    fetch_all: bool,
    max_pages: int | None,
) -> tuple[list[str], dict[str, str]]:
    ids: list[str] = []
    next_token: str | None = None
    last_headers: dict[str, str] = {}
    pages = 0

    while True:
        remaining = None if fetch_all else count - len(ids)
        if remaining is not None and remaining <= 0:
            break
        page_size = MAX_RESULTS if remaining is None else max(1, min(MAX_RESULTS, remaining))
        params = {"max_results": str(page_size)}
        if next_token:
            params["pagination_token"] = next_token
        payload, last_headers = api_get(
            f"/users/{user_id}/bookmarks/folders/{folder_id}",
            token,
            params,
        )
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
        pages += 1
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        next_token = meta.get("next_token") if isinstance(meta, dict) else None
        if not next_token:
            break
        if max_pages is not None and pages >= max_pages:
            break

    return ids, last_headers


def hydrate_posts(token: str, post_ids: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not post_ids:
        return [], {}
    by_id: dict[str, dict[str, Any]] = {}
    last_headers: dict[str, str] = {}
    for start in range(0, len(post_ids), MAX_RESULTS):
        batch = post_ids[start : start + MAX_RESULTS]
        payload, last_headers = api_get(
            "/tweets",
            token,
            {
                "ids": ",".join(batch),
                "tweet.fields": TWEET_FIELDS,
                "expansions": EXPANSIONS,
                "user.fields": USER_FIELDS,
                "media.fields": MEDIA_FIELDS,
            },
        )
        for item in normalize_posts(payload):
            by_id[item["id"]] = item
    return [by_id[item] for item in post_ids if item in by_id], last_headers


def long_text(tweet: dict[str, Any]) -> str:
    note = tweet.get("note_tweet")
    if isinstance(note, dict) and note.get("text"):
        return str(note["text"])
    return str(tweet.get("text", ""))


def user_url(username: str | None) -> str | None:
    if not username:
        return None
    return f"https://x.com/{username}"


def post_url(username: str | None, post_id: str) -> str:
    if username:
        return f"https://x.com/{username}/status/{post_id}"
    return f"https://x.com/i/web/status/{post_id}"


def normalize_posts(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    includes = payload.get("includes", {})
    if not isinstance(includes, dict):
        includes = {}
    users = {
        str(user["id"]): user
        for user in includes.get("users", [])
        if isinstance(user, dict) and user.get("id")
    }
    included_tweets = {
        str(tweet["id"]): tweet
        for tweet in includes.get("tweets", [])
        if isinstance(tweet, dict) and tweet.get("id")
    }
    media = {
        str(item["media_key"]): item
        for item in includes.get("media", [])
        if isinstance(item, dict) and item.get("media_key")
    }
    result: list[dict[str, Any]] = []
    data = payload.get("data", [])
    if not isinstance(data, list):
        return result

    for tweet in data:
        if not isinstance(tweet, dict) or not tweet.get("id"):
            continue
        post_id = str(tweet["id"])
        author = users.get(str(tweet.get("author_id")), {})
        username = str(author.get("username")) if author.get("username") else None
        attachments = tweet.get("attachments") if isinstance(tweet.get("attachments"), dict) else {}
        media_items = []
        for key in attachments.get("media_keys", []) if isinstance(attachments, dict) else []:
            item = media.get(str(key))
            if item:
                media_items.append(item)

        refs = []
        for ref in tweet.get("referenced_tweets", []) or []:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get("id", ""))
            ref_tweet = included_tweets.get(ref_id, {})
            ref_author = users.get(str(ref_tweet.get("author_id")), {}) if ref_tweet else {}
            ref_username = str(ref_author.get("username")) if ref_author.get("username") else None
            refs.append(
                {
                    "type": ref.get("type"),
                    "id": ref_id,
                    "text": long_text(ref_tweet) if ref_tweet else None,
                    "author": {
                        "id": ref_author.get("id"),
                        "username": ref_username,
                        "name": ref_author.get("name"),
                        "url": user_url(ref_username),
                    }
                    if ref_author
                    else None,
                    "url": post_url(ref_username, ref_id) if ref_id else None,
                }
            )

        result.append(
            {
                "id": post_id,
                "url": post_url(username, post_id),
                "text": long_text(tweet),
                "created_at": tweet.get("created_at"),
                "lang": tweet.get("lang"),
                "author": {
                    "id": author.get("id"),
                    "username": username,
                    "name": author.get("name"),
                    "url": user_url(username),
                    "verified": author.get("verified"),
                    "verified_type": author.get("verified_type"),
                    "public_metrics": author.get("public_metrics"),
                },
                "public_metrics": tweet.get("public_metrics"),
                "entities": tweet.get("entities"),
                "media": media_items,
                "referenced_tweets": refs,
                "source": "x-api-v2",
            }
        )
    return result


def searchable_text(item: dict[str, Any]) -> str:
    parts: list[str] = [
        str(item.get("text", "")),
        str(item.get("url", "")),
    ]
    author = item.get("author")
    if isinstance(author, dict):
        parts.extend(str(author.get(key, "")) for key in ("username", "name", "url"))
    for ref in item.get("referenced_tweets", []) or []:
        if isinstance(ref, dict):
            parts.append(str(ref.get("text", "")))
            ref_author = ref.get("author")
            if isinstance(ref_author, dict):
                parts.extend(str(ref_author.get(key, "")) for key in ("username", "name", "url"))
    return "\n".join(parts).lower()


def filter_query(items: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    if not query:
        return items
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return items
    return [item for item in items if all(term in searchable_text(item) for term in terms)]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def state_scope(folder_id: str | None) -> str:
    return f"folder:{folder_id}" if folder_id else "all"


def state_last_seen_id(state: dict[str, Any], scope: str) -> str | None:
    scopes = state.get("scopes")
    if isinstance(scopes, dict):
        entry = scopes.get(scope)
        if isinstance(entry, dict) and entry.get("last_seen_id"):
            return str(entry["last_seen_id"])
    if scope == "all" and state.get("last_seen_id"):
        return str(state["last_seen_id"])
    return None


def update_last_seen(state: dict[str, Any], scope: str, newest_id: str) -> dict[str, Any]:
    updated = dict(state)
    scopes = updated.get("scopes")
    if not isinstance(scopes, dict):
        scopes = {}
    scopes[scope] = {
        "last_seen_id": newest_id,
        "updated_at": utc_now(),
    }
    updated["scopes"] = scopes
    if scope == "all":
        updated["last_seen_id"] = newest_id
        updated["updated_at"] = scopes[scope]["updated_at"]
    return updated


def since_last(items: list[dict[str, Any]], state: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    last_seen_id = state_last_seen_id(state, scope)
    if not last_seen_id:
        return items
    result: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("id")) == str(last_seen_id):
            break
        result.append(item)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and search X bookmarks through X API v2.")
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of items to fetch.")
    parser.add_argument("--all", action="store_true", help="Fetch all available pages.")
    parser.add_argument("--max-pages", type=int, help="Safety cap for paginated runs.")
    parser.add_argument("--folders", action="store_true", help="List bookmark folders instead of posts.")
    parser.add_argument("--folder-id", help="Fetch bookmarks from a bookmark folder.")
    parser.add_argument("--query", help="Local text query over fetched bookmark data.")
    parser.add_argument("--since-last", action="store_true", help="Return items before the saved last_seen_id.")
    parser.add_argument("--update-state", action="store_true", help="Record newest fetched bookmark as last_seen_id.")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2
    if args.folders and args.folder_id:
        print("error: use either --folders or --folder-id, not both", file=sys.stderr)
        return 2

    try:
        token = get_valid_token()
        user = get_me(token)
        user_id = str(user["id"])
        headers: dict[str, str] = {}

        if args.folders:
            folders, headers = fetch_folders(token, user_id, args.count, args.all, args.max_pages)
            output: dict[str, Any] = {
                "data": folders,
                "meta": {
                    "kind": "bookmark-folders",
                    "count": len(folders),
                    "fetched_at": utc_now(),
                    "authenticated_user": user,
                    "rate_limit": headers,
                },
            }
        else:
            if args.folder_id:
                post_ids, headers = fetch_folder_post_ids(
                    token,
                    user_id,
                    args.folder_id,
                    args.count,
                    args.all,
                    args.max_pages,
                )
                items, hydrate_headers = hydrate_posts(token, post_ids)
                headers = hydrate_headers or headers
                for item in items:
                    item["folder_id"] = args.folder_id
            else:
                items, headers = fetch_bookmark_pages(
                    token,
                    user_id,
                    args.count,
                    args.all,
                    args.max_pages,
                )

            state = load_state(args.state_file)
            scope = state_scope(args.folder_id)
            fetched_items = list(items)
            newest_id = str(fetched_items[0]["id"]) if fetched_items else None
            pre_filter_count = len(fetched_items)
            if args.since_last:
                items = since_last(items, state, scope)
            items = filter_query(items, args.query)
            if args.update_state and newest_id:
                save_state(args.state_file, update_last_seen(state, scope, newest_id))

            output = {
                "data": items,
                "meta": {
                    "kind": "bookmarks",
                    "count": len(items),
                    "fetched_count": pre_filter_count,
                    "query": args.query,
                    "since_last": args.since_last,
                    "state_scope": scope,
                    "state_file": str(args.state_file.expanduser()),
                    "fetched_at": utc_now(),
                    "authenticated_user": user,
                    "rate_limit": headers,
                },
            }

        print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
        return 0
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("fix: run python3 scripts/x_api_auth.py --client-id YOUR_X_CLIENT_ID", file=sys.stderr)
        return 1
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.status == 429 and exc.reset_at:
            print(f"fix: retry after {exc.reset_at}", file=sys.stderr)
            return 75
        if exc.status == 402:
            print(
                "fix: use the Bird no-credit backend first: "
                "scripts/fetch_bookmarks_bird.sh --count 25",
                file=sys.stderr,
            )
            print(
                "fix: if you explicitly want the official X API path, add X API credits or an eligible plan, then retry",
                file=sys.stderr,
            )
            return 1
        print("fix: check X Developer app scopes and API access level", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
