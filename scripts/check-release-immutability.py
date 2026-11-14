#!/usr/bin/env python3
"""Ask GitHub whether a repository makes its new releases immutable.

A release published while the setting is off is not immutable, and its tag
name is used up all the same. The Release Plugin workflow therefore asks
before it publishes anything.

GitHub answers only a token that holds the repository's Administration
permission (read). The token a workflow run receives cannot hold it, so the
workflow passes a fine-grained personal access token from its
RELEASE_SETTINGS_TOKEN secret, in the SETTINGS_TOKEN environment variable.
docs/releasing.md says how to create one.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request


API_URL = "https://api.github.com"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}$")
# A token is printable ASCII in one piece. Anything else would break the request header.
TOKEN_RE = re.compile(r"^[!-~]+$")
TIMEOUT_SECONDS = 30
# GitHub's answers here are a few hundred bytes; nothing longer is read.
MAX_ANSWER = 65536

NOTHING_PUBLISHED = "Nothing was published"
TOKEN_FIX = (
    "fix: store a current fine-grained token that has the Administration permission (read) "
    "for this repository in the RELEASE_SETTINGS_TOKEN secret, or delete the secret to "
    f"release without this check. {NOTHING_PUBLISHED}."
)
RETRY_FIX = f"fix: dispatch the release again. {NOTHING_PUBLISHED}."


class Refused(Exception):
    """The release must not go ahead: the problem, and what to do about it."""

    def __init__(self, problem: str, fix: str) -> None:
        super().__init__(problem)
        self.fix = fix


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect: urllib would send the token on to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def said(answer: bytes) -> str:
    """Return the message in GitHub's error answer as one printable line, or nothing."""
    try:
        message = json.loads(answer).get("message")
    except (ValueError, AttributeError, RecursionError):
        return ""
    if not isinstance(message, str):
        return ""
    printable = "".join(char if char.isprintable() else " " for char in message)
    line = " ".join(printable.split())[:200]
    return f": {line}" if line else ""


def ask(repository: str, token: str, api_url: str) -> tuple[int, bytes]:
    """Return the status and body of GitHub's answer about the setting."""
    request = urllib.request.Request(
        f"{api_url}/repos/{repository}/immutable-releases",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "release-immutability-check",
        },
    )
    opener = urllib.request.build_opener(NoRedirects)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(MAX_ANSWER)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(MAX_ANSWER)
        finally:
            exc.close()
    except (OSError, http.client.HTTPException) as exc:
        # URLError and a timeout are both OSErrors.
        reason = getattr(exc, "reason", None) or exc
        raise Refused(
            f"could not ask GitHub about release immutability: {reason}", RETRY_FIX
        ) from exc


def require_immutable_releases(repository: str, token: str, api_url: str = API_URL) -> None:
    """Return when new releases in the repository are immutable; raise Refused otherwise."""
    status, answer = ask(repository, token, api_url)
    turn_on = (
        "fix: turn it on under Settings > Releases, or run "
        f"`gh api -X PUT repos/{repository}/immutable-releases`, then dispatch the release "
        f"again. {NOTHING_PUBLISHED}."
    )
    off = f"release immutability is off for {repository}, so this release would not be immutable"
    if status == 200:
        try:
            enabled = json.loads(answer).get("enabled")
        except (ValueError, AttributeError, RecursionError):
            enabled = None
        if enabled is True:
            return
        if enabled is False:
            raise Refused(off, turn_on)
        raise Refused("GitHub's answer does not say whether release immutability is on", RETRY_FIX)
    if status == 404:
        # GitHub hides what a token may not see behind the same answer.
        raise Refused(
            off,
            f"{turn_on} If it is on already, the token in RELEASE_SETTINGS_TOKEN cannot see "
            "this repository: give it access.",
        )
    if status == 401:
        raise Refused(
            f"GitHub does not accept the token in RELEASE_SETTINGS_TOKEN (HTTP 401{said(answer)})",
            TOKEN_FIX,
        )
    if status == 403:
        raise Refused(
            f"the token in RELEASE_SETTINGS_TOKEN may not read the settings of {repository} "
            f"(HTTP 403{said(answer)})",
            TOKEN_FIX,
        )
    raise Refused(
        f"GitHub answered HTTP {status} when asked about release immutability{said(answer)}",
        RETRY_FIX,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that GitHub makes new releases in a repository immutable.",
        epilog="The token is read from the SETTINGS_TOKEN environment variable.",
    )
    parser.add_argument("repository", help="The repository to ask about, as OWNER/NAME.")
    parser.add_argument("--api-url", default=API_URL, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if REPOSITORY_RE.fullmatch(args.repository) is None:
        print("error: the repository must be given as OWNER/NAME", file=sys.stderr)
        return 2
    token = os.environ.get("SETTINGS_TOKEN", "").strip()
    if not token:
        print("error: SETTINGS_TOKEN is not set, so the setting cannot be read", file=sys.stderr)
        return 2
    if TOKEN_RE.fullmatch(token) is None:
        print("error: SETTINGS_TOKEN does not hold a token", file=sys.stderr)
        return 2

    try:
        require_immutable_releases(args.repository, token, args.api_url.rstrip("/"))
    except Refused as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(exc.fix, file=sys.stderr)
        return 1
    print(f"release immutability is on for {args.repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
