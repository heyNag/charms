"""fetch_bookmarks_bird.py: what it passes to Bird, and what it accepts back.

Most tests answer the helper from fake_bird.FakeBird. The last class runs the
helper as a program with a fake `bird` as the only command on PATH. No test
reaches X or a browser's cookies. test_bird_reviews.py covers the review
cutoff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

import fake_x  # noqa: E402
from fake_bird import post  # noqa: E402
from test_bird_reviews import FORMAT_FIX, REVIEW, SCRIPT, BirdCase, command, ids, numbered  # noqa: E402


class OptionsTest(BirdCase):
    def test_the_session_options_reach_bird_in_order(self) -> None:
        self.bird.bookmarks = numbered(3)

        session = ("--cookie-source", "firefox", "--cookie-source", "chrome", "--chrome-profile", "Profile 2")
        profiles = ("--chrome-profile-dir=-odd/path", "--firefox-profile", "work")
        code, _output, stderr = self.run_bird_helper(*session, *profiles, "--bird-timeout", "30", "--count", "2")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            self.bird.runs,
            [
                command(
                    "--cookie-source=firefox",
                    "--cookie-source=chrome",
                    "--chrome-profile=Profile 2",
                    "--chrome-profile-dir=-odd/path",
                    "--firefox-profile=work",
                    "--count=2",
                )
            ],
        )
        self.assertEqual(self.bird.timeouts, [30.0])

    def test_session_cookies_are_refused_and_never_repeated(self) -> None:
        self.bird.bookmarks = numbered(3)

        for argv in (
            ("--auth-token", "cookie-value-1"),
            ("--ct0=cookie-value-2", "--count", "2"),
            ("--auth-token", "cookie-value-1", "--ct0", "cookie-value-2", *REVIEW),
        ):
            with self.subTest(argv=argv):
                code, output, stderr = self.run_bird_helper(*argv)

                self.assertEqual((code, output), (2, None))
                self.assertEqual(
                    stderr.splitlines(),
                    [
                        "error: --auth-token and --ct0 are not accepted, because a cookie in a command line "
                        "is visible in the process list and saved in shell history",
                        "fix: let Bird read the browser session (check it with `bird check --plain`), and sign "
                        "out of x.com in that browser to end the session if this command line may have been recorded",
                    ],
                )
                self.assertNotIn("cookie-value", stderr)
        self.assertEqual(self.bird.runs, [])
        self.assertFalse(self.state_file.exists())

    def test_options_that_cannot_work_stop_before_bird_runs(self) -> None:
        self.bird.bookmarks = numbered(3)
        needs_all = "error: --stop-after-known works only with --all --since-last"
        cases = [
            (("--count", "0"), ["error: --count must be at least 1"]),
            (("--max-pages", "2"), ["error: --max-pages works only with --all"]),
            (("--all", "--max-pages", "0"), ["error: --max-pages must be at least 1"]),
            (
                ("--folder-id", "../1"),
                [
                    "error: --folder-id must be a folder's numeric ID of 1 to 19 digits",
                    "fix: pass the number at the end of the folder's address on x.com, "
                    "https://x.com/i/bookmarks/NUMBER",
                ],
            ),
            (("--since-last", "--stop-after-known", "10"), [needs_all]),
            (("--all", "--stop-after-known", "10"), [needs_all]),
            (
                ("--all", "--since-last", "--stop-after-known", "4"),
                [
                    "error: --stop-after-known must be between 5 and 50: a shorter row is too easy to "
                    "mistake for the cutoff, and only 50 reviewed bookmarks are saved"
                ],
            ),
        ]
        for value in ("0", "-5", "nan", "inf", "86401"):
            cases.append(
                (("--bird-timeout", value), ["error: --bird-timeout must be more than 0 and at most 86400 seconds"])
            )
        for argv, lines in cases:
            with self.subTest(argv=argv):
                code, output, stderr = self.run_bird_helper(*argv)

                self.assertEqual((code, output), (2, None))
                self.assertEqual(stderr.splitlines(), lines)
        self.assertEqual(self.bird.runs, [])

    def test_a_folder_id_bird_refuses_is_reported_with_birds_words(self) -> None:
        code, output, stderr = self.run_bird_helper("--folder-id", "123")

        self.assertEqual((code, output), (1, None))
        self.assertEqual(self.bird.runs, [command("--folder-id=123", "--count=20")])
        self.assertEqual(
            stderr.splitlines()[:2],
            [
                "[err] Invalid --folder-id. Expected numeric ID or https://x.com/i/bookmarks/<id>.",
                "error: bird exited with status 1",
            ],
        )

    def test_a_missing_bird_is_reported_with_a_fix(self) -> None:
        with mock.patch.object(self.helper, "find_bird", return_value=None):
            code, output, stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((code, output), (127, None))
        self.assertEqual(
            stderr.splitlines(),
            [
                "error: bird is not installed",
                "fix: install Bird from https://bird.fast/ or use your managed toolchain",
            ],
        )
        self.assertEqual(self.bird.runs, [])


class PostFieldsTest(BirdCase):
    def fetch_one(self, **fields: object) -> dict:
        self.bird.bookmarks = ["1900000000000000001"]
        self.bird.fields = {"1900000000000000001": fields}
        code, output, stderr = self.run_bird_helper("--count", "5")
        self.assertEqual((code, stderr), (0, ""))
        (item,) = output["data"]
        return item

    def test_a_post_keeps_birds_fields_and_gains_the_ones_the_api_helper_gives(self) -> None:
        media = [{"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg", "width": 10, "height": 20}]

        item = self.fetch_one(text="café \U0001f426", likeCount=12, media=media, somethingNew={"kept": True})

        self.assertEqual(
            item,
            {
                **post("1900000000000000001"),
                "text": "café \U0001f426",
                "likeCount": 12,
                "media": media,
                "somethingNew": {"kept": True},
                "url": "https://x.com/author/status/1900000000000000001",
                "created_at": "2026-10-01T00:00:00.000Z",
                "source": "bird",
            },
        )
        # The same post through the X API helper carries the same time, in the same form.
        self.assertEqual(item["created_at"], fake_x.post("1")["created_at"])

    def test_a_handle_that_is_not_one_stays_out_of_the_url(self) -> None:
        for username in ("../i/flow/login", "a b", "x" * 16, "", None, 7):
            with self.subTest(username=username):
                item = self.fetch_one(author={"username": username, "name": "Name"})

                self.assertEqual(item["url"], "https://x.com/i/web/status/1900000000000000001")

    def test_a_post_whose_id_is_not_a_number_gets_no_url(self) -> None:
        self.bird.intercept = lambda _command: (0, json.dumps([post("abc/../def")]).encode("utf-8"), "")

        code, output, _stderr = self.run_bird_helper("--count", "5")

        self.assertEqual(code, 0)
        self.assertNotIn("url", output["data"][0])

    def test_a_quoted_post_gets_its_url_and_time_too(self) -> None:
        inner = post("1700000000000000003", createdAt="Sat Feb 03 04:05:06 +0000 2024")
        quoted = post(
            "1800000000000000002",
            author={"username": "quoted_1", "name": "Quoted"},
            createdAt="Mon Jan 06 09:08:07 +0000 2025",
            quotedTweet=inner,
        )

        item = self.fetch_one(quotedTweet=quoted)

        self.assertEqual(item["quotedTweet"]["url"], "https://x.com/quoted_1/status/1800000000000000002")
        self.assertEqual(item["quotedTweet"]["created_at"], "2025-01-06T09:08:07.000Z")
        self.assertEqual(
            item["quotedTweet"]["quotedTweet"]["url"], "https://x.com/author/status/1700000000000000003"
        )
        self.assertEqual(item["quotedTweet"]["quotedTweet"]["created_at"], "2024-02-03T04:05:06.000Z")
        self.assertNotIn("source", item["quotedTweet"])

    def test_creation_times_are_written_as_the_x_api_writes_them(self) -> None:
        for bird_time, api_time in (
            ("Wed Oct 10 20:19:24 +0000 2018", "2018-10-10T20:19:24.000Z"),
            ("Tue Mar 21 20:50:14 +0000 2006", "2006-03-21T20:50:14.000Z"),
            ("Thu Feb 29 23:59:59 +0000 2024", "2024-02-29T23:59:59.000Z"),
            ("Fri Jan 1 00:00:00 +0000 2027", "2027-01-01T00:00:00.000Z"),
            ("thu oct 01 05:30:00 +0530 2026", "2026-10-01T00:00:00.000Z"),
            ("Wed Sep 30 16:00:00 -0800 2026", "2026-10-01T00:00:00.000Z"),
            ("  Thu Oct 01 00:00:00 +0000 2026\n", "2026-10-01T00:00:00.000Z"),
        ):
            with self.subTest(bird_time=bird_time):
                self.assertEqual(self.helper.api_time(bird_time), api_time)

    def test_a_time_x_does_not_write_gives_no_created_at(self) -> None:
        for value in (
            "2026-10-01T00:00:00.000Z",
            "yesterday",
            "",
            "Thu Oct 32 00:00:00 +0000 2026",
            "Thu Foo 01 00:00:00 +0000 2026",
            "Thu Oct 01 24:00:00 +0000 2026",
            "Thu Feb 29 00:00:00 +0000 2026",
            "Thu Oct 01 00:00:00 +0000 0000",
            "Thu Oct 01 00:00:00 UTC 2026",
            None,
            1790000000,
        ):
            with self.subTest(value=value):
                self.assertIsNone(self.helper.api_time(value))
                self.assertNotIn("created_at", self.fetch_one(createdAt=value))


class BirdOutputTest(BirdCase):
    def answer(self, stdout: bytes, stderr: str = "", status: int = 0) -> None:
        self.bird.intercept = lambda _command: (status, stdout, stderr)

    def test_output_the_helper_cannot_read_is_refused_and_the_state_left_alone(self) -> None:
        paging = 'not the object with a "tweets" list and a "nextCursor" that --all gives'
        not_json = "bird did not print valid JSON: Expecting value: line 1 column 1 (char 0)"
        not_list = "not the list of posts that --count gives"
        window = ("--count", "5", "--since-last", "--update-state")
        cases = [
            (window, b"", not_json),
            (window, b"No bookmarks found.\n", not_json),
            (
                window,
                b"\xff\xfe[]",
                "bird did not print valid JSON: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte",
            ),
            (window, b'{"tweets": [], "nextCursor": null}', f"bird printed an object, {not_list}"),
            (window, b'"text"', f"bird printed text, {not_list}"),
            (window, b"null", f"bird printed null, {not_list}"),
            (window, b"true", f"bird printed true or false, {not_list}"),
            (window, b"12", f"bird printed a number, {not_list}"),
            (window, b'[{"id": "1"}, "x"]', "post 2 of bird's output is text, not an object"),
            (window, b'[{"text": "no id"}]', 'post 1 of bird\'s output has no "id" text'),
            (window, b'[{"id": 5}]', 'post 1 of bird\'s output has no "id" text'),
            (window, b'[{"id": ""}]', 'post 1 of bird\'s output has no "id" text'),
            (REVIEW, b"[]", f"bird printed a list, {paging}"),
            (REVIEW, b'{"tweets": []}', f"bird printed an object, {paging}"),
            (REVIEW, b'{"tweets": {}, "nextCursor": null}', f"bird printed an object, {paging}"),
            (REVIEW, b'{"nextCursor": null}', f"bird printed an object, {paging}"),
            (REVIEW, b'{"tweets": [], "nextCursor": 5}', 'the "nextCursor" bird printed is a number, not text or null'),
            (REVIEW, b'{"tweets": [null], "nextCursor": null}', "post 1 of bird's output is null, not an object"),
        ]
        for argv, stdout, message in cases:
            with self.subTest(stdout=stdout[:40]):
                self.answer(stdout)

                code, output, stderr = self.run_bird_helper(*argv)

                self.assertEqual((code, output), (1, None))
                self.assertEqual(stderr.splitlines(), [f"error: {message}", FORMAT_FIX])
        self.assertFalse(self.state_file.exists())

    def test_json_nested_too_deep_to_read_is_refused(self) -> None:
        self.answer(b"[" * 100_000)

        code, output, stderr = self.run_bird_helper("--count", "5")

        self.assertEqual((code, output), (1, None))
        self.assertRegex(stderr, r"\Aerror: bird did not print valid JSON: .*recursion")
        self.assertEqual(stderr.splitlines()[1:], [FORMAT_FIX])

    def test_an_empty_list_is_a_review_with_nothing_to_show(self) -> None:
        nothing_paged = b'{\n  "tweets": [],\n  "nextCursor": null\n}\n'
        for argv, stdout in ((("--count", "5"), b"[]\n"), (("--all",), nothing_paged)):
            with self.subTest(argv=argv):
                self.answer(stdout)

                code, output, stderr = self.run_bird_helper(*argv, "--since-last", "--update-state")

                self.assertEqual((code, stderr, output["data"]), (0, "", []))
                self.assertEqual(
                    (output["meta"]["cutoff_reached"], output["meta"]["state_updated"]), (True, False)
                )
        self.assertFalse(self.state_file.exists())

    def test_an_empty_cursor_ends_the_list_like_null(self) -> None:
        self.answer(json.dumps({"tweets": [post("1")], "nextCursor": ""}).encode("utf-8"))

        code, output, _stderr = self.run_bird_helper(*REVIEW)

        self.assertEqual((code, output["meta"]["cutoff_reached"], output["meta"]["state_updated"]), (0, True, True))

    def test_a_post_printed_twice_is_listed_once_in_its_newer_place(self) -> None:
        self.answer(json.dumps([post("3"), post("2"), post("3", text="again"), post("1")]).encode("utf-8"))

        code, output, _stderr = self.run_bird_helper("--count", "4")

        self.assertEqual(code, 0)
        self.assertEqual(
            [(item["id"], item["text"]) for item in output["data"]],
            [("3", "post 3"), ("2", "post 2"), ("1", "post 1")],
        )
        self.assertEqual((output["meta"]["count"], output["meta"]["fetched_count"]), (3, 3))
        # Bird returned as many posts as were asked for, so the list may go on.
        self.assertFalse(output["meta"]["cutoff_reached"])

    def test_birds_warnings_are_passed_on(self) -> None:
        self.bird.bookmarks = numbered(2)
        self.bird.stderr = "[warn] Failed to parse config at /home/me/.config/bird/config.json5: JSON5: bad"

        code, output, stderr = self.run_bird_helper("--count", "5")

        self.assertEqual((code, len(output["data"])), (0, 2))
        self.assertEqual(stderr, self.bird.stderr + "\n")

    def test_a_failed_bird_is_reported_with_the_fix_for_what_it_said(self) -> None:
        session = (
            "fix: check the browser session with `bird check --plain`; if it is signed out, "
            "sign in to x.com (scripts/open_x_login.sh opens it) and retry"
        )
        cases = [
            ("[warn] Missing auth_token - provide via --auth-token\n[err] Missing required credentials\n", 1, session),
            ("[err] Failed to fetch bookmarks: HTTP 401: Could not authenticate you\n", 1, session),
            ("", 3, session),
            (
                "error: unknown option '--all'\n",
                1,
                "fix: this helper needs Bird 0.6.0 or newer, which pages bookmarks with --all, "
                "--max-pages and --cursor; compare `bird --version`",
            ),
            (
                "[err] Failed to fetch bookmarks: HTTP 429: Rate limit exceeded\n",
                1,
                "fix: X is limiting requests from this session; wait, then retry, and read fewer "
                "pages with --count, --max-pages or --stop-after-known",
            ),
        ]
        for said, status, fix in cases:
            with self.subTest(said=said):
                # Whatever a failed Bird printed is not bookmarks, and is not read.
                self.answer(b'[{"id": "1"}]', said, status)

                code, output, stderr = self.run_bird_helper(*REVIEW)

                self.assertEqual((code, output), (1, None))
                self.assertEqual(
                    stderr.splitlines(), [*said.splitlines(), f"error: bird exited with status {status}", fix]
                )
        self.assertFalse(self.state_file.exists())


FAKE_BIRD = """#!/bin/sh
# Notes its arguments, one to a line, then does what the test asked.
for argument in "$@"; do
  printf '%s\\n' "$argument" >> "$FAKE_BIRD_LOG"
