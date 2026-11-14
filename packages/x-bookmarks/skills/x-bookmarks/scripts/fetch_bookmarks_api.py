#!/usr/bin/env python3
"""Fetch and search X bookmarks through X API v2."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import functools
import http.client
import json
from pathlib import Path
import sys
from typing import Any, Callable, Optional
import urllib.error
import urllib.parse
import urllib.request

# Stops here with one clear line when this Python is older than the floor.
import python_floor  # noqa: F401
import plugin_version
from review_state import (  # noqa: F401 - the state functions stay reachable from this module
    FOLDER_ID,
    MIN_KNOWN_RUN,
    STATE_ANCHORS,
    STATE_FIX,
    StateError,
    default_state_file,
    known_run,
    load_state,
    review,
    save_state,
    since_last,
    state_anchor_ids,
    state_scope,
    update_last_seen,
    utc_now,
)
from x_api_auth import AuthError, get_valid_token, open_request, token_variable

BASE_URL = "https://api.x.com/2"
MAX_RESULTS = 100
DEFAULT_STATE_FILE = default_state_file()
# Given the IDs fetched so far, newest first, says whether to stop paging.
Stop = Optional[Callable[[list], bool]]

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
        except (ValueError, OverflowError, OSError):
            # Not an epoch time this platform can represent; report no reset time.
            return None
        return stamp.strftime("%Y-%m-%d %H:%M:%S %z")


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
            "User-Agent": plugin_version.USER_AGENT,
        },
    )
    try:
        with open_request(request, timeout=45) as response:
            payload = parse_json_bytes(response.read())
            return payload, rate_headers(response.headers)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except (http.client.HTTPException, OSError):
            # A cut-short error body still leaves the status and rate headers.
            raw = b""
        finally:
            exc.close()
        try:
            payload = parse_json_bytes(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # A proxy or CDN error page can be any text in any charset.
            payload = raw.decode("utf-8", errors="replace")
        headers = rate_headers(exc.headers)
        raise ApiError(exc.code, f"HTTP {exc.code}: {problem_summary(payload)}", headers) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, f"request failed: {exc.reason}") from exc
    except (http.client.HTTPException, OSError) as exc:
        # The connection dropped or the body was cut short after the headers.
        raise ApiError(0, f"request failed: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError(0, f"response was not valid JSON: {exc}") from exc


class Session:
    """The access token for one run, replaced once if X rejects it.

    X answers 401 when a saved token was revoked or ran out early. The first
    401 refreshes the saved login and repeats that one request, so pages
    already fetched are not requested again. A second 401 is reported. A token
    from the environment is never refreshed: there is no refresh token for it.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self.refreshed = False

    def get(self, path: str, params: dict[str, str] | None = None) -> tuple[Any, dict[str, str]]:
        try:
            return api_get(path, self.token, params)
        except ApiError as exc:
            if exc.status != 401 or self.refreshed or token_variable():
                raise
        self.refreshed = True
        try:
            self.token = get_valid_token(force_refresh=True)
        except AuthError as exc:
            raise AuthError(
                f"X rejected the saved access token (HTTP 401), and refreshing it failed: {exc}"
            ) from exc
        print("note: X rejected the saved access token; refreshed it and repeated the request", file=sys.stderr)
        return api_get(path, self.token, params)


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


def get_me(session: Session) -> dict[str, Any]:
    payload, _headers = session.get("/users/me", {"user.fields": "id,username,name"})
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ApiError(0, "could not resolve authenticated X user")
    return data


