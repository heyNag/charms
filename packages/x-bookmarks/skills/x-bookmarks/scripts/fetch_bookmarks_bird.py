#!/usr/bin/env python3
"""Fetch X bookmarks through Bird and review what is new since last time.

Bird reads X with the session of a browser the user is signed in to, so it
spends no X API credits. This helper runs `bird bookmarks --json`, checks what
Bird printed, and applies the same saved review cutoff as the X API helper, so
a review can move from one backend to the other.

The output shapes and paging rules below are those of Bird 0.8.0; see
references/bird-fast.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import itertools
import json
import re
import shutil
import subprocess
import sys
from typing import Any

# Stops here with one clear line when this Python is older than the floor.
import python_floor  # noqa: F401
import plugin_version
import review_state
from review_state import (
    FOLDER_ID,
    STATE_FIX,
    StateError,
    Stop,
    early_stop,
    load_state,
    review,
    state_scope,
    stop_problem,
    utc_now,
)

# Seconds one Bird run may take. Bird limits each request, not the whole read.
DEFAULT_TIMEOUT = 600.0
MAX_TIMEOUT = 86400.0
# Pages per Bird run while a review may stop early; the last size repeats.
# Bird fetches 20 bookmarks to a page, so the first run covers the newest 100.
STEP_PAGES = (5, 10, 20, 40)
# An X handle and a post ID, checked before either goes into a URL.
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
POST_ID = re.compile(r"[0-9]{1,19}")
# A creation time as X writes it and Bird passes it on: "Wed Oct 10 20:19:24 +0000 2018".
X_TIME = re.compile(
    r"[A-Za-z]{3} ([A-Za-z]{3}) ([0-9]{1,2}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) ([+-])([0-9]{2})([0-9]{2}) ([0-9]{4})"
)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FORMAT_FIX = (
    "fix: this helper reads what Bird 0.8.0 prints for `bird bookmarks --json`; compare `bird --version`, "
    "and see the raw output with scripts/fetch_bookmarks_bird.sh"
)


class BirdError(RuntimeError):
    """Bird failed, or printed something this helper cannot read."""

    def __init__(self, message: str, *fixes: str) -> None:
        super().__init__(message)
        self.fixes = fixes


def find_bird() -> str | None:
    """The Bird program on PATH, or None when it is not installed."""
    return shutil.which("bird")


def relay(text: bytes | str | None) -> None:
    """Pass on what Bird wrote to standard error, which is where its warnings go."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if text:
        sys.stderr.write(text if text.endswith("\n") else text + "\n")


def run_bird(command: list[str], timeout: float) -> tuple[int, bytes, str]:
    """Run one Bird command; return its exit status, standard output and standard error.

    Bird gets no standard input, so it cannot wait for an answer nobody types.
    """
    try:
        done = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        relay(exc.stderr)
        raise BirdError(
            f"bird did not finish within {timeout:g} seconds",
            "fix: raise --bird-timeout, or read fewer bookmarks with --count or --max-pages",
        ) from exc
    except OSError as exc:
        raise BirdError(f"cannot run {command[0]}: {exc.strerror or exc}") from exc
    return done.returncode, done.stdout, done.stderr.decode("utf-8", errors="replace")


def failure_fixes(errors: str) -> tuple[str, ...]:
    """Pick the fix for a failed Bird run from what Bird said about it."""
    said = errors.lower()
    if "unknown option" in said:
        return (
            "fix: this helper needs Bird 0.6.0 or newer, which pages bookmarks with --all, "
            "--max-pages and --cursor; compare `bird --version`",
        )
    if "http 429" in said:
        return (
            "fix: X is limiting requests from this session; wait, then retry, and read fewer "
            "pages with --count, --max-pages or --stop-after-known",
        )
    return (
        "fix: check the browser session with `bird check --plain`; if it is signed out, "
        "sign in to x.com (scripts/open_x_login.sh opens it) and retry",
    )


