"""A stand-in for `bird bookmarks --json`, answering as Bird 0.8.0 does.

It holds an account's bookmarks, newest first, and answers one Bird command
line at a time. The paging loop follows Bird's own: 20 posts to a request, a
JSON list for a window (--count), and an object with "tweets" and
"nextCursor" for --all or --cursor. nextCursor is null once a request came
back empty and a cursor when --max-pages stopped the read first. X names a
cursor on every page, the last one too, so Bird finds the end of the list
only by asking once more.

Every run and every page request is counted, so a test can check what was
asked of Bird and what it cost. Nothing here reaches X or a browser.
"""

from __future__ import annotations

import json
import re
from typing import Any

PAGE = 20
# Flags and options of `bird bookmarks` that the helper may pass.
FLAGS = {"--json", "--plain", "--all"}
OPTIONS = {
    "--count",
    "--max-pages",
    "--cursor",
    "--folder-id",
    "--cookie-source",
    "--chrome-profile",
    "--chrome-profile-dir",
    "--firefox-profile",
}
# Bird takes a folder ID of five digits or more.
FOLDER_ID = re.compile(r"[0-9]{5,}")


def post(post_id: str, **fields: Any) -> dict[str, Any]:
    """A post as Bird prints it; fake_x.post is the same post as the X API sends it."""
    return {
        "id": post_id,
        "text": f"post {post_id}",
        "createdAt": "Thu Oct 01 00:00:00 +0000 2026",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "conversationId": post_id,
        "author": {"username": "author", "name": "Author"},
        "authorId": "7",
        **fields,
    }


class FakeBird:
    """The account's bookmarks and every Bird run made against them."""

    def __init__(self) -> None:
        # Post IDs, newest bookmark first.
        self.bookmarks: list[str] = []
        self.folders: dict[str, list[str]] = {}
        # Fields to set on a post, by post ID.
        self.fields: dict[str, dict[str, Any]] = {}
        # Written to standard error on every run, as Bird writes its warnings.
        self.stderr = ""
        # Called with each command line; may return (status, stdout, stderr) to answer it.
        self.intercept: Any = None
        self.runs: list[list[str]] = []
        self.timeouts: list[float] = []
        self.pages = 0

    def run(self, command: list[str], timeout: float) -> tuple[int, bytes, str]:
        """Answer one command line. The signature is that of the helper's run_bird."""
        self.runs.append(list(command))
        self.timeouts.append(timeout)
        if self.intercept is not None:
            scripted = self.intercept(command)
            if scripted is not None:
                return scripted

        flags, options = self.parse(command)
        if "--json" not in flags:
            raise AssertionError(f"without --json bird prints text: {command}")
        items = self.bookmarks
        if "--folder-id" in options:
            if not FOLDER_ID.fullmatch(options["--folder-id"]):
                return 1, b"", "[err] Invalid --folder-id. Expected numeric ID or https://x.com/i/bookmarks/<id>.\n"
            items = self.folders.get(options["--folder-id"], [])

        paged = "--all" in flags or "--cursor" in options
        if "--max-pages" in options and not paged:
            return 1, b"", "[err] --max-pages requires --all or --cursor.\n"
        if paged:
            max_pages = int(options["--max-pages"]) if "--max-pages" in options else None
            held, next_cursor = self.read(items, None, options.get("--cursor"), max_pages)
            answer: Any = {"tweets": self.posts(held), "nextCursor": next_cursor}
        else:
            held, _cursor = self.read(items, int(options.get("--count", "20")), None, None)
            answer = self.posts(held)
        # Bird prints with JSON.stringify, which leaves other scripts as they are.
        return 0, (json.dumps(answer, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), self.stderr

    @staticmethod
    def parse(command: list[str]) -> tuple[set[str], dict[str, str]]:
        if command[1] != "bookmarks":
            raise AssertionError(f"not a bookmarks command: {command}")
        flags: set[str] = set()
        options: dict[str, str] = {}
        for argument in command[2:]:
            name, equals, value = argument.partition("=")
            if equals and name in OPTIONS:
                options[name] = value
            elif argument in FLAGS:
                flags.add(argument)
            else:
                raise AssertionError(f"bird bookmarks has no such option, or it needs a value: {argument}")
        return flags, options

    def posts(self, held: list[str]) -> list[dict[str, Any]]:
        return [post(item, **self.fields.get(item, {})) for item in held]

    def read(
        self, items: list[str], limit: int | None, cursor: str | None, max_pages: int | None
    ) -> tuple[list[str], str | None]:
        """Bird's paging loop: the IDs it collects and the cursor it reports."""
        held: list[str] = []
        next_cursor: str | None = None
        fetched = 0
        while limit is None or len(held) < limit:
            size = PAGE if limit is None else min(PAGE, limit - len(held))
            start = int(cursor) if cursor else 0
            page = items[start : start + size]
            page_cursor = str(start + len(page))
            self.pages += 1
            fetched += 1
            added = [item for item in page if item not in held]
            held.extend(added)
            if page_cursor == cursor or not page or not added:
                next_cursor = None
                break
            if max_pages and fetched >= max_pages:
                next_cursor = page_cursor
                break
            cursor = next_cursor = page_cursor
        return held, next_cursor