def fetch_bookmark_pages(
    session: Session,
    user_id: str,
    count: int,
    fetch_all: bool,
    max_pages: int | None,
    stop: Stop = None,
) -> tuple[list[dict[str, Any]], dict[str, str], bool, bool]:
    """Return bookmarks, rate headers, whether pagination reached the end, and whether stop ended it."""
    bookmarks: list[dict[str, Any]] = []
    next_token: str | None = None
    last_headers: dict[str, str] = {}
    pages = 0
    stopped = False

    while True:
        remaining = None if fetch_all else count - len(bookmarks)
        if remaining is not None and remaining <= 0:
            break
        page_size = MAX_RESULTS if remaining is None else max(1, min(MAX_RESULTS, remaining))
        payload, last_headers = session.get(
            f"/users/{user_id}/bookmarks",
            common_post_params(page_size, next_token),
        )
        bookmarks.extend(normalize_posts(payload))
        pages += 1
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        next_token = meta.get("next_token") if isinstance(meta, dict) else None
        if not next_token:
            break
        if stop is not None and stop([item["id"] for item in bookmarks]):
            stopped = True
            break
        if max_pages is not None and pages >= max_pages:
            break

    return bookmarks, last_headers, not next_token, stopped


def fetch_folders(
    session: Session,
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
        payload, last_headers = session.get(f"/users/{user_id}/bookmarks/folders", params)
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
    session: Session,
    user_id: str,
    folder_id: str,
    count: int,
    fetch_all: bool,
    max_pages: int | None,
    stop: Stop = None,
) -> tuple[list[str], dict[str, str], bool, bool]:
    """Return folder post IDs, rate headers, whether pagination reached the end, and whether stop ended it."""
    ids: list[str] = []
    next_token: str | None = None
    last_headers: dict[str, str] = {}
    pages = 0
    stopped = False

    while True:
        remaining = None if fetch_all else count - len(ids)
        if remaining is not None and remaining <= 0:
            break
        page_size = MAX_RESULTS if remaining is None else max(1, min(MAX_RESULTS, remaining))
        params = {"max_results": str(page_size)}
        if next_token:
            params["pagination_token"] = next_token
        payload, last_headers = session.get(f"/users/{user_id}/bookmarks/folders/{folder_id}", params)
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
        if stop is not None and stop(ids):
            stopped = True
            break
        if max_pages is not None and pages >= max_pages:
            break

    return ids, last_headers, not next_token, stopped


