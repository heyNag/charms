"""A stand-in for api.x.com that tests run on a loopback port.

It serves what the helpers call: the OAuth token endpoint, the authenticated
user, bookmarks, bookmark folders, a folder's post IDs, and post lookup. Each
request is recorded, so a test can check what was sent and in which order.

The helpers reach it only because a test points BASE_URL and TOKEN_URL at it.
"""

from __future__ import annotations

import http.server
import json
import threading
from typing import Any
import urllib.parse

AUTHOR = {"id": "7", "username": "author", "name": "Author"}
PAGE_LIMIT = 100


def post(post_id: str) -> dict[str, str]:
    return {
        "id": post_id,
        "text": f"post {post_id}",
        "author_id": AUTHOR["id"],
        "created_at": "2026-10-01T00:00:00.000Z",
    }


class FakeX:
    """The account, its tokens, and every request made against them."""

    def __init__(self) -> None:
        self.user = {"id": "42", "username": "me", "name": "Me"}
        # Post IDs, newest bookmark first.
        self.bookmarks: list[str] = []
        self.folders: list[dict[str, str]] = []
        self.folder_posts: dict[str, list[str]] = {}
        # Posts that lookup no longer returns, as when one was deleted.
        self.deleted_posts: set[str] = set()
        self.access_tokens: set[str] = set()
        # Refresh token -> the token response it buys. X uses each one once.
        self.refresh_grants: dict[str, dict[str, Any]] = {}
        # Called with each recorded request; may return (status, payload) to answer it.
        self.intercept: Any = None
        # Sent with every response, as X sends its rate-limit headers.
        self.headers: dict[str, str] = {}
        self.requests: list[dict[str, Any]] = []
        self._server = http.server.HTTPServer(("127.0.0.1", 0), self._handler())
        # A short poll keeps stop() quick: shutdown waits for the next poll.
        self._thread = threading.Thread(target=self._server.serve_forever, args=(0.02,), daemon=True)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeX":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(10)

    def paths(self, method: str | None = None) -> list[str]:
        return [item["path"] for item in self.requests if method in (None, item["method"])]

    # -- answers ---------------------------------------------------------

    def answer(self, request: dict[str, Any]) -> tuple[int, Any]:
        if self.intercept is not None:
            scripted = self.intercept(request)
            if scripted is not None:
                return scripted
        path = request["path"]
        if request["method"] == "POST":
            if path == "/2/oauth2/token":
                return self._token(request["form"])
            return 404, {"title": "Not Found"}

        authorization = request["authorization"] or ""
        if not authorization.startswith("Bearer ") or authorization[7:] not in self.access_tokens:
            return 401, {"title": "Unauthorized", "type": "about:blank", "status": 401, "detail": "Unauthorized"}

        query = request["query"]
        if path == "/2/users/me":
            return 200, {"data": self.user}
        if path == "/2/tweets":
            found = [item for item in query.get("ids", "").split(",") if item not in self.deleted_posts]
            return 200, {"data": [post(item) for item in found], "includes": {"users": [AUTHOR]}}

        prefix = f"/2/users/{self.user['id']}/bookmarks"
        if path == prefix:
            return self._page(query, self.bookmarks, post, includes=True)
        if path == f"{prefix}/folders":
            return self._page(query, self.folders, dict)
        if path.startswith(f"{prefix}/folders/"):
            folder_id = path[len(prefix) + len("/folders/") :]
            if folder_id not in self.folder_posts:
                return 404, {"title": "Not Found Error", "detail": "Could not find the folder."}
            return self._page(query, self.folder_posts[folder_id], lambda item: {"id": item})
        if path.startswith("/2/users/"):
            return 403, {"title": "Forbidden", "detail": "The path user is not the authenticated user."}
        return 404, {"title": "Not Found"}

    def _token(self, form: dict[str, str]) -> tuple[int, Any]:
        grant = self.refresh_grants.pop(form.get("refresh_token", ""), None)
        if form.get("grant_type") != "refresh_token" or grant is None:
            return 400, {
                "error": "invalid_request",
                "error_description": "Value passed for the token was invalid.",
            }
        self.access_tokens.add(grant["access_token"])
        return 200, grant

    @staticmethod
    def _page(query: dict[str, str], items: list, shape: Any, includes: bool = False) -> tuple[int, Any]:
        try:
            size = int(query.get("max_results", "100"))
            start = int(query.get("pagination_token", "0"))
        except ValueError:
            return 400, {"title": "Invalid Request", "detail": "A query parameter is not a number."}
        if not 1 <= size <= PAGE_LIMIT:
            return 400, {"title": "Invalid Request", "detail": "max_results must be between 1 and 100."}
        window = items[start : start + size]
        payload: dict[str, Any] = {"data": [shape(item) for item in window], "meta": {"result_count": len(window)}}
        if includes:
            payload["includes"] = {"users": [AUTHOR]}
        if start + size < len(items):
            payload["meta"]["next_token"] = str(start + size)
        return 200, payload

    # -- transport -------------------------------------------------------

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
                request = {
                    "method": self.command,
                    "path": parsed.path,
                    "query": dict(urllib.parse.parse_qsl(parsed.query)),
                    "form": dict(urllib.parse.parse_qsl(body)),
                    "authorization": self.headers.get("Authorization"),
                    "user_agent": self.headers.get("User-Agent"),
                }
                fake.requests.append(request)
                status, payload = fake.answer(request)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for name, value in fake.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = reply  # noqa: N815 - stdlib hook name
            do_POST = reply  # noqa: N815 - stdlib hook name

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler
