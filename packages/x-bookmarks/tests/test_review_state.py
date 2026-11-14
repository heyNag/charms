"""Review-state regressions for fetch_bookmarks_api.py --since-last/--update-state.

The X API is replaced by an in-memory paginated bookmark list, and every
config and state path points at a temporary directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from test_basic import SCRIPTS, load_module  # noqa: E402


def bookmarks(newest: int, total: int) -> list[dict[str, str]]:
    return posts(str(newest - index) for index in range(total))


def posts(ids) -> list[dict[str, str]]:
    return [{"id": item, "text": f"post {item}", "created_at": "2026-10-01T00:00:00.000Z"} for item in ids]


def returned_ids(output: dict) -> list[str]:
    return [item["id"] for item in output["data"]]


class ReviewStateTest(unittest.TestCase):
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
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.api = load_module("fetch_bookmarks_api_review_state", SCRIPTS / "fetch_bookmarks_api.py")
        self.state_file = self.tmp / "state" / "state.json"
        self.bookmarks = bookmarks(1000, 250)
        self.requests: list[str] = []
        self.token = mock.Mock(return_value="test-token")

    def fake_api_get(self, path: str, _token: str, params: dict[str, str] | None = None):
        self.requests.append(path)
        params = params or {}
        if path == "/users/me":
            return {"data": {"id": "u1", "username": "me", "name": "Me"}}, {}
        start = int(params.get("pagination_token") or 0)
        size = int(params["max_results"])
        meta = {"next_token": str(start + size)} if start + size < len(self.bookmarks) else {}
        return {"data": self.bookmarks[start : start + size], "meta": meta}, {}

    def save_state(self, **entry: object) -> None:
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text(json.dumps({"scopes": {"all": entry}}))

    def saved_entry(self) -> dict:
        return json.loads(self.state_file.read_text())["scopes"]["all"]

    def run_main(self, *argv: str) -> tuple[int, dict | None, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(self.api, "get_valid_token", self.token),
            mock.patch.object(self.api, "api_get", self.fake_api_get),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = self.api.main([*argv, "--state-file", str(self.state_file)])
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, output, stderr.getvalue()

    def write_state(self, content: bytes) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_bytes(content)

    def test_update_state_keeps_cutoff_when_default_count_stops_early(self) -> None:
        # 30 bookmarks arrived since the review; the default --count 20 cannot reach it.
        self.save_state(last_seen_id="970")

        code, output, stderr = self.run_main("--since-last", "--update-state")

        self.assertEqual(code, 0)
        self.assertEqual(self.saved_entry()["last_seen_id"], "970")
        self.assertEqual(len(output["data"]), 20)
        self.assertFalse(output["meta"]["cutoff_reached"])
        self.assertFalse(output["meta"]["state_updated"])
        self.assertIn("warning:", stderr)

        # The next full review still returns every bookmark since the old cutoff.
        _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")
        self.assertEqual(len(output["data"]), 30)
        self.assertTrue(output["meta"]["state_updated"])
        self.assertEqual(self.saved_entry()["last_seen_id"], "1000")

    def test_update_state_keeps_cutoff_when_max_pages_stops_early(self) -> None:
        self.save_state(last_seen_id="850")

        _code, output, _stderr = self.run_main(
            "--all", "--max-pages", "1", "--since-last", "--update-state"
        )

        self.assertEqual(self.saved_entry()["last_seen_id"], "850")
        self.assertFalse(output["meta"]["cutoff_reached"])

    def test_update_state_waits_for_full_fetch_even_with_cutoff_in_window(self) -> None:
        self.save_state(last_seen_id="970")

        _code, output, stderr = self.run_main("--count", "40", "--since-last", "--update-state")

        # The cutoff is inside the window, but a partial fetch cannot confirm it.
        self.assertEqual(returned_ids(output), [str(1000 - i) for i in range(40)])
        self.assertEqual(output["meta"]["cutoff_mode"], "unfiltered")
        self.assertFalse(output["meta"]["cutoff_reached"])
        self.assertFalse(output["meta"]["state_updated"])
        self.assertIn("warning:", stderr)
        self.assertEqual(self.saved_entry()["last_seen_id"], "970")

        _code, output, stderr = self.run_main("--all", "--since-last", "--update-state")

        self.assertEqual(returned_ids(output), [str(1000 - i) for i in range(30)])
        self.assertTrue(output["meta"]["cutoff_reached"])
        self.assertEqual(output["meta"]["cutoff_mode"], "anchor")
        self.assertEqual(stderr, "")
        entry = self.saved_entry()
        self.assertEqual(entry["last_seen_id"], "1000")
        self.assertEqual(len(entry["anchor_ids"]), self.api.STATE_ANCHORS)

    def review_everything(self) -> None:
        """Fully review r1..r300 (r1 newest), saving r1..r50 as anchors."""
        self.state_file.unlink(missing_ok=True)
        self.bookmarks = posts(f"r{index}" for index in range(1, 301))
        _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")
        self.assertTrue(output["meta"]["state_updated"])

    def bookmark(self, *ids: str) -> None:
        """Bookmark each ID now, moving it to the top; later IDs are newer."""
        order = [item["id"] for item in self.bookmarks]
        for item in ids:
            if item in order:
                order.remove(item)
            order.insert(0, item)
        self.bookmarks = posts(order)

    def assert_partial_fetch_is_unconfirmed(self, *argv: str) -> None:
        saved = self.saved_entry()

        _code, output, stderr = self.run_main(*argv, "--since-last", "--update-state")

        self.assertEqual(len(output["data"]), output["meta"]["fetched_count"])
        self.assertEqual(output["meta"]["cutoff_mode"], "unfiltered")
        self.assertFalse(output["meta"]["cutoff_reached"])
        self.assertFalse(output["meta"]["state_updated"])
        self.assertIn("warning:", stderr)
        self.assertEqual(self.saved_entry(), saved)

    def test_reviewed_pair_bookmarked_again_is_not_the_cutoff_in_partial_fetch(self) -> None:
        # r5 then r3 bookmarked again above the new posts form a run of anchors.
        for argv, new_count in ((("--count", "32"), 30), (("--all", "--max-pages", "1"), 98)):
            with self.subTest(argv=argv):
                self.review_everything()
                new = [f"n{index}" for index in range(1, new_count + 1)]
                self.bookmark(*new, "r5", "r3")

                self.assert_partial_fetch_is_unconfirmed(*argv)

                _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")
                self.assertEqual(returned_ids(output), ["r3", "r5", *reversed(new)])

    def test_reviewed_post_bookmarked_again_at_window_edge_is_not_the_cutoff(self) -> None:
        self.review_everything()
        earlier = [f"m{index}" for index in range(1, 11)]
        later = [f"n{index}" for index in range(1, 50)]
        self.bookmark(*earlier, "r30", *later)

        # The 50-item window ends exactly on r30.
        self.assert_partial_fetch_is_unconfirmed("--count", "50")

        _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")
        self.assertEqual(returned_ids(output), [*reversed(later), "r30", *reversed(earlier)])

    def rebookmark_scenario(self, readded: str) -> list[str]:
        """Save r1..r50 as reviewed, then re-bookmark one above 30 new posts."""
        reviewed = [f"r{index}" for index in range(1, 61)]
        self.api.save_state(self.state_file, self.api.update_last_seen({}, "all", reviewed))
        new = [readded, *(f"n{index}" for index in range(30, 0, -1))]
        self.bookmarks = posts([*new, *(item for item in reviewed if item != readded)])
        return new

    def test_rebookmarked_reviewed_post_is_not_the_cutoff_in_partial_fetch(self) -> None:
        # The default --count 20 sees r30 at the top but never reaches r1.
        expected = self.rebookmark_scenario("r30")
        saved = self.saved_entry()

        _code, output, stderr = self.run_main("--since-last", "--update-state")

        self.assertEqual(self.saved_entry(), saved)
        self.assertFalse(output["meta"]["cutoff_reached"])
        self.assertEqual(output["meta"]["cutoff_mode"], "unfiltered")
        self.assertIn("warning:", stderr)

        _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")
        self.assertEqual([item["id"] for item in output["data"]], expected)

    def test_rebookmarked_newest_reviewed_post_is_listed_as_new(self) -> None:
        expected = self.rebookmark_scenario("r1")

        _code, output, _stderr = self.run_main("--all", "--since-last", "--update-state")

        self.assertEqual([item["id"] for item in output["data"]], expected)
        self.assertEqual(output["meta"]["cutoff_mode"], "anchor")

    def test_only_full_fetch_applies_anchor_cutoff(self) -> None:
        reviewed = [f"r{index}" for index in range(1, 51)]
        state = self.api.update_last_seen({}, "all", reviewed)
        # The other reviewed posts were removed; r7 and r12 still mark the cutoff.
        items = [{"id": item} for item in ("n1", "n2", "r7", "r12", "older-1", "older-2")]

        self.assertEqual(self.api.since_last(items, state, "all"), (items[:2], "anchor"))
        lone = [item for item in items if item["id"] != "r12"]
        self.assertEqual(self.api.since_last(lone, state, "all"), (lone[:2], "anchor"))
        # Even adjacent anchors may be reviewed posts bookmarked again above
        # unfetched new ones, so a partial fetch keeps every item.
        self.assertEqual(
            self.api.since_last(items, state, "all", reached_end=False), (items, "unfiltered")
        )

    def test_update_state_refuses_query(self) -> None:
        self.save_state(last_seen_id="970")

        code, output, stderr = self.run_main(
            "--all", "--since-last", "--update-state", "--query", "post 999"
        )

        self.assertEqual(code, 2)
        self.assertIsNone(output)
        self.assertIn("error: --update-state cannot be combined with --query", stderr)
        self.assertEqual(self.saved_entry()["last_seen_id"], "970")

    def test_since_last_uses_next_anchor_when_newest_reviewed_was_removed(self) -> None:
        items = [
            {"id": "new-bookmark-of-old-post", "created_at": "2019-01-01T00:00:00.000Z"},
            {"id": "new-recent", "created_at": "2026-10-05T00:00:00.000Z"},
            {"id": "reviewed-b", "created_at": "2015-01-01T00:00:00.000Z"},
            {"id": "reviewed-c", "created_at": "2026-09-01T00:00:00.000Z"},
        ]
        # reviewed-a, the newest reviewed bookmark, has since been un-bookmarked.
        state = self.api.update_last_seen(
            {}, "all", ["reviewed-a", "reviewed-b", "reviewed-c"], "2026-10-01T00:00:00.000Z"
        )

        result, mode = self.api.since_last(items, state, "all")

        self.assertEqual([item["id"] for item in result], ["new-bookmark-of-old-post", "new-recent"])
        self.assertEqual(mode, "anchor")

    def test_since_last_reads_state_with_only_last_seen_id(self) -> None:
        items = [{"id": "3"}, {"id": "2"}, {"id": "1"}]
        state = {"scopes": {"all": {"last_seen_id": "2"}}}

        self.assertEqual(self.api.since_last(items, state, "all"), ([{"id": "3"}], "anchor"))
        self.assertEqual(self.api.state_anchor_ids(state, "all"), ["2"])

    def test_since_last_without_full_list_does_not_filter_by_created_at(self) -> None:
        items = [
            {"id": "5", "created_at": "2019-01-01T00:00:00.000Z"},
            {"id": "4", "created_at": "2026-10-05T00:00:00.000Z"},
        ]
        state = self.api.update_last_seen({}, "all", ["removed"], "2026-10-01T00:00:00.000Z")

        result, mode = self.api.since_last(items, state, "all", reached_end=False)

        self.assertEqual((len(result), mode), (2, "unfiltered"))

    def test_created_at_fallback_is_flagged_in_meta_and_stderr(self) -> None:
        self.save_state(
            last_seen_id="removed-a",
            anchor_ids=["removed-a", "removed-b"],
            last_seen_created_at="2026-09-01T00:00:00.000Z",
        )

        _code, output, stderr = self.run_main("--all", "--since-last")

        self.assertEqual(output["meta"]["cutoff_mode"], "created_at_fallback")
        self.assertIn("warning: no saved review anchor is still bookmarked", stderr)

    def test_a_damaged_state_file_stops_the_run_before_any_request(self) -> None:
        damaged = {
            "cut short": b'{"scopes": {"all": {"last_seen_id": "97',
            "empty": b"",
            "not UTF-8": b'{"scopes": "\xff\xfe"}',
            "a list": b'["970"]',
            "scopes is a list": b'{"scopes": ["all"]}',
            "a scope is text": b'{"scopes": {"all": "970"}}',
            "anchors are text": b'{"scopes": {"all": {"anchor_ids": "970"}}}',
            "an anchor is an object": b'{"scopes": {"all": {"anchor_ids": [{"id": "970"}]}}}',
            "the newest ID is a list": b'{"scopes": {"all": {"last_seen_id": ["970"]}}}',
            "the time is a number": b'{"scopes": {"all": {"last_seen_id": "970", "last_seen_created_at": 5}}}',
            "another scope is damaged": b'{"scopes": {"all": {"last_seen_id": "970"}, "folder:7": []}}',
        }
        for label, content in damaged.items():
            for flags in (("--since-last",), ("--update-state",), ("--all", "--since-last", "--update-state")):
                with self.subTest(label, flags=flags):
                    self.write_state(content)

                    code, output, stderr = self.run_main(*flags)

                    self.assertEqual(code, 1)
                    self.assertIsNone(output)
                    self.assertIn(f"error: the review state file {self.state_file} is ", stderr)
                    self.assertIn("fix: restore the file from a backup, or move it aside", stderr)
                    self.assertEqual(self.requests, [])
                    self.token.assert_not_called()
                    self.assertEqual(self.state_file.read_bytes(), content)

    def test_a_state_path_that_cannot_be_read_stops_the_run_before_any_request(self) -> None:
        self.state_file.mkdir(parents=True)

        code, output, stderr = self.run_main("--all", "--since-last", "--update-state")

        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertIn(f"error: cannot read the review state file {self.state_file}: ", stderr)
        self.assertEqual(self.requests, [])
        self.token.assert_not_called()

    def test_a_fetch_that_does_not_use_review_state_never_opens_the_file(self) -> None:
        self.write_state(b"{not json")

        code, output, stderr = self.run_main("--count", "5")
        self.assertEqual((code, len(output["data"]), stderr), (0, 5, ""))

        code, output, stderr = self.run_main("--folders", "--since-last")
        self.assertEqual((code, output["meta"]["kind"], stderr), (0, "bookmark-folders", ""))

    def test_state_saved_with_numeric_ids_is_still_read(self) -> None:
        self.write_state(b'{"scopes": {"all": {"last_seen_id": 970, "anchor_ids": [970, 969]}}}')

        code, output, _stderr = self.run_main("--all", "--since-last")

        self.assertEqual(code, 0)
        self.assertEqual(returned_ids(output), [str(1000 - i) for i in range(30)])
        self.assertEqual(output["meta"]["cutoff_mode"], "anchor")

    def test_a_failed_save_still_prints_the_bookmarks_and_reports_the_error(self) -> None:
        self.save_state(last_seen_id="970")
        saved = self.state_file.read_bytes()

        with mock.patch.object(self.api, "save_state", side_effect=PermissionError(13, "Permission denied")):
            code, output, stderr = self.run_main("--all", "--since-last", "--update-state")

        self.assertEqual(code, 1)
        self.assertEqual(returned_ids(output), [str(1000 - i) for i in range(30)])
        self.assertFalse(output["meta"]["state_updated"])
        self.assertIn(f"error: cannot save the review state file {self.state_file}: Permission denied", stderr)
        self.assertIn("fix: make that folder writable or pass --state-file", stderr)
        self.assertEqual(self.state_file.read_bytes(), saved)

    def test_a_tilde_in_the_state_path_is_expanded_once_for_reading_and_saving(self) -> None:
        home = self.tmp / "home"
        home.mkdir()
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {"HOME": str(home)}),
            mock.patch.object(self.api, "get_valid_token", self.token),
            mock.patch.object(self.api, "api_get", self.fake_api_get),
            contextlib.redirect_stdout(stdout),
        ):
            code = self.api.main(["--all", "--update-state", "--state-file", "~/reviews/state.json"])

        expected = home / "reviews" / "state.json"
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["meta"]["state_file"], str(expected))
        self.assertEqual(json.loads(expected.read_text())["scopes"]["all"]["last_seen_id"], "1000")
        self.assertFalse((Path.cwd() / "~").exists())

    def test_update_last_seen_keeps_newest_anchors_then_older_ones(self) -> None:
        state = self.api.update_last_seen({}, "all", ["old-2", "old-1"])
        fetched = [str(index) for index in range(60, 0, -1)]

        entry = self.api.update_last_seen(state, "all", fetched)["scopes"]["all"]

        self.assertEqual(len(entry["anchor_ids"]), self.api.STATE_ANCHORS)
        self.assertEqual(entry["anchor_ids"][:2], ["60", "59"])
        self.assertEqual(
            self.api.update_last_seen(state, "all", ["new"])["scopes"]["all"]["anchor_ids"],
            ["new", "old-2", "old-1"],
        )


if __name__ == "__main__":
    unittest.main()