def bird_json(command: list[str], timeout: float) -> bytes:
    """Run Bird and return what it printed, or raise BirdError when it failed."""
    status, output, errors = run_bird(command, timeout)
    relay(errors)
    if status != 0:
        raise BirdError(f"bird exited with status {status}", *failure_fixes(errors))
    return output


def bird_command(
    bird: str, args: argparse.Namespace, pages: int | None = None, cursor: str | None = None
) -> list[str]:
    """Build one `bird bookmarks` command line.

    An option's value is written as --name=value, so a value that starts with
    a dash cannot be read as another option. The thread and sorting options of
    `bird bookmarks` are never passed: they add posts that are not bookmarks
    or reorder the list, and the review cutoff relies on X's own order.
    """
    command = [bird, "bookmarks", "--json", "--plain"]
    command += [f"--cookie-source={source}" for source in args.cookie_source or []]
    for name in ("chrome_profile", "chrome_profile_dir", "firefox_profile"):
        value = getattr(args, name)
        if value:
            command.append(f"--{name.replace('_', '-')}={value}")
    if args.folder_id:
        command.append(f"--folder-id={args.folder_id}")
    if not args.all:
        return [*command, f"--count={args.count}"]
    command.append("--all")
    if pages is not None:
        command.append(f"--max-pages={pages}")
    if cursor:
        command.append(f"--cursor={cursor}")
    return command


def shape(value: Any) -> str:
    """Name the kind of a JSON value for an error message, without quoting its content."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return "text"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true or false"
    return "a number"


def read_posts(raw: bytes, paged: bool) -> tuple[list[dict[str, Any]], str | None]:
    """Return the posts Bird printed, and the cursor of the next page when Bird names one.

    Bird prints a list for a window (--count). When it pages (--all or
    --cursor) it prints an object with "tweets" and "nextCursor": null once
    Bird has read to the end of the list, a cursor when --max-pages stopped it
    first. Anything else is refused, because a guess about where the list
    ends could mark bookmarks nobody saw as reviewed.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        raise BirdError(f"bird did not print valid JSON: {exc}", FORMAT_FIX) from exc
    cursor = None
    if paged:
        paging = isinstance(payload, dict) and isinstance(payload.get("tweets"), list) and "nextCursor" in payload
        if not paging:
            raise BirdError(
                f'bird printed {shape(payload)}, not the object with a "tweets" list and a "nextCursor" '
                "that --all gives",
                FORMAT_FIX,
            )
        posts, cursor = payload["tweets"], payload["nextCursor"]
        if cursor is not None and not isinstance(cursor, str):
            raise BirdError(f'the "nextCursor" bird printed is {shape(cursor)}, not text or null', FORMAT_FIX)
    elif isinstance(payload, list):
        posts = payload
    else:
        raise BirdError(f"bird printed {shape(payload)}, not the list of posts that --count gives", FORMAT_FIX)
    for position, post in enumerate(posts, 1):
        if not isinstance(post, dict):
            raise BirdError(f"post {position} of bird's output is {shape(post)}, not an object", FORMAT_FIX)
        if not isinstance(post.get("id"), str) or not post["id"]:
            raise BirdError(f'post {position} of bird\'s output has no "id" text', FORMAT_FIX)
    return posts, cursor or None


