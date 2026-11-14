"""The check that stops a release before it is published while immutability is off.

A local HTTP server stands in for GitHub's API, so the request, its headers and
the refusal of redirects are the real ones. Nothing here reaches GitHub.
"""

import contextlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import socket
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-release-immutability.py"
REPOSITORY = "example-owner/example-repo"
# Not in the form of a real token, which the repository's secret scan would refuse.
TOKEN = "example-settings-token"
ON = (200, {"enabled": True, "enforced_by_owner": False})
TURN_ON = (
    "fix: turn it on under Settings > Releases, or run "
    f"`gh api -X PUT repos/{REPOSITORY}/immutable-releases`, then dispatch the release again. "
    "Nothing was published."
)
OFF = f"error: release immutability is off for {REPOSITORY}, so this release would not be immutable"
TOKEN_FIX = (
    "fix: store a current fine-grained token that has the Administration permission (read) "
    "for this repository in the RELEASE_SETTINGS_TOKEN secret, or delete the secret to "
    "release without this check. Nothing was published."
)
RETRY_FIX = "fix: dispatch the release again. Nothing was published."
MAY_NOT = f"error: the token in RELEASE_SETTINGS_TOKEN may not read the settings of {REPOSITORY}"
ASKED = "when asked about release immutability"
NOT_REACHED = "error: could not ask GitHub about release immutability"