def hydrate_posts(session: Session, post_ids: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not post_ids:
        return [], {}
    by_id: dict[str, dict[str, Any]] = {}
    last_headers: dict[str, str] = {}
    for start in range(0, len(post_ids), MAX_RESULTS):
        batch = post_ids[start : start + MAX_RESULTS]
        payload, last_headers = session.get(
            "/tweets",
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and search X bookmarks through X API v2.")
    parser.add_argument("--version", action="version", version=plugin_version.VERSION_LINE)
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of items to fetch.")
    parser.add_argument("--all", action="store_true", help="Fetch all available pages.")
    parser.add_argument("--max-pages", type=int, help="Safety cap for paginated runs.")
    parser.add_argument("--folders", action="store_true", help="List bookmark folders instead of posts.")
    parser.add_argument(
        "--folder-id",
        help="Fetch bookmarks from the bookmark folder with this numeric ID, as --folders lists it.",
    )
    parser.add_argument("--query", help="Local text query over fetched bookmark data.")
    parser.add_argument(
        "--since-last",
        action="store_true",
        help="Return items bookmarked after the saved review cutoff.",
    )
    parser.add_argument(
        "--update-state",
        action="store_true",
        help="Save the newest fetched bookmarks as the cutoff after a fetch that reached the end of the list.",
    )
    parser.add_argument(
        "--stop-after-known",
        type=int,
        metavar="N",
        help=(
            "With --all --since-last, stop fetching once N already reviewed bookmarks appear in a row "
            f"({MIN_KNOWN_RUN} to {STATE_ANCHORS}). Saves requests, but misses new bookmarks that sit "
            "below at least N reviewed posts bookmarked again in their old order."
        ),
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2
    if args.folders and args.folder_id is not None:
        print("error: use either --folders or --folder-id, not both", file=sys.stderr)
        return 2
    if args.folder_id is not None and not FOLDER_ID.fullmatch(args.folder_id):
        print("error: --folder-id must be a folder's numeric ID of 1 to 19 digits", file=sys.stderr)
        print("fix: list the folders with --folders, then pass one of their IDs", file=sys.stderr)
        return 2
    if args.update_state and args.query:
        print(
            "error: --update-state cannot be combined with --query; "
            "it would mark bookmarks the query hid as reviewed",
            file=sys.stderr,
        )
        print("fix: run --all --since-last --update-state without --query", file=sys.stderr)
        return 2
    if args.stop_after_known is not None:
        if not (args.all and args.since_last) or args.folders:
            print("error: --stop-after-known works only with --all --since-last", file=sys.stderr)
            return 2
        if not MIN_KNOWN_RUN <= args.stop_after_known <= STATE_ANCHORS:
            print(
                f"error: --stop-after-known must be between {MIN_KNOWN_RUN} and {STATE_ANCHORS}: "
                f"a shorter row is too easy to mistake for the cutoff, and only {STATE_ANCHORS} "
                "reviewed bookmarks are saved",
                file=sys.stderr,
            )
            return 2

    state_file = args.state_file.expanduser()
    state: dict[str, Any] = {}
    if not args.folders and (args.since_last or args.update_state):
        # Before the first request: a damaged file must not cost API calls.
        try:
            state = load_state(state_file)
        except StateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            print(STATE_FIX, file=sys.stderr)
            return 1

    try:
        session = Session(get_valid_token())
        user = get_me(session)
        user_id = str(user["id"])
        headers: dict[str, str] = {}
        state_saved = True
        stop: Stop = None
        if args.stop_after_known is not None:
            stop = functools.partial(
                known_run,
                anchors=state_anchor_ids(state, state_scope(args.folder_id)),
                needed=args.stop_after_known,
            )

        if args.folders:
            folders, headers = fetch_folders(session, user_id, args.count, args.all, args.max_pages)
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
                post_ids, headers, reached_end, stopped_early = fetch_folder_post_ids(
                    session,
                    user_id,
                    args.folder_id,
                    args.count,
                    args.all,
                    args.max_pages,
                    stop,
                )
                items, hydrate_headers = hydrate_posts(session, post_ids)
                headers = hydrate_headers or headers
                for item in items:
                    item["folder_id"] = args.folder_id
            else:
                items, headers, reached_end, stopped_early = fetch_bookmark_pages(
                    session,
                    user_id,
                    args.count,
                    args.all,
                    args.max_pages,
                    stop,
                )

            reviewed = review(
                items,
                state,
                state_scope(args.folder_id),
                state_file,
                reached_end=reached_end,
                apply_cutoff=args.since_last,
                save_cutoff=args.update_state,
                stopped_early=stopped_early,
            )
            for line in reviewed.messages:
                print(line, file=sys.stderr)
            state_saved = not reviewed.failed
            shown = filter_query(reviewed.items, args.query)

            output = {
                "data": shown,
                "meta": {
                    "kind": "bookmarks",
                    "count": len(shown),
                    "fetched_count": len(items),
                    "query": args.query,
                    **reviewed.meta,
                    "fetched_at": utc_now(),
                    "authenticated_user": user,
                    "rate_limit": headers,
                },
            }

        print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
        # A state file that could not be saved is an error, reported above;
        # the bookmarks were still printed because the requests were made.
        return 0 if state_saved else 1
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("fix: run python3 scripts/x_api_auth.py --client-id YOUR_X_CLIENT_ID", file=sys.stderr)
        return 1
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.status == 429:
            reset_at = exc.reset_at
            if reset_at:
                print(f"fix: retry after {reset_at}", file=sys.stderr)
            else:
                print("fix: wait for the X API rate limit window to reset, then retry", file=sys.stderr)
            return 75
        if exc.status == 401:
            variable = token_variable()
            if variable:
                print(
                    f"fix: X rejected the access token in {variable}; set a current one, "
                    "or unset it to use the saved login",
                    file=sys.stderr,
                )
            else:
                print(
                    "fix: X rejected the saved login even after a refresh; rerun setup with "
                    "python3 scripts/x_api_auth.py",
                    file=sys.stderr,
                )
            return 1
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