def unique(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a post that appears twice, keeping its first and newer place."""
    seen: set[str] = set()
    kept = []
    for post in posts:
        if post["id"] not in seen:
            seen.add(post["id"])
            kept.append(post)
    return kept


def fetch(bird: str, args: argparse.Namespace, stop: Stop) -> tuple[list[dict[str, Any]], bool, bool]:
    """Return the bookmarks, whether Bird read to the end of the list, and whether stop ended the read.

    A window is one Bird run, and so is the whole list. Bird cannot be told to
    stop at a reviewed bookmark, though, so a review that may stop early runs
    Bird in steps of STEP_PAGES pages. Each step resumes at the cursor the one
    before returned, until stop is satisfied or the list ends.
    """
    timeout = args.bird_timeout
    if not args.all:
        posts, _cursor = read_posts(bird_json(bird_command(bird, args), timeout), paged=False)
        # Bird keeps asking X for more until it holds --count posts, so fewer means the list ended.
        return unique(posts), len(posts) < args.count, False
    if stop is None:
        posts, cursor = read_posts(bird_json(bird_command(bird, args, pages=args.max_pages), timeout), paged=True)
        return unique(posts), cursor is None, False

    posts = []
    cursor = None
    left = args.max_pages
    steps = itertools.chain(STEP_PAGES, itertools.repeat(STEP_PAGES[-1]))
    while True:
        pages = next(steps) if left is None else min(next(steps), left)
        command = bird_command(bird, args, pages=pages, cursor=cursor)
        more, cursor = read_posts(bird_json(command, timeout), paged=True)
        held = len(posts)
        posts = unique(posts + more)
        if cursor is None:
            return posts, True, False
        if stop([post["id"] for post in posts]):
            return posts, False, True
        if len(posts) == held:
            raise BirdError("bird returned no further bookmarks, yet named a cursor for more", FORMAT_FIX)
        if left is not None:
            left -= pages
            if left <= 0:
                return posts, False, False


def api_time(value: Any) -> str | None:
    """Return Bird's creation time in the X API's form, or None when it is not a time X writes.

    The API writes "Wed Oct 10 20:19:24 +0000 2018" as
    "2018-10-10T20:19:24.000Z". The review cutoff compares creation times as
    text, so both backends have to write them alike.
    """
    match = X_TIME.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        return None
    month, day, hour, minute, second, sign, offset_hours, offset_minutes, year = match.groups()
    if month.title() not in MONTHS:
        return None
    offset = timedelta(hours=int(offset_hours), minutes=int(offset_minutes))
    try:
        moment = datetime(
            int(year),
            MONTHS.index(month.title()) + 1,
            int(day),
            int(hour),
            int(minute),
            int(second),
            tzinfo=timezone(-offset if sign == "-" else offset),
        ).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        # A day, hour or year no calendar has.
        return None
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}.000Z"
    )


def post_url(post: dict[str, Any]) -> str | None:
    """Return the post's address on x.com, or None when its ID is not a number."""
    post_id = post.get("id")
    if not isinstance(post_id, str) or not POST_ID.fullmatch(post_id):
        return None
    author = post.get("author")
    username = author.get("username") if isinstance(author, dict) else None
    if isinstance(username, str) and HANDLE.fullmatch(username):
        return f"https://x.com/{username}/status/{post_id}"
    return f"https://x.com/i/web/status/{post_id}"


def add_fields(post: dict[str, Any], folder_id: str | None) -> None:
    """Add what the X API helper's posts also carry: url, created_at, source and folder_id.

    Bird's own fields stay as they are. A quoted post gets its url and
    created_at too.
    """
    node: Any = post
    while isinstance(node, dict):
        url = post_url(node)
        if url:
            node["url"] = url
        created = api_time(node.get("createdAt"))
        if created:
            node["created_at"] = created
        node = node.get("quotedTweet")
    post["source"] = "bird"
    if folder_id:
        post["folder_id"] = folder_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch X bookmarks through Bird and review what is new since last time."
    )
    parser.add_argument("--version", action="version", version=plugin_version.VERSION_LINE)
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of bookmarks to fetch.")
    parser.add_argument("--all", action="store_true", help="Fetch every bookmark.")
    parser.add_argument("--max-pages", type=int, help="With --all, stop after this many pages of 20 bookmarks.")
    parser.add_argument("--folder-id", help="Fetch bookmarks from the bookmark folder with this numeric ID.")
    review_state.add_options(parser)
    parser.add_argument(
        "--cookie-source",
        action="append",
        metavar="BROWSER",
        help="Browser whose x.com session Bird reads: safari, chrome or firefox. Repeat to try several in order.",
    )
    parser.add_argument("--chrome-profile", metavar="NAME", help="Chrome profile Bird reads the session from.")
    parser.add_argument(
        "--chrome-profile-dir",
        metavar="PATH",
        help="Chrome or Chromium profile folder Bird reads the session from.",
    )
    parser.add_argument("--firefox-profile", metavar="NAME", help="Firefox profile Bird reads the session from.")
    parser.add_argument(
        "--bird-timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="Seconds one Bird run may take (default: %(default)g).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    # Bird takes the session cookies as options. They are parsed here only so
    # that argparse cannot repeat a cookie in an "unrecognized arguments" error.
    parser.add_argument("--auth-token", help=argparse.SUPPRESS)
    parser.add_argument("--ct0", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def usage_problem(args: argparse.Namespace) -> list[str]:
    """Return the lines that say why these options cannot be used, or [] when they can."""
    if args.auth_token is not None or args.ct0 is not None:
        return [
            "error: --auth-token and --ct0 are not accepted, because a cookie in a command line "
            "is visible in the process list and saved in shell history",
            "fix: let Bird read the browser session (check it with `bird check --plain`), and sign out "
            "of x.com in that browser to end the session if this command line may have been recorded",
        ]
    if args.count < 1:
        return ["error: --count must be at least 1"]
    if args.max_pages is not None and not args.all:
        return ["error: --max-pages works only with --all"]
    if args.max_pages is not None and args.max_pages < 1:
        return ["error: --max-pages must be at least 1"]
    if args.folder_id is not None and not FOLDER_ID.fullmatch(args.folder_id):
        return [
            "error: --folder-id must be a folder's numeric ID of 1 to 19 digits",
            "fix: pass the number at the end of the folder's address on x.com, "
            "https://x.com/i/bookmarks/NUMBER",
        ]
    # Written so that "nan" fails too.
    if not 0 < args.bird_timeout <= MAX_TIMEOUT:
        return [f"error: --bird-timeout must be more than 0 and at most {MAX_TIMEOUT:g} seconds"]
    problem = stop_problem(args.stop_after_known, whole_list=args.all, since_last=args.since_last)
    return [f"error: {problem}"] if problem else []


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    problem = usage_problem(args)
    if problem:
        for line in problem:
            print(line, file=sys.stderr)
        return 2

    state_file = args.state_file.expanduser()
    state: dict[str, Any] = {}
    if args.since_last or args.update_state:
        # Before Bird runs: a damaged file must not cost a read of the whole list.
        try:
            state = load_state(state_file)
        except StateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            print(STATE_FIX, file=sys.stderr)
            return 1

    bird = find_bird()
    if bird is None:
        print("error: bird is not installed", file=sys.stderr)
        print("fix: install Bird from https://bird.fast/ or use your managed toolchain", file=sys.stderr)
        return 127

    scope = state_scope(args.folder_id)
    try:
        posts, reached_end, stopped_early = fetch(bird, args, early_stop(state, scope, args.stop_after_known))
    except BirdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for line in exc.fixes:
            print(line, file=sys.stderr)
        return 1
    for post in posts:
        add_fields(post, args.folder_id)

    reviewed = review(
        posts,
        state,
        scope,
        state_file,
        reached_end=reached_end,
        apply_cutoff=args.since_last,
        save_cutoff=args.update_state,
        stopped_early=stopped_early,
    )
    for line in reviewed.messages:
        print(line, file=sys.stderr)
    output = {
        "data": reviewed.items,
        "meta": {
            "kind": "bookmarks",
            "count": len(reviewed.items),
            "fetched_count": len(posts),
            **reviewed.meta,
            "fetched_at": utc_now(),
        },
    }
    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
    # A state file that could not be saved is an error, reported above; the
    # bookmarks were still printed because Bird had already read them.
    return 1 if reviewed.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