def load_module():
    spec = importlib.util.spec_from_file_location("check_release_immutability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    """Answers every request with one scripted response and records what was asked."""

    def __init__(self, test: unittest.TestCase) -> None:
        self.status = 200
        self.body = b""
        self.headers: dict[str, str] = {}
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fake.requests.append((self.command, self.path, dict(self.headers.items())))
                self.send_response(fake.status)
                for name, value in fake.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(fake.body)))
                self.end_headers()
                self.wfile.write(fake.body)

            def log_message(self, *_args) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        # The default poll makes every shutdown wait half a second.
        thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        test.addCleanup(thread.join)
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)

    def answer(self, status: int, body: object, **headers: str) -> None:
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = headers


class CheckReleaseImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        # No proxy and no token from the developer's own environment.
        self.enterContext(mock.patch.dict(os.environ, {"SETTINGS_TOKEN": TOKEN}, clear=True))
        self.github = FakeGitHub(self)

    def run_check(self, *argv: str) -> tuple[int, str, list[str]]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.module.main(list(argv) or [REPOSITORY, "--api-url", self.github.url])
        output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(TOKEN, output)
        return code, stdout.getvalue(), stderr.getvalue().splitlines()

    def test_a_repository_with_immutability_on_passes(self):
        self.github.answer(*ON)

        code, stdout, stderr = self.run_check()

        self.assertEqual((code, stderr), (0, []))
        self.assertEqual(stdout, f"release immutability is on for {REPOSITORY}\n")

    def test_the_request_is_one_authorized_get_for_the_setting(self):
        self.github.answer(*ON)

        self.run_check(REPOSITORY, "--api-url", self.github.url + "/")

        [(method, path, headers)] = self.github.requests
        self.assertEqual((method, path), ("GET", f"/repos/{REPOSITORY}/immutable-releases"))
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["User-Agent"], "release-immutability-check")

    def test_github_is_asked_at_its_own_address_by_default(self):
        self.assertEqual(self.module.API_URL, "https://api.github.com")
        with mock.patch.object(self.module, "ask", return_value=(200, b'{"enabled": true}')) as ask:
            code, _stdout, _stderr = self.run_check(REPOSITORY)

        self.assertEqual(code, 0)
        ask.assert_called_once_with(REPOSITORY, TOKEN, "https://api.github.com")

    def test_immutability_that_is_off_stops_the_release(self):
        not_found = {"message": "Not Found", "status": "404"}
        cannot_see = (
            f"{TURN_ON} If it is on already, the token in RELEASE_SETTINGS_TOKEN cannot see "
            "this repository: give it access."
        )
        for answer, fix in (((404, not_found), cannot_see), ((200, {"enabled": False}), TURN_ON)):
            with self.subTest(status=answer[0]):
                self.github.answer(*answer)

                code, stdout, stderr = self.run_check()

                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(stderr, [OFF, fix])

    def test_a_token_github_refuses_stops_the_release_and_says_which_secret(self):
        cases = (
            (
                (401, {"message": "Bad credentials"}),
                "error: GitHub does not accept the token in RELEASE_SETTINGS_TOKEN "
                "(HTTP 401: Bad credentials)",
            ),
            (
                (403, {"message": "Resource not accessible by personal access token"}),
                f"{MAY_NOT} (HTTP 403: Resource not accessible by personal access token)",
            ),
            ((403, b""), f"{MAY_NOT} (HTTP 403)"),
        )
        for answer, problem in cases:
            with self.subTest(problem=problem):
                self.github.answer(*answer)

                code, stdout, stderr = self.run_check()

                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(stderr, [problem, TOKEN_FIX])

    def test_an_answer_that_settles_nothing_stops_the_release(self):
        unclear = "error: GitHub's answer does not say whether release immutability is on"
        cases = (
            ((200, b"<html>maintenance</html>"), unclear),
            ((200, []), unclear),
            ((200, {"enabled": "yes"}), unclear),
            ((200, {}), unclear),
            ((200, b"[" * 100_000 + b"]" * 100_000), unclear),
            ((500, b"oops"), f"error: GitHub answered HTTP 500 {ASKED}"),
            (
                (429, {"message": "API rate limit exceeded"}),
                f"error: GitHub answered HTTP 429 {ASKED}: API rate limit exceeded",
            ),
            ((503, {"message": 5}), f"error: GitHub answered HTTP 503 {ASKED}"),
            ((204, b""), f"error: GitHub answered HTTP 204 {ASKED}"),
        )
        for answer, problem in cases:
            with self.subTest(problem=problem, status=answer[0]):
                self.github.answer(*answer)

                code, stdout, stderr = self.run_check()

                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(stderr, [problem, RETRY_FIX])

    def test_what_github_says_is_printed_as_one_plain_line(self):
        said = "Not allowed\n::error::injected\r\n\x1b[31m" + "x" * 300
        self.github.answer(403, {"message": said})

        code, _stdout, stderr = self.run_check()

        # Line breaks and control characters become spaces, and 200 characters are kept.
        shown = ("Not allowed ::error::injected [31m" + "x" * 300)[:200]
        self.assertEqual(code, 1)
        self.assertEqual(stderr, [f"{MAY_NOT} (HTTP 403: {shown})", TOKEN_FIX])

    def test_a_redirect_is_not_followed_so_the_token_stays_with_github(self):
        elsewhere = FakeGitHub(self)
        elsewhere.answer(*ON)
        target = f"{elsewhere.url}/repos/{REPOSITORY}/immutable-releases"
        for status in (301, 302, 307, 308):
            with self.subTest(status=status):
                self.github.answer(status, b"", Location=target)

                code, stdout, stderr = self.run_check()

                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(
                    stderr, [f"error: GitHub answered HTTP {status} {ASKED}", RETRY_FIX]
                )
        self.assertEqual(elsewhere.requests, [])

    def test_a_github_that_cannot_be_reached_stops_the_release(self):
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{unused.getsockname()[1]}"

        code, stdout, stderr = self.run_check(REPOSITORY, "--api-url", closed)

        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(len(stderr), 2)
        self.assertTrue(stderr[0].startswith(f"{NOT_REACHED}: "), stderr[0])
        self.assertEqual(stderr[1], RETRY_FIX)

    def test_an_answer_cut_short_stops_the_release(self):
        with mock.patch.object(
            self.module.urllib.request.OpenerDirector,
            "open",
            side_effect=self.module.http.client.IncompleteRead(b"{"),
        ):
            code, stdout, stderr = self.run_check()

        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(stderr, [f"{NOT_REACHED}: IncompleteRead(1 bytes read)", RETRY_FIX])

    def test_a_missing_or_malformed_token_is_a_usage_error_and_nothing_is_asked(self):
        cases = (
            ("", "error: SETTINGS_TOKEN is not set, so the setting cannot be read"),
            (" \n", "error: SETTINGS_TOKEN is not set, so the setting cannot be read"),
            ("two words", "error: SETTINGS_TOKEN does not hold a token"),
            ("line\nbreak", "error: SETTINGS_TOKEN does not hold a token"),
            ("café", "error: SETTINGS_TOKEN does not hold a token"),
        )
        for token, problem in cases:
            with self.subTest(token=token), mock.patch.dict(os.environ, {"SETTINGS_TOKEN": token}):
                code, stdout, stderr = self.run_check()

                self.assertEqual((code, stdout, stderr), (2, "", [problem]))
        with mock.patch.dict(os.environ, clear=True):
            code, _stdout, stderr = self.run_check()
        self.assertEqual((code, stderr), (2, [cases[0][1]]))
        self.assertEqual(self.github.requests, [])

    def test_a_token_with_a_newline_around_it_is_used_without_it(self):
        self.github.answer(*ON)
        with mock.patch.dict(os.environ, {"SETTINGS_TOKEN": f"{TOKEN}\n"}):
            code, _stdout, _stderr = self.run_check()

        self.assertEqual(code, 0)
        self.assertEqual(self.github.requests[0][2]["Authorization"], f"Bearer {TOKEN}")

    def test_a_repository_that_is_not_owner_and_name_is_a_usage_error(self):
        for repository in (
            "example-repo",
            "owner/repo/extra",
            "owner/../repo",
            "owner/..",
            "owner/.",
            "owner/repo?x=1",
            "owner/repo#fragment",
            "owner-/-repo/",
            "owner /repo",
            "",
        ):
            with self.subTest(repository=repository):
                code, stdout, stderr = self.run_check(repository, "--api-url", self.github.url)

                self.assertEqual(
                    (code, stdout, stderr),
                    (2, "", ["error: the repository must be given as OWNER/NAME"]),
                )
        self.assertEqual(self.github.requests, [])


if __name__ == "__main__":
    unittest.main()
