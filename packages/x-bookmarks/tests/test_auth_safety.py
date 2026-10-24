"""OAuth setup and credential-handling regressions for the X API helpers.

Network access stays on loopback servers started by the tests, and every
config, token, and state path points at a temporary directory.
"""

from __future__ import annotations

import contextlib
import http.client
import http.server
import io
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from test_basic import SCRIPTS, load_module  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(port: int, path: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


class LoopbackServer:
    """Serve one handler class on 127.0.0.1 in a background thread."""

    def __init__(self, handler: type[http.server.BaseHTTPRequestHandler]) -> None:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.server.seen = []  # type: ignore[attr-defined]
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "LoopbackServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def seen(self) -> list[dict[str, str | None]]:
        return self.server.seen  # type: ignore[attr-defined]


class RecordingTarget(http.server.BaseHTTPRequestHandler):
    def record(self) -> None:
        self.server.seen.append(  # type: ignore[attr-defined]
            {"path": self.path, "authorization": self.headers.get("Authorization")}
        )
        body = b'{"access_token": "leaked"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = record  # noqa: N815 - stdlib hook name
    do_POST = record  # noqa: N815 - stdlib hook name

    def log_message(self, _format: str, *_args: object) -> None:
        return


def redirect_handler(location: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Redirect(http.server.BaseHTTPRequestHandler):
        def redirect(self) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = redirect  # noqa: N815 - stdlib hook name
        do_POST = redirect  # noqa: N815 - stdlib hook name

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Redirect


def cut_short_handler(
    status: int, body: bytes, length: int | None
) -> type[http.server.BaseHTTPRequestHandler]:
    """Send body, announcing length bytes (None: none), then close; status 0 sends nothing."""

    class CutShort(http.server.BaseHTTPRequestHandler):
        def reply(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if not status:
                return
            self.send_response(status)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()
            self.wfile.write(body)

        do_GET = reply  # noqa: N815 - stdlib hook name
        do_POST = reply  # noqa: N815 - stdlib hook name

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return CutShort


def error_handler(
    status: int, body: bytes, headers: dict[str, str]
) -> type[http.server.BaseHTTPRequestHandler]:
    class ErrorReply(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ErrorReply


# An ISO-8859-1 error page, as a proxy or CDN might send instead of X's JSON.
LATIN1_PAGE = b"<html>Service indisponible, r\xe9essayez</html>"
LATIN1_HEADERS = {"Content-Type": "text/html; charset=iso-8859-1"}


CUT_SHORT_RESPONSES = {
    "truncated body": (200, b'{"access_token": "partial-secret', 100),
    "dropped connection": (0, b"", None),
    "truncated error body": (429, b'{"title":', 100),
    "body ended by connection close": (200, b'{"data": {"id": ', None),
}


class HermeticCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(
            os.environ,
            {
                "X_BOOKMARKS_CONFIG_DIR": str(self.tmp / "config"),
                "X_BOOKMARKS_TOKEN_FILE": str(self.tmp / "config" / "tokens.json"),
                "X_BOOKMARKS_STATE_FILE": str(self.tmp / "state" / "state.json"),
                # Loopback requests must never be routed through a user proxy.
                "no_proxy": "*",
                "NO_PROXY": "*",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        for name in ("X_API_ACCESS_TOKEN", "X_API_BEARER_TOKEN", "X_API_CLIENT_SECRET"):
            os.environ.pop(name, None)
        self.auth = load_module("x_api_auth_safety", SCRIPTS / "x_api_auth.py")
        self.assertTrue(str(self.auth.CONFIG_FILE).startswith(str(self.tmp)))


class ScopeSetupTest(HermeticCase):
    def run_setup(self, *argv: str, flow_error: Exception | None = None) -> tuple[int, list, str]:
        requested: list[list[str]] = []

        def fake_flow(**kwargs):
            requested.append(list(kwargs["scopes"]))
            if flow_error:
                raise flow_error
            return {"access_token": "test-access", "scope_list": kwargs["scopes"]}

        stderr = io.StringIO()
        with (
            mock.patch.object(self.auth, "run_auth_flow", side_effect=fake_flow),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            code = self.auth.main(["--client-id", "test-client", "--no-browser", *argv])
        return code, requested, stderr.getvalue()

    def saved_scopes(self) -> list[str]:
        return json.loads(self.auth.CONFIG_FILE.read_text())["scopes"]

    def test_later_setup_does_not_inherit_saved_write_scope(self) -> None:
        code, requested, _stderr = self.run_setup("--include-write-scope")
        self.assertEqual(code, 0)
        self.assertIn("bookmark.write", requested[0])

        code, requested, _stderr = self.run_setup()

        self.assertEqual(code, 0)
        self.assertEqual(requested, [self.auth.DEFAULT_SCOPES])
        self.assertEqual(self.saved_scopes(), self.auth.DEFAULT_SCOPES)

    def test_unknown_scope_is_rejected_before_authorization(self) -> None:
        code, requested, stderr = self.run_setup("--scope", "bookmark.wirte")

        self.assertEqual(code, 1)
        self.assertEqual(requested, [])
        self.assertIn("error: unknown OAuth scope 'bookmark.wirte'", stderr)
        self.assertFalse(self.auth.CONFIG_FILE.exists())

    def test_failed_setup_leaves_saved_config_unchanged(self) -> None:
        self.run_setup()

        code, _requested, _stderr = self.run_setup(
            "--scope", "tweet.write", flow_error=self.auth.AuthError("access_denied")
        )

        self.assertEqual(code, 1)
        self.assertEqual(self.saved_scopes(), self.auth.DEFAULT_SCOPES)

    def test_status_warns_about_scopes_beyond_read_only(self) -> None:
        self.run_setup("--include-write-scope")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.auth.status()

        self.assertIn("warning: scopes beyond the read-only defaults: bookmark.write", stdout.getvalue())


class CallbackServerTest(HermeticCase):
    def start_flow(
        self, token_error: Exception | None = None, **flow_kwargs: float
    ) -> tuple[int, queue.Queue, dict]:
        port = free_port()
        opened: queue.Queue = queue.Queue()
        outcome: dict = {}

        def run() -> None:
            try:
                with (
                    mock.patch.object(self.auth.webbrowser, "open", side_effect=opened.put),
                    mock.patch.object(
                        self.auth, "token_request", return_value={"access_token": "a"}, side_effect=token_error
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    outcome["tokens"] = self.auth.run_auth_flow(
                        "test-client",
                        None,
                        f"http://127.0.0.1:{port}/callback",
                        list(self.auth.DEFAULT_SCOPES),
                        True,
                        **flow_kwargs,
                    )
            except Exception as exc:  # noqa: BLE001 - reported to the test thread
                outcome["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        outcome["thread"] = thread
        return port, opened, outcome

    def test_stray_requests_do_not_end_the_flow(self) -> None:
        port, opened, outcome = self.start_flow()
        auth_url = opened.get(timeout=5)
        state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)["state"][0]

        self.assertEqual(get(port, "/favicon.ico"), 404)
        self.assertEqual(get(port, "/callback?state=stale-tab&code=old"), 400)
        self.assertEqual(get(port, f"/callback?state={state}&code=good-code"), 200)
        outcome["thread"].join(10)

        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["tokens"]["access_token"], "a")

    def test_flow_gives_up_after_timeout(self) -> None:
        started = time.monotonic()
        _port, _opened, outcome = self.start_flow(timeout=0.3)
        outcome["thread"].join(10)

        self.assertLess(time.monotonic() - started, 5)
        self.assertIsInstance(outcome.get("error"), self.auth.AuthError)
        self.assertIn("no OAuth callback", str(outcome["error"]))

    def test_slow_client_does_not_hold_flow_past_deadline(self) -> None:
        port, opened, outcome = self.start_flow(timeout=1.0)
        opened.get(timeout=5)
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            # A header line sent a byte at a time never times out a single recv.
            client.sendall(b"GET /favicon.ico HTTP/1.1\r\nHost: x\r\nX-Pad: ")
            while outcome["thread"].is_alive() and time.monotonic() - started < 8:
                client.sendall(b"a")
                time.sleep(0.2)
            elapsed = time.monotonic() - started
            client.sendall(b"\r\n\r\n")
            client.recv(1024)
        outcome["thread"].join(10)

        self.assertLess(elapsed, 5)
        self.assertIsInstance(outcome.get("error"), self.auth.AuthError)
        self.assertIn("no OAuth callback", str(outcome["error"]))

    def test_flow_ends_only_after_the_callback_page_is_written(self) -> None:
        # setup exits as soon as the flow ends, killing the daemon handler
        # thread, so a page still being written would reach the browser cut off.
        original = self.auth.OAuthCallback.respond
        for suffix, status, expected in (
            ("&code=good-code", 200, "token request failed: offline"),
            ("&error=access_denied", 400, "access_denied"),
            ("", 400, "missing authorization code"),
        ):
            with self.subTest(callback=suffix or "no code"):
                port, opened, outcome = self.start_flow(
                    token_error=self.auth.AuthError("token request failed: offline"), timeout=10.0
                )
                auth_url = opened.get(timeout=5)
                state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)["state"][0]
                ended_before_page: list[bool] = []

                def held_respond(handler: object, *args: object) -> None:
                    # Hold the page back longer than the flow takes to notice a result.
                    outcome["thread"].join(1.5)
                    ended_before_page.append(not outcome["thread"].is_alive())
                    original(handler, *args)

                with mock.patch.object(self.auth.OAuthCallback, "respond", held_respond):
                    self.assertEqual(get(port, f"/callback?state={state}{suffix}"), status)
                    outcome["thread"].join(10)

                self.assertEqual(ended_before_page, [False])
                self.assertIsInstance(outcome.get("error"), self.auth.AuthError)
                self.assertEqual(str(outcome["error"]), expected)

    def test_browser_hanging_up_does_not_lose_the_code(self) -> None:
        port, opened, outcome = self.start_flow(timeout=3.0)
        auth_url = opened.get(timeout=5)
        state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)["state"][0]

        with (
            mock.patch.object(self.auth.OAuthCallback, "respond", side_effect=BrokenPipeError),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            socket.create_connection(("127.0.0.1", port), timeout=5) as client,
        ):
            client.sendall(f"GET /callback?state={state}&code=good-code HTTP/1.1\r\n\r\n".encode())
            client.recv(1024)
            outcome["thread"].join(10)

        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["tokens"]["access_token"], "a")
        self.assertEqual(stderr.getvalue(), "")

    def test_busy_callback_port_is_an_auth_error_with_fix(self) -> None:
        stdout = io.StringIO()
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            redirect_uri = f"http://127.0.0.1:{busy.getsockname()[1]}/callback"
            with (
                mock.patch.object(self.auth.webbrowser, "open") as browser,
                contextlib.redirect_stdout(stdout),
                self.assertRaises(self.auth.AuthError) as raised,
            ):
                self.auth.run_auth_flow(
                    "test-client", None, redirect_uri, list(self.auth.DEFAULT_SCOPES), True, timeout=1.0
                )

        self.assertIn(f"cannot listen on {redirect_uri}", str(raised.exception))
        self.assertIn("pass --redirect-uri with a free loopback port", str(raised.exception))
        # A flow that cannot receive its callback never shows the URL.
        self.assertEqual(stdout.getvalue(), "")
        browser.assert_not_called()


class SetupOutputTest(HermeticCase):
    def test_authorization_url_reaches_piped_stdout_before_the_wait(self) -> None:
        redirect_uri = f"http://127.0.0.1:{free_port()}/callback"
        # Keep stdout block-buffered, as it is when an agent pipes it.
        env = {name: value for name, value in os.environ.items() if name != "PYTHONUNBUFFERED"}
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "x_api_auth.py"),
                "--client-id",
                "test-client",
                "--no-browser",
                "--redirect-uri",
                redirect_uri,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**env, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        lines: queue.Queue = queue.Queue()
        reader = threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True)
        reader.start()
        # Cleanups run last first: kill, reap, drain, then close the pipe.
        self.addCleanup(process.stdout.close)
        self.addCleanup(reader.join, 10)
        self.addCleanup(process.wait, 10)
        self.addCleanup(process.kill)

        try:
            lines.get(timeout=10)
            auth_url = lines.get(timeout=10).decode("utf-8").strip()
        except queue.Empty:
            self.fail("setup did not write the authorization URL while waiting for the callback")

        self.assertTrue(auth_url.startswith(self.auth.AUTHORIZE_URL + "?"))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
        self.assertEqual(query["redirect_uri"], [redirect_uri])
        self.assertIsNone(process.poll())


class RedirectTest(HermeticCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = load_module("fetch_bookmarks_api_safety", SCRIPTS / "fetch_bookmarks_api.py")

    def test_api_get_does_not_follow_redirect_with_bearer_token(self) -> None:
        with LoopbackServer(RecordingTarget) as target:
            location = f"http://localhost:{target.port}/steal"
            with LoopbackServer(redirect_handler(location)) as api_host:
                with mock.patch.object(self.api, "BASE_URL", f"http://127.0.0.1:{api_host.port}/2"):
                    with self.assertRaisesRegex(self.api.ApiError, "refused HTTP 302 redirect"):
                        self.api.api_get("/users/me", "test-bearer-token")

        self.assertEqual(target.seen, [])

    def test_token_request_does_not_follow_redirect_with_client_secret(self) -> None:
        with LoopbackServer(RecordingTarget) as target:
            location = f"http://localhost:{target.port}/steal"
            with LoopbackServer(redirect_handler(location)) as token_host:
                token_url = f"http://127.0.0.1:{token_host.port}/2/oauth2/token"
                with mock.patch.object(self.auth, "TOKEN_URL", token_url):
                    with self.assertRaisesRegex(self.auth.AuthError, "refused HTTP 302 redirect"):
                        self.auth.token_request(
                            {"grant_type": "refresh_token", "refresh_token": "test-refresh"},
                            "test-client",
                            "test-secret",
                        )

        self.assertEqual(target.seen, [])


class CutShortResponseTest(HermeticCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = load_module("fetch_bookmarks_api_cut_short", SCRIPTS / "fetch_bookmarks_api.py")

    def test_api_get_reports_cut_short_responses_as_api_errors(self) -> None:
        for label, (status, body, length) in CUT_SHORT_RESPONSES.items():
            with self.subTest(label), LoopbackServer(cut_short_handler(status, body, length)) as host:
                with mock.patch.object(self.api, "BASE_URL", f"http://127.0.0.1:{host.port}/2"):
                    with self.assertRaises(self.api.ApiError) as raised:
                        self.api.api_get("/users/me", "test-bearer-token")
                # A cut-short error body keeps its status for rate-limit handling.
                self.assertEqual(raised.exception.status, 429 if status == 429 else 0)

    def test_token_request_reports_cut_short_responses_as_auth_errors(self) -> None:
        for label, (status, body, length) in CUT_SHORT_RESPONSES.items():
            with self.subTest(label), LoopbackServer(cut_short_handler(status, body, length)) as host:
                token_url = f"http://127.0.0.1:{host.port}/2/oauth2/token"
                with mock.patch.object(self.auth, "TOKEN_URL", token_url):
                    with self.assertRaises(self.auth.AuthError) as raised:
                        self.auth.token_request(
                            {"grant_type": "refresh_token", "refresh_token": "test-refresh"},
                            "test-client",
                        )
                self.assertNotIn("partial-secret", str(raised.exception))

    def test_fetch_cli_prints_error_when_connection_drops(self) -> None:
        stderr = io.StringIO()
        with LoopbackServer(cut_short_handler(0, b"", None)) as host:
            with (
                mock.patch.object(self.api, "BASE_URL", f"http://127.0.0.1:{host.port}/2"),
                mock.patch.object(self.api, "get_valid_token", return_value="test-bearer-token"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                code = self.api.main(["--state-file", str(self.tmp / "state" / "state.json")])

        self.assertEqual(code, 1)
        self.assertIn("error: request failed:", stderr.getvalue())


class ErrorResponseTest(HermeticCase):
    def setUp(self) -> None:
        super().setUp()
        self.api = load_module("fetch_bookmarks_api_errors", SCRIPTS / "fetch_bookmarks_api.py")

    def run_fetch(self, handler: type[http.server.BaseHTTPRequestHandler]) -> tuple[int, str]:
        stderr = io.StringIO()
        with LoopbackServer(handler) as host:
            with (
                mock.patch.object(self.api, "BASE_URL", f"http://127.0.0.1:{host.port}/2"),
                mock.patch.object(self.api, "get_valid_token", return_value="test-bearer-token"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                code = self.api.main(["--state-file", str(self.tmp / "state" / "state.json")])
        return code, stderr.getvalue()

    def test_api_get_reports_non_utf8_error_body(self) -> None:
        with LoopbackServer(error_handler(503, LATIN1_PAGE, LATIN1_HEADERS)) as host:
            with mock.patch.object(self.api, "BASE_URL", f"http://127.0.0.1:{host.port}/2"):
                with self.assertRaises(self.api.ApiError) as raised:
                    self.api.api_get("/users/me", "test-bearer-token")

        self.assertEqual(raised.exception.status, 503)
        self.assertIn("HTTP 503: <html>Service indisponible, r\ufffdessayez", str(raised.exception))

    def test_non_utf8_rate_limit_body_keeps_retry_handling(self) -> None:
        headers = {**LATIN1_HEADERS, "x-rate-limit-reset": "1700000000"}

        code, stderr = self.run_fetch(error_handler(429, LATIN1_PAGE, headers))

        self.assertEqual(code, 75)
        self.assertIn("error: HTTP 429:", stderr)
        self.assertRegex(stderr, r"fix: retry after 2023-11-1[45] ")

    def test_unusable_rate_limit_reset_means_no_reset_time(self) -> None:
        for value in ("99999999999999999999", "-99999999999", "soon"):
            with self.subTest(value):
                error = self.api.ApiError(429, "HTTP 429", {"x-rate-limit-reset": value})
                self.assertIsNone(error.reset_at)
        with mock.patch.object(self.api, "datetime") as clock:
            clock.fromtimestamp.side_effect = OSError("Value too large")
            self.assertIsNone(self.api.ApiError(429, "HTTP 429", {"x-rate-limit-reset": "1"}).reset_at)

        headers = {"Content-Type": "application/json", "x-rate-limit-reset": "99999999999999999999"}
        code, stderr = self.run_fetch(error_handler(429, b'{"title": "Too Many Requests"}', headers))

        self.assertEqual(code, 75)
        self.assertIn("error: HTTP 429: Too Many Requests", stderr)
        self.assertIn("fix: wait for the X API rate limit window to reset, then retry", stderr)


class SkillRulesTest(unittest.TestCase):
    def test_skill_marks_bookmark_content_untrusted_and_bird_read_only(self) -> None:
        skill = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
        rules = skill.split("## Operating Rules", 1)[1].split("\n## ", 1)[0]

        self.assertIn("untrusted data", rules)
        for command in ("tweet", "reply", "unbookmark", "follow"):
            self.assertIn(f"`{command}`", rules)


if __name__ == "__main__":
    unittest.main()
