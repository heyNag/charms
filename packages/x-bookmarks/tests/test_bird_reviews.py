"""fetch_bookmarks_bird.py: the review cutoff, and how much of the list each review reads.

Every Bird run is answered by fake_bird.FakeBird, which pages the way Bird
0.8.0 does. The last class reviews one account through both backends, with
fake_x.FakeX as the X API. No test reaches X or a browser's cookies.
test_bird_helper.py covers the options and Bird's output.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from fake_bird import FakeBird, post  # noqa: E402
from test_api_requests import FakeXCase  # noqa: E402
from test_basic import SCRIPTS, load_module  # noqa: E402

SCRIPT = SCRIPTS / "fetch_bookmarks_bird.py"
BIRD = "/fake/bin/bird"
REVIEW = ("--all", "--since-last", "--update-state")
FORMAT_FIX = (
    "fix: this helper reads what Bird 0.8.0 prints for `bird bookmarks --json`; compare `bird --version`, "
    "and see the raw output with scripts/fetch_bookmarks_bird.sh"
)
PARTIAL = [
    "warning: the fetch stopped before the end of the list, so the last review cutoff cannot be "
    "confirmed and some new bookmarks may not have been fetched; review state was not updated",
    "fix: rerun with --all and without --max-pages",
]


def numbered(count: int, first: int = 1001) -> list[str]:
    """Post IDs for `count` bookmarks, newest first."""
    return [str(number) for number in range(first + count - 1, first - 1, -1)]


def command(*options: str) -> list[str]:
    return [BIRD, "bookmarks", "--json", "--plain", *options]


def ids(output: dict) -> list[str]:
    return [item["id"] for item in output["data"]]


class BirdMixin:
    """Loads the helper and answers its Bird runs from a FakeBird."""

    def use_fake_bird(self) -> None:
        self.helper = load_module("fetch_bookmarks_bird_fake", SCRIPT)
        self.bird = FakeBird()
        for name, value in (("run_bird", self.bird.run), ("find_bird", lambda: BIRD)):
            patcher = mock.patch.object(self.helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_bird_helper(self, *argv: str) -> tuple[int, dict | None, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.helper.main(list(argv))
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, output, stderr.getvalue()


class BirdCase(BirdMixin, unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_file = Path(tmp.name) / "state" / "state.json"
        env = mock.patch.dict(os.environ, {"X_BOOKMARKS_STATE_FILE": str(self.state_file)})
        env.start()
        self.addCleanup(env.stop)
        self.use_fake_bird()

    def state(self, scope: str = "all") -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))["scopes"][scope]

    def reviewed(self, count: int) -> list[str]:
        """Bookmark `count` posts, review them, and forget what that cost."""
        self.bird.bookmarks = numbered(count)
        code, output, stderr = self.run_bird_helper(*REVIEW)
        self.assertEqual((code, stderr, len(output["data"])), (0, "", count))
        self.bird.runs.clear()
        self.bird.pages = 0
        return list(self.bird.bookmarks)

    def bookmark(self, count: int) -> list[str]:
        """Bookmark `count` more posts and return their IDs, newest first."""
        new = numbered(count, first=5001 + len(self.bird.bookmarks))
        self.bird.bookmarks[:0] = new
        return new


class WindowTest(BirdCase):
    def test_a_window_asks_bird_for_that_many_posts(self) -> None:
        self.bird.bookmarks = numbered(30)

        code, output, stderr = self.run_bird_helper("--count", "7")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--count=7")])
        self.assertEqual(self.bird.timeouts, [600.0])
        self.assertEqual(ids(output), numbered(30)[:7])
        meta = output["meta"]
        fetched_at = datetime.fromisoformat(meta.pop("fetched_at"))
        self.assertLess(abs((datetime.now(timezone.utc) - fetched_at).total_seconds()), 120)
        self.assertEqual(
            meta,
            {
                "kind": "bookmarks",
                "count": 7,
                "fetched_count": 7,
                "since_last": False,
                "cutoff_mode": None,
                "cutoff_reached": False,
                "stopped_early": False,
                "state_updated": False,
                "state_scope": "all",
                "state_file": str(self.state_file),
            },
        )
        self.assertFalse(self.state_file.exists())

    def test_twenty_posts_are_fetched_when_no_count_is_given(self) -> None:
        self.bird.bookmarks = numbered(30)

        _code, output, _stderr = self.run_bird_helper()

        self.assertEqual(self.bird.runs, [command("--count=20")])
        self.assertEqual(len(output["data"]), 20)

    def test_fewer_posts_than_asked_for_means_the_list_ended(self) -> None:
        self.bird.bookmarks = numbered(3)

        code, output, stderr = self.run_bird_helper("--count", "5", "--since-last", "--update-state")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(ids(output), numbered(3))
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["cutoff_reached"], meta["state_updated"]), ("no_state", True, True)
        )
        self.assertEqual(self.state()["anchor_ids"], numbered(3))

    def test_a_full_window_cannot_confirm_the_cutoff(self) -> None:
        self.reviewed(30)
        saved = self.state_file.read_bytes()
        new = self.bookmark(2)

        code, output, stderr = self.run_bird_helper("--count", "20", "--since-last", "--update-state")

        self.assertEqual(code, 0)
        self.assertEqual(stderr.splitlines(), PARTIAL)
        self.assertEqual(ids(output), [*new, *numbered(30)[:18]])
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["cutoff_reached"], meta["state_updated"]), ("unfiltered", False, False)
        )
        self.assertEqual(self.state_file.read_bytes(), saved)


class ReviewTest(BirdCase):
    def test_all_reads_the_list_in_one_run(self) -> None:
        self.bird.bookmarks = numbered(45)

        code, output, stderr = self.run_bird_helper("--all")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all")])
        # Two full pages, the last five, and one empty answer that ends the list.
        self.assertEqual(self.bird.pages, 4)
        self.assertEqual(ids(output), numbered(45))
        self.assertTrue(output["meta"]["cutoff_reached"])
        self.assertFalse(self.state_file.exists())

    def test_the_first_review_lists_everything_and_saves_the_newest_fifty(self) -> None:
        self.bird.bookmarks = numbered(120)

        code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(ids(output), numbered(120))
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["cutoff_reached"], meta["state_updated"], meta["fetched_count"]),
            ("no_state", True, True, 120),
        )
        entry = self.state()
        self.assertEqual(entry["anchor_ids"], numbered(120)[:50])
        self.assertEqual(entry["last_seen_id"], numbered(120)[0])
        # The moment fake_bird.post gives, in the form the X API writes it.
        self.assertEqual(entry["last_seen_created_at"], "2026-10-01T00:00:00.000Z")
        self.assertEqual(stat.S_IMODE(self.state_file.stat().st_mode), 0o600)

    def test_the_next_review_lists_only_what_was_bookmarked_since(self) -> None:
        old = self.reviewed(120)
        new = self.bookmark(3)

        code, output, stderr = self.run_bird_helper(*REVIEW, "--pretty")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all")])
        self.assertEqual(ids(output), new)
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["count"], meta["fetched_count"], meta["state_updated"]),
            ("anchor", 3, 123, True),
        )
        self.assertEqual(self.state()["anchor_ids"], [*new, *old[:47]])

    def test_a_review_with_nothing_new_lists_nothing(self) -> None:
        self.reviewed(25)

        code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((code, stderr, output["data"]), (0, "", []))
        self.assertEqual((output["meta"]["count"], output["meta"]["cutoff_mode"]), (0, "anchor"))

    def test_removing_the_newest_reviewed_bookmark_keeps_the_cutoff(self) -> None:
        self.reviewed(25)
        del self.bird.bookmarks[0]
        new = self.bookmark(2)

        _code, output, _stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (new, "anchor"))

    def test_a_reviewed_post_bookmarked_again_is_listed_as_new(self) -> None:
        old = self.reviewed(25)
        again = old[10]
        self.bird.bookmarks.remove(again)
        self.bird.bookmarks.insert(0, again)

        _code, output, _stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), ([again], "anchor"))

    def test_update_state_alone_lists_everything_and_moves_the_cutoff(self) -> None:
        self.reviewed(25)
        new = self.bookmark(2)

        code, output, stderr = self.run_bird_helper("--all", "--update-state")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(len(output["data"]), 27)
        self.assertEqual(
            (output["meta"]["since_last"], output["meta"]["cutoff_mode"], output["meta"]["state_updated"]),
            (False, None, True),
        )
        self.assertEqual(self.state()["anchor_ids"][:2], new)

    def test_max_pages_reaches_bird_and_cannot_confirm_the_cutoff(self) -> None:
        self.reviewed(60)
        saved = self.state_file.read_bytes()
        new = self.bookmark(2)

        code, output, stderr = self.run_bird_helper("--all", "--max-pages", "1", "--since-last", "--update-state")

        self.assertEqual(code, 0)
        self.assertEqual(self.bird.runs, [command("--all", "--max-pages=1")])
        self.assertEqual(stderr.splitlines(), PARTIAL)
        self.assertEqual(ids(output), [*new, *numbered(60)[:18]])
        self.assertEqual((output["meta"]["cutoff_mode"], output["meta"]["state_updated"]), ("unfiltered", False))
        self.assertEqual(self.state_file.read_bytes(), saved)

    def test_creation_time_is_compared_when_every_reviewed_bookmark_is_gone(self) -> None:
        self.reviewed(5)
        self.bird.bookmarks = ["9003", "9002", "9001"]
        # One second after the saved moment, the moment itself, and the day before.
        self.bird.fields = {
            "9003": {"createdAt": "Thu Oct 01 00:00:01 +0000 2026"},
            "9002": {"createdAt": "Thu Oct 01 00:00:00 +0000 2026"},
            "9001": {"createdAt": "Wed Sep 30 23:59:59 +0000 2026"},
        }

        code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual(code, 0)
        self.assertEqual(
            stderr.splitlines(),
            [
                "warning: no saved review anchor is still bookmarked; filtered by post creation time, "
                "which can skip or repeat bookmarks"
            ],
        )
        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (["9003"], "created_at_fallback"))
        self.assertEqual(self.state()["last_seen_created_at"], "2026-10-01T00:00:01.000Z")

    def test_a_folder_has_its_own_cutoff(self) -> None:
        self.reviewed(5)
        whole_list = self.state()
        self.bird.folders["1234567"] = numbered(4, first=3001)

        code, output, stderr = self.run_bird_helper(*REVIEW, "--folder-id", "1234567")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--folder-id=1234567", "--all")])
        self.assertEqual(ids(output), numbered(4, first=3001))
        self.assertEqual({item["folder_id"] for item in output["data"]}, {"1234567"})
        self.assertEqual((output["meta"]["state_scope"], output["meta"]["cutoff_mode"]), ("folder:1234567", "no_state"))
        self.assertEqual(self.state("folder:1234567")["anchor_ids"], numbered(4, first=3001))
        self.assertEqual(self.state(), whole_list)

        self.bird.folders["1234567"].insert(0, "3999")
        _code, output, _stderr = self.run_bird_helper(*REVIEW, "--folder-id", "1234567")
        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (["3999"], "anchor"))

    def test_a_damaged_state_file_stops_the_review_before_bird_runs(self) -> None:
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text('{"scopes": []}', encoding="utf-8")
        self.bird.bookmarks = numbered(3)

        for argv in (REVIEW, ("--all", "--since-last"), ("--count", "5", "--update-state")):
            with self.subTest(argv=argv):
                code, output, stderr = self.run_bird_helper(*argv)

                self.assertEqual((code, output), (1, None))
                self.assertEqual(
                    stderr.splitlines(),
                    [
                        f'error: the review state file {self.state_file} is damaged: "scopes" is not a JSON object',
                        "fix: restore the file from a backup, or move it aside and rerun; "
                        "the next --since-last run then lists every bookmark as new",
                    ],
                )
        self.assertEqual(self.bird.runs, [])
        self.assertEqual(self.state_file.read_text(encoding="utf-8"), '{"scopes": []}')

        # A plain fetch does not read the state, so it still works.
        code, output, stderr = self.run_bird_helper("--count", "2")
        self.assertEqual((code, stderr, len(output["data"])), (0, "", 2))

    def test_bookmarks_are_still_printed_when_the_state_cannot_be_saved(self) -> None:
        self.bird.bookmarks = numbered(3)
        review_state = sys.modules[self.helper.review.__module__]

        with mock.patch.object(review_state, "save_state", side_effect=PermissionError(13, "Permission denied")):
            code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual(code, 1)
        self.assertEqual(ids(output), numbered(3))
        self.assertFalse(output["meta"]["state_updated"])
        self.assertEqual(
            stderr.splitlines(),
            [
                f"error: cannot save the review state file {self.state_file}: Permission denied",
                "fix: make that folder writable or pass --state-file, then rerun; the review "
                "cutoff did not move, so these bookmarks are listed as new again",
            ],
        )


class EarlyStopTest(BirdCase):
    STOP = (*REVIEW, "--stop-after-known", "10")

    def test_a_cutoff_near_the_top_costs_one_run_of_five_pages(self) -> None:
        old = self.reviewed(500)
        new = self.bookmark(3)

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all", "--max-pages=5")])
        self.assertEqual(self.bird.pages, 5)
        self.assertEqual(ids(output), new)
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["cutoff_reached"], meta["stopped_early"], meta["state_updated"]),
            ("early_stop", True, True, True),
        )
        self.assertEqual(meta["fetched_count"], 100)
        self.assertEqual(self.state()["anchor_ids"], [*new, *old[:47]])

    def test_the_next_run_resumes_at_the_cursor_and_reads_twice_as_far(self) -> None:
        self.reviewed(500)
        new = self.bookmark(150)

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            self.bird.runs,
            [command("--all", "--max-pages=5"), command("--all", "--max-pages=10", "--cursor=100")],
        )
        self.assertEqual(self.bird.pages, 15)
        self.assertEqual(ids(output), new)
        self.assertEqual((output["meta"]["cutoff_mode"], output["meta"]["fetched_count"]), ("early_stop", 300))

    def test_runs_grow_to_forty_pages_and_stay_there(self) -> None:
        self.reviewed(1000)
        new = self.bookmark(1600)

        code, output, _stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual(code, 0)
        self.assertEqual(
            [run[4:] for run in self.bird.runs],
            [
                ["--all", "--max-pages=5"],
                ["--all", "--max-pages=10", "--cursor=100"],
                ["--all", "--max-pages=20", "--cursor=300"],
                ["--all", "--max-pages=40", "--cursor=700"],
                ["--all", "--max-pages=40", "--cursor=1500"],
            ],
        )
        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (new, "early_stop"))

    def test_a_reviewed_row_shorter_than_asked_for_reads_to_the_end(self) -> None:
        old = self.reviewed(12)
        del self.bird.bookmarks[2:7]
        new = self.bookmark(3)

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all", "--max-pages=5")])
        self.assertEqual(ids(output), new)
        meta = output["meta"]
        self.assertEqual(
            (meta["cutoff_mode"], meta["cutoff_reached"], meta["stopped_early"], meta["state_updated"]),
            ("anchor", True, False, True),
        )
        self.assertEqual(self.state()["anchor_ids"], [*new, *old[:2], *old[7:], *old[2:7]])

    def test_too_few_saved_bookmarks_to_stop_on_read_the_list_in_one_run(self) -> None:
        self.reviewed(9)
        new = self.bookmark(1)

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all")])
        meta = output["meta"]
        self.assertEqual((ids(output), meta["cutoff_mode"], meta["stopped_early"]), (new, "anchor", False))

    def test_a_first_review_reads_the_list_in_one_run(self) -> None:
        self.bird.bookmarks = numbered(130)

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(self.bird.runs, [command("--all")])
        self.assertEqual((len(output["data"]), output["meta"]["cutoff_mode"]), (130, "no_state"))

    def test_max_pages_caps_the_pages_of_all_runs_together(self) -> None:
        self.reviewed(500)
        saved = self.state_file.read_bytes()
        new = self.bookmark(150)

        code, output, stderr = self.run_bird_helper(*self.STOP, "--max-pages", "7")

        self.assertEqual(code, 0)
        self.assertEqual(
            self.bird.runs,
            [command("--all", "--max-pages=5"), command("--all", "--max-pages=2", "--cursor=100")],
        )
        self.assertEqual(stderr.splitlines(), PARTIAL)
        self.assertEqual(ids(output), new[:140])
        self.assertEqual((output["meta"]["cutoff_mode"], output["meta"]["state_updated"]), ("unfiltered", False))
        self.assertEqual(self.state_file.read_bytes(), saved)

    def test_a_run_that_fails_part_way_prints_nothing_and_keeps_the_state(self) -> None:
        self.reviewed(500)
        saved = self.state_file.read_bytes()
        self.bookmark(150)
        self.bird.intercept = lambda _command: (
            (1, b"", "[err] Failed to fetch bookmarks: HTTP 429: Rate limit exceeded\n")
            if len(self.bird.runs) == 2
            else None
        )

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, output), (1, None))
        self.assertEqual(
            stderr.splitlines(),
            [
                "[err] Failed to fetch bookmarks: HTTP 429: Rate limit exceeded",
                "error: bird exited with status 1",
                "fix: X is limiting requests from this session; wait, then retry, and read fewer "
                "pages with --count, --max-pages or --stop-after-known",
            ],
        )
        self.assertEqual(self.state_file.read_bytes(), saved)

    def test_a_cursor_that_brings_no_further_bookmarks_is_refused(self) -> None:
        self.reviewed(500)
        self.bookmark(150)
        first_page = json.dumps({"tweets": [post(item) for item in self.bird.bookmarks[:20]], "nextCursor": "20"})
        self.bird.intercept = lambda _command: (0, first_page.encode("utf-8"), "")

        code, output, stderr = self.run_bird_helper(*self.STOP)

        self.assertEqual((code, output, len(self.bird.runs)), (1, None, 2))
        self.assertEqual(
            stderr.splitlines(),
            ["error: bird returned no further bookmarks, yet named a cursor for more", FORMAT_FIX],
        )


class BothBackendsTest(BirdMixin, FakeXCase):
    """One saved cutoff serves both helpers, so a review can change backend."""

    def setUp(self) -> None:
        super().setUp()
        self.use_fake_bird()
        self.save_login()
        self.x.access_tokens.add("access-1")

    def bookmark(self, *new: str) -> None:
        for account in (self.x, self.bird):
            account.bookmarks[:0] = new

    def test_a_review_moves_from_the_api_to_bird_and_back(self) -> None:
        self.bookmark(*numbered(160))
        code, output, _stderr = self.fetch(*REVIEW)
        self.assertEqual((code, len(output["data"]), output["meta"]["cutoff_mode"]), (0, 160, "no_state"))

        self.bookmark("2002", "2001")
        code, output, stderr = self.run_bird_helper(*REVIEW)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (["2002", "2001"], "anchor"))
        self.assertEqual(output["meta"]["state_file"], str(self.state_file))

        self.bookmark("3001")
        code, output, _stderr = self.fetch(*REVIEW)
        self.assertEqual((code, ids(output), output["meta"]["cutoff_mode"]), (0, ["3001"], "anchor"))

        code, output, _stderr = self.run_bird_helper(*REVIEW, "--stop-after-known", "10")
        self.assertEqual((code, output["data"], output["meta"]["cutoff_mode"]), (0, [], "early_stop"))

    def test_the_creation_time_one_backend_saved_is_compared_by_the_other(self) -> None:
        self.bookmark(*numbered(3))
        self.fetch(*REVIEW)
        saved = json.loads(self.state_file.read_text(encoding="utf-8"))["scopes"]["all"]["last_seen_created_at"]
        self.assertEqual(saved, "2026-10-01T00:00:00.000Z")

        # Every reviewed bookmark is removed; of the two that remain, one was written later.
        self.bird.bookmarks = ["9002", "9001"]
        self.bird.fields = {"9002": {"createdAt": "Thu Oct 01 00:00:01 +0000 2026"}}
        code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual(code, 0)
        self.assertIn("filtered by post creation time", stderr)
        self.assertEqual((ids(output), output["meta"]["cutoff_mode"]), (["9002"], "created_at_fallback"))


if __name__ == "__main__":
    unittest.main()
