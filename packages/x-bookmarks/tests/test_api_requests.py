"""Token refresh, the retry after a rejected token, and folder fetches.

Every request goes to fake_x.FakeX on a loopback port, and every config,
token and state path points at a temporary directory.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from fake_x import FakeX  # noqa: E402
from test_basic import SCRIPTS, load_module  # noqa: E402

CLIENT = "test-client"
CLIENT_SECRET = "test-client-secret"
SCOPES = ["tweet.read", "users.read", "bookmark.read", "offline.access"]


def grant(access: str, refresh: str | None = "refresh-2") -> dict:
    """A token response as X sends it for a refresh."""
    response = {"token_type": "bearer", "expires_in": 7200, "access_token": access, "scope": " ".join(SCOPES)}
    if refresh:
        response["refresh_token"] = refresh
    return response


def ids(output: dict) -> list[str]:
    return [item["id"] for item in output["data"]]


class FakeXCase(unittest.TestCase):
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

        # The fetch helper imports x_api_auth by name. Load both afresh so that
        # they share this test's paths, then put back what was loaded before.
        self.addCleanup(self.restore_auth_module, sys.modules.pop("x_api_auth", None))
        self.api = load_module("fetch_bookmarks_api_fake_x", SCRIPTS / "fetch_bookmarks_api.py")
        self.auth = sys.modules["x_api_auth"]
        self.assertTrue(str(self.auth.TOKEN_FILE).startswith(str(self.tmp)))
        self.state_file = self.tmp / "state" / "state.json"
        self.assertEqual(self.api.default_state_file(), self.state_file)

        # Point both helpers at the fake before any test can make a request.
        self.x = FakeX().start()
        self.addCleanup(self.x.stop)
        for module, name, value in (
            (self.api, "BASE_URL", f"{self.x.url}/2"),
            (self.auth, "TOKEN_URL", f"{self.x.url}/2/oauth2/token"),
        ):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def restore_auth_module(previous: object) -> None:
        if previous is None:
            sys.modules.pop("x_api_auth", None)
        else:
            sys.modules["x_api_auth"] = previous  # type: ignore[assignment]

    def save_login(
        self, access: str = "access-1", refresh: str | None = "refresh-1", expires_in: int = 7200, **config: object
    ) -> None:
        self.auth.save_config({"client_id": CLIENT, "scopes": SCOPES, **config})
        tokens = {"access_token": access, "expires_at": int(time.time()) + expires_in}
        if refresh:
            tokens["refresh_token"] = refresh
        self.auth.save_tokens(tokens)

    def saved_tokens(self) -> dict:
        return json.loads(self.auth.TOKEN_FILE.read_text())

    def fetch(self, *argv: str) -> tuple[int, dict | None, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.api.main(list(argv))
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, output, stderr.getvalue()

    def queries(self, suffix: str) -> list[dict[str, str]]:
        return [item["query"] for item in self.x.requests if item["path"].endswith(suffix)]


class RefreshTest(FakeXCase):
    def test_an_expired_token_is_refreshed_and_the_new_login_saved(self) -> None:
        self.save_login(expires_in=-60)
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        self.assertEqual(self.auth.get_valid_token(), "access-2")

        (request,) = self.x.requests
        self.assertEqual((request["method"], request["path"]), ("POST", "/2/oauth2/token"))
        self.assertEqual(
            request["form"],
            {"grant_type": "refresh_token", "refresh_token": "refresh-1", "client_id": CLIENT},
        )
        self.assertIsNone(request["authorization"])
        saved = self.saved_tokens()
        self.assertEqual((saved["access_token"], saved["refresh_token"]), ("access-2", "refresh-2"))
        self.assertAlmostEqual(saved["expires_at"], time.time() + 7200, delta=60)
        self.assertEqual(saved["scope_list"], SCOPES)
        self.assertEqual(stat.S_IMODE(self.auth.TOKEN_FILE.stat().st_mode), 0o600)

    def test_the_old_refresh_token_is_kept_when_x_sends_no_new_one(self) -> None:
        self.save_login(expires_in=-60)
        self.x.refresh_grants["refresh-1"] = grant("access-2", refresh=None)

        self.assertEqual(self.auth.get_valid_token(), "access-2")

        self.assertEqual(self.saved_tokens()["refresh_token"], "refresh-1")

    def test_a_confidential_client_refreshes_with_basic_authentication(self) -> None:
        expected = base64.b64encode(f"{CLIENT}:{CLIENT_SECRET}".encode()).decode()
        for label, config, environment in (
            ("saved secret", {"client_secret": CLIENT_SECRET}, {}),
            ("secret from the environment", {}, {"X_API_CLIENT_SECRET": CLIENT_SECRET}),
        ):
            with self.subTest(label), mock.patch.dict(os.environ, environment):
                self.x.requests.clear()
                self.save_login(expires_in=-60, **config)
                self.x.refresh_grants["refresh-1"] = grant("access-2")

                self.assertEqual(self.auth.get_valid_token(), "access-2")

                (request,) = self.x.requests
                self.assertEqual(request["authorization"], f"Basic {expected}")
                self.assertEqual(request["form"], {"grant_type": "refresh_token", "refresh_token": "refresh-1"})

    def test_a_token_that_is_not_due_is_used_without_a_request(self) -> None:
        self.save_login(expires_in=3600)
        self.assertEqual(self.auth.get_valid_token(), "access-1")

        # A login saved without an expiry time is not refreshed on a guess.
        self.auth.save_tokens({"access_token": "access-1", "refresh_token": "refresh-1"})
        self.assertEqual(self.auth.get_valid_token(), "access-1")

        self.assertEqual(self.x.requests, [])

    def test_a_token_about_to_expire_or_missing_is_refreshed_first(self) -> None:
        for label, tokens in (
            ("expires within two minutes", {"access_token": "access-1", "expires_at": int(time.time()) + 90}),
            ("no access token", {"access_token": "", "expires_at": int(time.time()) + 3600}),
        ):
            with self.subTest(label):
                self.x.requests.clear()
                self.save_login()
                self.auth.save_tokens({**tokens, "refresh_token": "refresh-1"})
                self.x.refresh_grants["refresh-1"] = grant("access-2")

                self.assertEqual(self.auth.get_valid_token(), "access-2")
                self.assertEqual(self.x.paths(), ["/2/oauth2/token"])

    def test_a_forced_refresh_replaces_a_token_that_is_not_due(self) -> None:
        self.save_login(expires_in=3600)
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        self.assertEqual(self.auth.get_valid_token(force_refresh=True), "access-2")
        self.assertEqual(self.saved_tokens()["access_token"], "access-2")

    def test_a_token_from_the_environment_is_used_as_it_is(self) -> None:
        self.save_login(expires_in=-60)
        self.assertIsNone(self.auth.token_variable())

        for environment, variable, token in (
            ({"X_API_BEARER_TOKEN": "bearer-env"}, "X_API_BEARER_TOKEN", "bearer-env"),
            ({"X_API_ACCESS_TOKEN": "access-env"}, "X_API_ACCESS_TOKEN", "access-env"),
            (
                {"X_API_BEARER_TOKEN": "bearer-env", "X_API_ACCESS_TOKEN": "access-env"},
                "X_API_ACCESS_TOKEN",
                "access-env",
            ),
        ):
            with self.subTest(variable=variable, set=sorted(environment)), mock.patch.dict(os.environ, environment):
                self.assertEqual(self.auth.token_variable(), variable)
                self.assertEqual(self.auth.get_valid_token(), token)
                self.assertEqual(self.auth.get_valid_token(force_refresh=True), token)

        self.assertEqual(self.x.requests, [])
        self.assertEqual(self.saved_tokens()["access_token"], "access-1")

    def test_a_refresh_that_cannot_work_is_an_auth_error_and_keeps_the_saved_login(self) -> None:
        for label, login, config, message, requests in (
            ("no refresh token", {"refresh": None}, {}, "missing refresh_token; rerun setup", 0),
            ("no client ID", {}, {"client_id": ""}, "missing client_id in config; rerun setup", 0),
            ("X refuses the refresh token", {}, {}, "token request failed with HTTP 400", 1),
        ):
            with self.subTest(label):
                self.x.requests.clear()
                self.save_login(expires_in=-60, **login, **config)
                saved = self.auth.TOKEN_FILE.read_bytes()

                with self.assertRaises(self.auth.AuthError) as raised:
                    self.auth.get_valid_token()

                self.assertIn(message, str(raised.exception))
                self.assertEqual(len(self.x.requests), requests)
                self.assertEqual(self.auth.TOKEN_FILE.read_bytes(), saved)

    def test_the_refresh_command_reports_the_result_without_printing_tokens(self) -> None:
        self.save_login(expires_in=3600)
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        def refresh() -> tuple[int, str]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                return self.auth.main(["--refresh"]), output.getvalue()

        code, output = refresh()
        self.assertEqual((code, output), (0, "auth: refreshed\n"))
        self.assertEqual(self.saved_tokens()["access_token"], "access-2")

        # X uses a refresh token once, and this fake has no grant for the next.
        code, output = refresh()
        self.assertEqual(code, 1)
        self.assertIn("error: token request failed with HTTP 400", output)
        self.assertNotIn("refresh-2", output)
        self.assertEqual(self.saved_tokens()["access_token"], "access-2")


class RejectedTokenTest(FakeXCase):
    def setUp(self) -> None:
        super().setUp()
        self.x.bookmarks = [str(1000 - index) for index in range(250)]

    def test_a_rejected_token_is_refreshed_once_and_the_request_repeated(self) -> None:
        # The saved token is not due, but X no longer knows it.
        self.save_login()
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 0)
        self.assertEqual(ids(output), ["1000", "999", "998", "997", "996"])
        self.assertEqual(
            self.x.paths(), ["/2/users/me", "/2/oauth2/token", "/2/users/me", "/2/users/42/bookmarks"]
        )
        self.assertEqual(
            [item["authorization"] for item in self.x.requests if item["method"] == "GET"],
            ["Bearer access-1", "Bearer access-2", "Bearer access-2"],
        )
        self.assertEqual(self.saved_tokens()["access_token"], "access-2")
        self.assertEqual(
            stderr, "note: X rejected the saved access token; refreshed it and repeated the request\n"
        )

    def test_a_token_rejected_between_pages_repeats_only_that_page(self) -> None:
        self.save_login()
        self.x.access_tokens.add("access-1")
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        def revoke_before_the_third_page(request: dict) -> None:
            if request["query"].get("pagination_token") == "200":
                self.x.access_tokens.discard("access-1")

        self.x.intercept = revoke_before_the_third_page

        code, output, _stderr = self.fetch("--all")

        self.assertEqual(code, 0)
        self.assertEqual(ids(output), self.x.bookmarks)
        self.assertEqual(
            [query.get("pagination_token") for query in self.queries("/bookmarks")], [None, "100", "200", "200"]
        )
        self.assertEqual(self.x.paths("POST"), ["/2/oauth2/token"])

    def test_a_second_rejection_is_reported_and_not_retried(self) -> None:
        self.save_login()
        self.x.refresh_grants["refresh-1"] = grant("access-2")
        # X refuses the refreshed token as well.
        self.x.intercept = lambda request: (401, {"title": "Unauthorized"}) if request["method"] == "GET" else None

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertEqual(self.x.paths(), ["/2/users/me", "/2/oauth2/token", "/2/users/me"])
        self.assertIn("error: HTTP 401: Unauthorized", stderr)
        self.assertIn("fix: X rejected the saved login even after a refresh; rerun setup", stderr)

    def test_a_rejected_token_from_the_environment_is_not_refreshed(self) -> None:
        self.save_login()
        self.x.refresh_grants["refresh-1"] = grant("access-2")

        with mock.patch.dict(os.environ, {"X_API_ACCESS_TOKEN": "stale-env-token"}):
            code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertEqual(self.x.paths(), ["/2/users/me"])
        self.assertIn("error: HTTP 401: Unauthorized", stderr)
        self.assertIn("fix: X rejected the access token in X_API_ACCESS_TOKEN", stderr)
        self.assertNotIn("stale-env-token", stderr)
        self.assertEqual(self.saved_tokens()["access_token"], "access-1")

    def test_a_refresh_that_fails_after_a_rejection_names_both(self) -> None:
        # X knows neither the saved access token nor the refresh token.
        self.save_login()

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertEqual(self.x.paths(), ["/2/users/me", "/2/oauth2/token"])
        self.assertIn(
            "error: X rejected the saved access token (HTTP 401), and refreshing it failed: "
            "token request failed with HTTP 400",
            stderr,
        )
        self.assertIn("fix: run python3 scripts/x_api_auth.py", stderr)
        self.assertEqual(self.saved_tokens()["access_token"], "access-1")

    def test_an_error_that_is_not_a_rejected_token_is_not_retried(self) -> None:
        self.save_login()
        self.x.access_tokens.add("access-1")
        self.x.refresh_grants["refresh-1"] = grant("access-2")
        self.x.intercept = lambda request: (
            (403, {"title": "Forbidden", "detail": "Missing scope."}) if request["path"].endswith("/bookmarks") else None
        )

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertEqual(self.x.paths(), ["/2/users/me", "/2/users/42/bookmarks"])
        self.assertIn("error: HTTP 403: Missing scope.", stderr)
        self.assertIn("fix: check X Developer app scopes and API access level", stderr)


class FetchOutputTest(FakeXCase):
    def setUp(self) -> None:
        super().setUp()
        self.save_login()
        self.x.access_tokens.add("access-1")
        self.x.bookmarks = [str(1000 - index) for index in range(30)]

    def answer_bookmarks_with(self, payload: dict) -> None:
        self.x.intercept = lambda request: (200, payload) if request["path"].endswith("/bookmarks") else None

    def test_a_post_carries_its_author_media_and_quoted_post(self) -> None:
        self.answer_bookmarks_with(
            {
                "data": [
                    {
                        "id": "11",
                        "text": "short text",
                        "note_tweet": {"text": "the long text of a note"},
                        "author_id": "7",
                        "created_at": "2026-10-02T08:00:00.000Z",
                        "lang": "en",
                        "public_metrics": {"like_count": 3},
                        "attachments": {"media_keys": ["3_1", "3_gone"]},
                        "referenced_tweets": [{"type": "quoted", "id": "12"}, {"type": "replied_to", "id": "13"}],
                    },
                    {"id": "14", "text": "author not included", "author_id": "99"},
                    {"text": "no id, so it is dropped"},
                ],
                "includes": {
                    "users": [
                        {"id": "7", "username": "author", "name": "Author", "verified": True},
                        {"id": "8", "username": "quoted", "name": "Quoted"},
                    ],
                    "tweets": [{"id": "12", "text": "the quoted post", "author_id": "8"}],
                    "media": [{"media_key": "3_1", "type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"}],
                },
                "meta": {"result_count": 3},
            }
        )

        code, output, _stderr = self.fetch("--count", "5")

        self.assertEqual(code, 0)
        first, second = output["data"]
        self.assertEqual(
            {key: first[key] for key in ("id", "url", "text", "created_at", "lang", "source")},
            {
                "id": "11",
                "url": "https://x.com/author/status/11",
                "text": "the long text of a note",
                "created_at": "2026-10-02T08:00:00.000Z",
                "lang": "en",
                "source": "x-api-v2",
            },
        )
        self.assertEqual(first["author"]["url"], "https://x.com/author")
        self.assertTrue(first["author"]["verified"])
        self.assertEqual(first["public_metrics"], {"like_count": 3})
        self.assertEqual(first["media"], [{"media_key": "3_1", "type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"}])
        quoted, reply = first["referenced_tweets"]
        self.assertEqual(
            quoted,
            {
                "type": "quoted",
                "id": "12",
                "text": "the quoted post",
                "author": {"id": "8", "username": "quoted", "name": "Quoted", "url": "https://x.com/quoted"},
                "url": "https://x.com/quoted/status/12",
            },
        )
        # A referenced post X did not include keeps its ID and a neutral link.
        self.assertEqual(
            reply,
            {"type": "replied_to", "id": "13", "text": None, "author": None, "url": "https://x.com/i/web/status/13"},
        )
        self.assertEqual(second["url"], "https://x.com/i/web/status/14")
        self.assertIsNone(second["author"]["username"])

    def test_the_query_filters_fetched_posts_and_reports_both_counts(self) -> None:
        code, output, _stderr = self.fetch("--all", "--query", "POST 99")

        self.assertEqual(code, 0)
        self.assertEqual(ids(output), [str(item) for item in range(999, 989, -1)])
        self.assertEqual((output["meta"]["count"], output["meta"]["fetched_count"]), (10, 30))
        self.assertEqual(output["meta"]["query"], "POST 99")

    def test_the_request_names_the_plugin_and_the_rate_limit_is_reported(self) -> None:
        self.x.headers = {
            "x-rate-limit-limit": "180",
            "x-rate-limit-remaining": "178",
            "x-rate-limit-reset": "1900000000",
        }

        code, output, _stderr = self.fetch("--count", "5")

        self.assertEqual(code, 0)
        self.assertEqual(output["meta"]["rate_limit"], self.x.headers)
        self.assertEqual({item["authorization"] for item in self.x.requests}, {"Bearer access-1"})
        for request in self.x.requests:
            self.assertRegex(request["user_agent"], r"^charms-x-bookmarks/(\d+\.\d+\.\d+|unknown)$")
        (query,) = self.queries("/bookmarks")
        self.assertEqual(query["max_results"], "5")
        self.assertIn("note_tweet", query["tweet.fields"])
        self.assertIn("referenced_tweets.id", query["expansions"])

    def test_a_payment_error_points_to_bird_first(self) -> None:
        self.x.intercept = lambda request: (
            (402, {"title": "Payment Required"}) if request["path"].endswith("/bookmarks") else None
        )

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertEqual(
            stderr.splitlines(),
            [
                "error: HTTP 402: Payment Required",
                "fix: use the Bird no-credit backend first: scripts/fetch_bookmarks_bird.sh --count 25",
                "fix: if you explicitly want the official X API path, add X API credits or an eligible plan, "
                "then retry",
            ],
        )

    def test_an_answer_without_the_user_is_an_error(self) -> None:
        self.x.intercept = lambda request: (200, {"errors": [{"title": "x"}]}) if request["path"] == "/2/users/me" else None

        code, output, stderr = self.fetch("--count", "5")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertIn("error: could not resolve authenticated X user", stderr)
        self.assertEqual(self.x.paths(), ["/2/users/me"])

    def test_options_that_cannot_work_stop_before_any_request(self) -> None:
        for argv, message in (
            (("--count", "0"), "error: --count must be at least 1"),
            (("--folders", "--folder-id", "7001"), "error: use either --folders or --folder-id, not both"),
        ):
            with self.subTest(argv=argv):
                code, output, stderr = self.fetch(*argv)

                self.assertEqual(code, 2)
                self.assertIsNone(output)
                self.assertIn(message, stderr)
        self.assertEqual(self.x.requests, [])


class FolderTest(FakeXCase):
    def setUp(self) -> None:
        super().setUp()
        self.save_login()
        self.x.access_tokens.add("access-1")
        self.x.folders = [{"id": str(7000 + index), "name": f"Folder {index}"} for index in range(230)]
        self.x.folder_posts["7001"] = [str(500 - index) for index in range(250)]

    def lookups(self) -> list[int]:
        return [len(query["ids"].split(",")) for query in self.queries("/tweets")]

    def test_all_folders_are_listed_page_by_page(self) -> None:
        code, output, stderr = self.fetch("--folders", "--all")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(output["data"], self.x.folders)
        self.assertEqual(output["meta"]["kind"], "bookmark-folders")
        self.assertEqual(output["meta"]["count"], 230)
        self.assertEqual(output["meta"]["authenticated_user"], self.x.user)
        self.assertEqual(
            self.queries("/folders"),
            [
                {"max_results": "100"},
                {"max_results": "100", "pagination_token": "100"},
                {"max_results": "100", "pagination_token": "200"},
            ],
        )

    def test_a_folder_count_asks_for_no_more_than_it_needs(self) -> None:
        for argv, expected, sizes in (
            ((), 20, ["20"]),
            (("--count", "3"), 3, ["3"]),
            (("--count", "150"), 150, ["100", "50"]),
            (("--count", "500"), 230, ["100", "100", "100"]),
        ):
            with self.subTest(argv=argv):
                self.x.requests.clear()

                code, output, _stderr = self.fetch("--folders", *argv)

                self.assertEqual(code, 0)
                self.assertEqual(output["data"], self.x.folders[:expected])
                self.assertEqual([query["max_results"] for query in self.queries("/folders")], sizes)

    def test_max_pages_stops_a_folder_listing(self) -> None:
        code, output, _stderr = self.fetch("--folders", "--all", "--max-pages", "2")

        self.assertEqual(code, 0)
        self.assertEqual(output["data"], self.x.folders[:200])
        self.assertEqual(len(self.queries("/folders")), 2)

    def test_a_folder_is_read_as_ids_then_looked_up_in_folder_order(self) -> None:
        self.x.deleted_posts = {"499", "251"}

        code, output, stderr = self.fetch("--folder-id", "7001", "--all")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(ids(output), [item for item in self.x.folder_posts["7001"] if item not in {"499", "251"}])
        self.assertEqual({item["folder_id"] for item in output["data"]}, {"7001"})
        self.assertEqual(output["data"][0]["author"]["username"], "author")
        self.assertEqual(output["data"][0]["url"], "https://x.com/author/status/500")
        self.assertEqual(output["meta"]["state_scope"], "folder:7001")
        self.assertEqual(output["meta"]["fetched_count"], 248)
        self.assertTrue(output["meta"]["cutoff_reached"])
        # IDs arrive 100 to a page, and lookups go 100 to a request.
        self.assertEqual(
            [query.get("pagination_token") for query in self.queries("/folders/7001")], [None, "100", "200"]
        )
        self.assertEqual(self.lookups(), [100, 100, 50])

    def test_a_folder_window_is_a_partial_fetch(self) -> None:
        code, output, _stderr = self.fetch("--folder-id", "7001", "--count", "30")

        self.assertEqual(code, 0)
        self.assertEqual(ids(output), self.x.folder_posts["7001"][:30])
        self.assertFalse(output["meta"]["cutoff_reached"])
        self.assertEqual(self.queries("/folders/7001"), [{"max_results": "30"}])
        self.assertEqual(self.lookups(), [30])

    def test_an_empty_folder_makes_no_lookup(self) -> None:
        self.x.folder_posts["7002"] = []

        code, output, stderr = self.fetch("--folder-id", "7002", "--all", "--since-last", "--update-state")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(output["data"], [])
        self.assertTrue(output["meta"]["cutoff_reached"])
        self.assertFalse(output["meta"]["state_updated"])
        self.assertEqual(self.lookups(), [])
        self.assertFalse(self.state_file.exists())

    def test_a_folder_keeps_its_own_review_cutoff(self) -> None:
        self.x.bookmarks = ["902", "901", *self.x.folder_posts["7001"]]
        review = ("--folder-id", "7001", "--all", "--since-last", "--update-state")

        code, output, _stderr = self.fetch(*review)
        self.assertEqual(code, 0)
        self.assertEqual((output["meta"]["cutoff_mode"], output["meta"]["state_updated"]), ("no_state", True))
        self.assertEqual(list(json.loads(self.state_file.read_text())["scopes"]), ["folder:7001"])

        self.x.folder_posts["7001"] = ["902", "901", *self.x.folder_posts["7001"]]
        code, output, _stderr = self.fetch(*review)
        self.assertEqual(code, 0)
        self.assertEqual(ids(output), ["902", "901"])
        self.assertEqual(output["meta"]["cutoff_mode"], "anchor")

        # The whole bookmark list has no cutoff of its own yet.
        code, output, _stderr = self.fetch("--all", "--since-last")
        self.assertEqual(code, 0)
        self.assertEqual(output["meta"]["cutoff_mode"], "no_state")
        self.assertEqual(len(output["data"]), 252)

    def test_an_early_stop_saves_folder_pages_and_lookups(self) -> None:
        review = ("--folder-id", "7001", "--all", "--since-last", "--update-state")
        self.fetch(*review)
        self.assertEqual((len(self.queries("/folders/7001")), self.lookups()), (3, [100, 100, 50]))
        self.x.folder_posts["7001"] = ["903", "902", "901", *self.x.folder_posts["7001"]]
        self.x.requests.clear()

        code, output, stderr = self.fetch(*review, "--stop-after-known", "5")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(ids(output), ["903", "902", "901"])
        self.assertEqual(output["meta"]["cutoff_mode"], "early_stop")
        self.assertTrue(output["meta"]["state_updated"])
        self.assertEqual((len(self.queries("/folders/7001")), self.lookups()), (1, [100]))

    def test_a_folder_id_that_is_not_digits_is_refused_before_any_request(self) -> None:
        refused = (
            "../../me",
            "7001/../../../tweets",
            "7001?max_results=1",
            "70 01",
            "7001\n",
            "-7001",
            "seven",
            "",
            # Digits, but not the ASCII ones an ID is made of.
            "\uff17\uff10\uff10\uff11",
            # One digit more than X allows.
            "12345678901234567890",
        )
        for value in refused:
            for argv in (("--folder-id", value), (f"--folder-id={value}", "--all", "--since-last")):
                with self.subTest(argv=argv):
                    code, output, stderr = self.fetch(*argv)

                    self.assertEqual(code, 2)
                    self.assertIsNone(output)
                    self.assertEqual(
                        stderr.splitlines(),
                        [
                            "error: --folder-id must be a folder's numeric ID of 1 to 19 digits",
                            "fix: list the folders with --folders, then pass one of their IDs",
                        ],
                    )
        self.assertEqual(self.x.requests, [])

    def test_the_longest_folder_id_x_allows_is_sent_as_it_is(self) -> None:
        longest = "1234567890123456789"
        self.x.folder_posts[longest] = ["500", "499"]

        code, output, _stderr = self.fetch("--folder-id", longest, "--all")

        self.assertEqual(code, 0)
        self.assertEqual(ids(output), ["500", "499"])
        self.assertIn(f"/2/users/42/bookmarks/folders/{longest}", self.x.paths())

    def test_a_folder_x_does_not_know_is_an_api_error(self) -> None:
        code, output, stderr = self.fetch("--folder-id", "7999")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertIn("error: HTTP 404: Could not find the folder.", stderr)
        self.assertEqual(self.lookups(), [])


if __name__ == "__main__":
    unittest.main()