done
if [ -n "${FAKE_BIRD_STDERR:-}" ]; then
  printf '%s\\n' "$FAKE_BIRD_STDERR" >&2
fi
if [ -n "${FAKE_BIRD_SLEEP:-}" ]; then
  exec /bin/sleep "$FAKE_BIRD_SLEEP"
fi
if [ -n "${FAKE_BIRD_OUTPUT:-}" ]; then
  /bin/cat "$FAKE_BIRD_OUTPUT"
fi
exit "${FAKE_BIRD_STATUS:-0}"
"""


class BirdProgramTest(unittest.TestCase):
    """The helper as a program, with a fake `bird` as the only command on PATH."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "bird.log"
        self.state_file = self.tmp / "state" / "state.json"

    def install_bird(self, script: str = FAKE_BIRD) -> None:
        bird = self.bin / "bird"
        bird.write_text(script, encoding="utf-8")
        bird.chmod(0o755)

    def answer(self, value: object) -> str:
        path = self.tmp / "answer.json"
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return str(path)

    def run_helper(self, *argv: str, typed: str | None = None, **environment: str) -> subprocess.CompletedProcess:
        """Run the helper; `typed` is what waits on its standard input, which is otherwise empty."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            env={
                "PATH": str(self.bin),
                "HOME": str(self.tmp),
                "X_BOOKMARKS_STATE_FILE": str(self.state_file),
                "PYTHONDONTWRITEBYTECODE": "1",
                "FAKE_BIRD_LOG": str(self.log),
                **environment,
            },
            **({"stdin": subprocess.DEVNULL} if typed is None else {"input": typed}),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_the_helper_can_be_run_directly(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertEqual(SCRIPT.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_a_review_runs_bird_and_saves_the_cutoff(self) -> None:
        self.install_bird()
        answer = self.answer({"tweets": [post("1002"), post("1001")], "nextCursor": None})

        result = self.run_helper(*REVIEW, "--cookie-source", "firefox", FAKE_BIRD_OUTPUT=answer)

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines(),
            ["bookmarks", "--json", "--plain", "--cookie-source=firefox", "--all"],
        )
        output = json.loads(result.stdout)
        self.assertEqual(ids(output), ["1002", "1001"])
        self.assertEqual(output["data"][0]["url"], "https://x.com/author/status/1002")
        self.assertEqual((output["meta"]["cutoff_mode"], output["meta"]["state_updated"]), ("no_state", True))
        saved = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["scopes"]["all"]["anchor_ids"], ["1002", "1001"])

    def test_a_missing_bird_is_reported_with_a_fix(self) -> None:
        result = self.run_helper("--count", "5")

        self.assertEqual((result.returncode, result.stdout), (127, ""))
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "error: bird is not installed",
                "fix: install Bird from https://bird.fast/ or use your managed toolchain",
            ],
        )

    def test_birds_failure_and_message_are_passed_on(self) -> None:
        self.install_bird()

        result = self.run_helper(
            "--count",
            "5",
            FAKE_BIRD_STATUS="1",
            FAKE_BIRD_STDERR="[err] Failed to fetch bookmarks: HTTP 401: Could not authenticate you",
            FAKE_BIRD_OUTPUT=self.answer([post("1")]),
        )

        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "[err] Failed to fetch bookmarks: HTTP 401: Could not authenticate you",
                "error: bird exited with status 1",
                "fix: check the browser session with `bird check --plain`; if it is signed out, "
                "sign in to x.com (scripts/open_x_login.sh opens it) and retry",
            ],
        )

    def test_a_bird_that_does_not_finish_is_stopped(self) -> None:
        self.install_bird()
        started = time.monotonic()

        result = self.run_helper(
            *REVIEW, "--bird-timeout", "0.5", FAKE_BIRD_SLEEP="30", FAKE_BIRD_STDERR="[warn] waiting for the keychain"
        )

        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertEqual(
            result.stderr.splitlines(),
            [
                "[warn] waiting for the keychain",
                "error: bird did not finish within 0.5 seconds",
                "fix: raise --bird-timeout, or read fewer bookmarks with --count or --max-pages",
            ],
        )
        self.assertFalse(self.state_file.exists())

    def test_a_bird_that_cannot_be_started_is_reported(self) -> None:
        self.install_bird("#!/nonexistent/interpreter\n")

        result = self.run_helper("--count", "5")

        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertEqual(
            result.stderr.splitlines(), [f"error: cannot run {self.bin / 'bird'}: No such file or directory"]
        )

    def test_bird_gets_no_standard_input(self) -> None:
        # This bird fails if it can read a line. The helper has one waiting, and must not pass it on.
        self.install_bird('#!/bin/sh\nread -r line && exit 9\nprintf "[]"\n')

        result = self.run_helper("--count", "5", typed="a line for bird\n")

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(json.loads(result.stdout)["data"], [])


if __name__ == "__main__":
    unittest.main()
