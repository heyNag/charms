from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "x-bookmarks" / "scripts"


def load_module(name: str, path: Path):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(SCRIPTS))
        except ValueError:
            pass


class XBookmarksHelpersTest(unittest.TestCase):
    def test_filter_query_matches_text_author_and_refs(self) -> None:
        api = load_module("fetch_bookmarks_api", SCRIPTS / "fetch_bookmarks_api.py")
        items = [
            {
                "text": "Agent workflow notes",
                "url": "https://x.com/a/status/1",
                "author": {"username": "builder", "name": "Builder"},
                "referenced_tweets": [{"text": "MCP detail", "author": {"username": "tools"}}],
            },
            {
                "text": "Cooking notes",
                "url": "https://x.com/b/status/2",
                "author": {"username": "chef", "name": "Chef"},
                "referenced_tweets": [],
            },
        ]

        self.assertEqual(api.filter_query(items, "agent mcp"), [items[0]])
        self.assertEqual(api.filter_query(items, "chef"), [items[1]])

    def test_since_last_stops_at_saved_id(self) -> None:
        api = load_module("fetch_bookmarks_api_state", SCRIPTS / "fetch_bookmarks_api.py")
        items = [{"id": "3"}, {"id": "2"}, {"id": "1"}]
        state = {"scopes": {"all": {"last_seen_id": "2"}}}

        self.assertEqual(api.since_last(items, state, "all"), [{"id": "3"}])

    def test_since_last_falls_back_to_created_at_when_id_removed(self) -> None:
        api = load_module("fetch_bookmarks_api_removed", SCRIPTS / "fetch_bookmarks_api.py")
        items = [
            {"id": "5", "created_at": "2026-07-02T10:00:00.000Z"},
            {"id": "4", "created_at": "2026-07-01T10:00:00.000Z"},
            {"id": "3", "created_at": "2026-06-30T10:00:00.000Z"},
        ]
        state = {
            "scopes": {
                "all": {
                    "last_seen_id": "removed-id",
                    "last_seen_created_at": "2026-07-01T00:00:00.000Z",
                }
            }
        }

        self.assertEqual(
            [item["id"] for item in api.since_last(items, state, "all")],
            ["5", "4"],
        )

        # Without a stored created_at, the old everything-again behavior remains.
        legacy_state = {"scopes": {"all": {"last_seen_id": "removed-id"}}}
        self.assertEqual(len(api.since_last(items, legacy_state, "all")), 3)

    def test_update_last_seen_records_created_at(self) -> None:
        api = load_module("fetch_bookmarks_api_update", SCRIPTS / "fetch_bookmarks_api.py")

        state = api.update_last_seen({}, "all", "9", "2026-07-02T10:00:00.000Z")

        entry = state["scopes"]["all"]
        self.assertEqual(entry["last_seen_id"], "9")
        self.assertEqual(entry["last_seen_created_at"], "2026-07-02T10:00:00.000Z")
        self.assertEqual(state["last_seen_id"], "9")

    def test_pkce_pair_shape(self) -> None:
        auth = load_module("x_api_auth", SCRIPTS / "x_api_auth.py")
        verifier, challenge = auth.pkce_pair()

        self.assertGreaterEqual(len(verifier), 40)
        self.assertNotIn("=", challenge)
        self.assertGreaterEqual(len(challenge), 40)

    def test_token_request_missing_access_token_error_is_sanitized(self) -> None:
        auth = load_module("x_api_auth_sanitized", SCRIPTS / "x_api_auth.py")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"refresh_token":"sensitive-refresh-value"}'

        with mock.patch.object(auth.urllib.request, "urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(auth.AuthError, "did not return access_token") as raised:
                auth.token_request({"grant_type": "refresh_token"}, "client-id")

        self.assertNotIn("sensitive-refresh-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
