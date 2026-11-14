"""doctor.py --prune lists old run folders and deletes only what it recognises."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))
sys.path.insert(0, str(TESTS_DIR))

import doctor  # noqa: E402
import network_guard  # noqa: E402
import prune_runs  # noqa: E402
import watch  # noqa: E402

HOUR = 3600
DAY = 24 * HOUR
NOW = time.time()


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def run_name(source: str, age: float, slug: str = "video", suffix: str = "") -> str:
    """A run folder name as watch.py would have made it `age` seconds ago."""
    stamp = datetime.fromtimestamp(NOW - age).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slug}-{hashlib.sha1(source.encode('utf-8')).hexdigest()[:8]}{suffix}"


def age_tree(folder: Path, age: float) -> None:
    """Make everything in a folder look last changed `age` seconds ago."""
    moment = NOW - age
    for current, folders, files in os.walk(folder):
        for name in (*folders, *files):
            os.utime(os.path.join(current, name), (moment, moment), follow_symlinks=False)
    os.utime(folder, (moment, moment))


class PruneCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "runs"
        self.root.mkdir()

    def make_run(
        self, source: str, age: float, *, record: str | None = "metadata.json",
        files: dict[str, bytes] | None = None, suffix: str = "",
    ) -> Path:
        folder = self.root / run_name(source, age, suffix=suffix)
        folder.mkdir()
        if record == "metadata.json":
            watch.write_json(folder / record, {"engine": "local", "source": source})
        elif record == "batch.json":
            watch.write_json(folder / record, {
                "schema_version": 1, "engine": "local", "source": source, "videos": []})
        if files is None:
            files = {"media/video.mp4": b"v" * 2048, "report.md": b"report"}
        for name, content in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        age_tree(folder, age)
        return folder


class AgeTests(unittest.TestCase):
    def test_ages_take_hours_days_and_weeks(self) -> None:
        self.assertEqual(prune_runs.parse_age("12h"), 12 * HOUR)
        self.assertEqual(prune_runs.parse_age("7d"), 7 * DAY)
        self.assertEqual(prune_runs.parse_age(" 2W "), 14 * DAY)
        self.assertEqual(prune_runs.parse_age(prune_runs.DEFAULT_AGE), 7 * DAY)

    def test_other_forms_are_rejected(self) -> None:
        for value in ("", "7", "d", "7m", "1.5d", "-1d", "7 d", "7days", "week"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "12h, 7d or 2w"):
                prune_runs.parse_age(value)

    def test_less_than_an_hour_is_rejected(self) -> None:
        for value in ("0h", "0d", "0w"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "at least 1h"):
                prune_runs.parse_age(value)
        self.assertEqual(prune_runs.parse_age("1h"), HOUR)


class RecognitionTests(PruneCase):
    def test_folders_made_by_watch_are_recognised(self) -> None:
        source = "https://www.youtube.com/watch?v=fixture"
        with mock.patch.object(watch, "safe_run_id", return_value=run_name(source, 0)):
            first = watch.create_run_dir(self.root, source)
            second = watch.create_run_dir(self.root, source)
        self.assertTrue(second.name.endswith("-01"))
        for folder in (first, second):
            self.assertEqual(prune_runs.run_kind(folder), "unfinished")
            watch.write_json(folder / "metadata.json", {"engine": "local", "source": source})
            self.assertEqual(prune_runs.run_kind(folder), "recorded")

    def test_the_name_watch_generates_today_is_recognised(self) -> None:
        for source in ("https://example.com/a/b.mp4?x=1", "/Users/me/Screen Recording 1.mov", "…"):
            with self.subTest(source=source):
                folder = watch.create_run_dir(self.root, source)
                watch.write_json(folder / "metadata.json", {"engine": "gemini", "source": source})
                self.assertEqual(prune_runs.run_kind(folder), "recorded")

    def test_a_batch_record_counts(self) -> None:
        folder = self.make_run("/recordings", DAY, record="batch.json", files={"videos/x/report.md": b"r"})
        self.assertEqual(prune_runs.run_kind(folder), "recorded")

    def test_a_recorded_run_may_hold_other_files(self) -> None:
        folder = self.make_run("/a.mp4", DAY, files={"notes from the agent.md": b"n", "crops/1.png": b"p"})
        self.assertEqual(prune_runs.run_kind(folder), "recorded")

    def test_a_run_without_its_record_must_hold_only_run_artifacts(self) -> None:
        leftovers = self.make_run("/a.mp4", DAY, record=None, files={
            "media/video.mp4": b"v", "audio.mp3": b"a", "frames/frame_0001.jpg": b"f"})
        self.assertEqual(prune_runs.run_kind(leftovers), "unfinished")
        empty = self.make_run("/empty.mp4", DAY, record=None, files={})
        self.assertEqual(prune_runs.run_kind(empty), "unfinished")
        for name in ("thesis.docx", "media.txt", "report.md/inner"):
            with self.subTest(name=name):
                other = self.make_run(f"/{name}", DAY, record=None, files={name: b"mine"})
                self.assertIsNone(prune_runs.run_kind(other))

    def test_a_record_for_another_source_does_not_count(self) -> None:
        folder = self.root / run_name("/a.mp4", DAY)
        folder.mkdir()
        watch.write_json(folder / "metadata.json", {"engine": "local", "source": "/other.mp4"})
        (folder / "keep.txt").write_text("mine", encoding="utf-8")
        self.assertIsNone(prune_runs.run_kind(folder))

    def test_unreadable_records_do_not_count(self) -> None:
        for content in (b"{not json", b"[]", b'{"source": 5}', b"\xff\xfe"):
            with self.subTest(content=content):
                folder = self.make_run(f"/{content!r}", DAY, record=None, files={
                    "metadata.json": content, "keep.txt": b"mine"})
                self.assertIsNone(prune_runs.run_kind(folder))

    def test_other_names_are_never_runs(self) -> None:
        digest = hashlib.sha1(b"/a.mp4").hexdigest()[:8]
        for name in ("notes", "20261114-101500-video", f"20261399-101500-video-{digest}",
                     f"2026114-101500-video-{digest}", f"20261114-101500-{digest}",
                     f"20261114-101500-video-{digest.upper()}", f"x20261114-101500-video-{digest}",
                     f"20261114-101500-video-{digest}-1", f"20261114-101500-video-{digest}.bak"):
            with self.subTest(name=name):
                folder = self.root / name
                folder.mkdir()
                watch.write_json(folder / "metadata.json", {"engine": "local", "source": "/a.mp4"})
                self.assertIsNone(prune_runs.run_kind(folder))

    def test_links_and_files_are_never_runs(self) -> None:
        real = self.make_run("/a.mp4", DAY)
        link = self.root / run_name("/a.mp4", 2 * DAY)
        link.symlink_to(real, target_is_directory=True)
        self.assertIsNone(prune_runs.run_kind(link))
        plain = self.root / run_name("/b.mp4", DAY)
        plain.write_text("a file", encoding="utf-8")
        self.assertIsNone(prune_runs.run_kind(plain))
        linked_inside = self.make_run("/c.mp4", DAY, record=None, files={})
        (linked_inside / "media").symlink_to(real, target_is_directory=True)
        self.assertIsNone(prune_runs.run_kind(linked_inside))


class PruneTests(PruneCase):
    def test_a_dry_run_lists_old_runs_and_deletes_nothing(self) -> None:
        old = self.make_run("/old.mp4", 9 * DAY)
        unfinished = self.make_run("/stopped.mp4", 30 * DAY, record=None, files={"media/part.mp4": b"p" * 100})
        recent = self.make_run("/recent.mp4", 2 * DAY)
        (self.root / "my notes").mkdir()
        (self.root / "list.txt").write_text("mine", encoding="utf-8")

        result = prune_runs.prune(self.root, 7 * DAY, now=NOW)

        self.assertEqual(
            [(run["name"], run["kind"], run["removed"]) for run in result["runs"]],
            sorted([(old.name, "recorded", False), (unfinished.name, "unfinished", False)]),
        )
        by_name = {run["name"]: run for run in result["runs"]}
        self.assertEqual(by_name[unfinished.name]["size_bytes"], 100)
        self.assertGreater(by_name[old.name]["size_bytes"], 2048)
        self.assertEqual(by_name[old.name]["age_seconds"], 9 * DAY)
        self.assertEqual((result["kept_newer"], result["not_runs"]), (1, 2))
        self.assertEqual((result["delete"], result["ok"], result["error"]), (False, True, None))
        for path in (old, unfinished, recent, self.root / "my notes", self.root / "list.txt"):
            self.assertTrue(path.exists(), path)
        text = prune_runs.report(result)
        self.assertIn(f"- {old.name}: ", text)
        self.assertIn("unchanged for 9 days", text)
        self.assertIn(f"- {unfinished.name}: 0.0 MB, unchanged for 30 days, unfinished run", text)
        self.assertIn("2 run folder(s), 0.0 MB. Nothing was deleted. Run the command again with --delete", text)
        self.assertIn("Left alone: 1 newer run folder(s) and 2 item(s) that are not watch-video runs.", text)
        self.assertNotIn(recent.name, text)

    def test_delete_removes_only_the_old_runs(self) -> None:
        old = self.make_run("/old.mp4", 9 * DAY)
        batch = self.make_run("/recordings", 8 * DAY, record="batch.json", files={"videos/x/media/v.mp4": b"v"})
        recent = self.make_run("/recent.mp4", 6 * DAY)
        notes = self.root / "my notes"
        notes.mkdir()
        (notes / "keep.txt").write_text("mine", encoding="utf-8")

        result = prune_runs.prune(self.root, 7 * DAY, delete=True, now=NOW)

        self.assertEqual([run["removed"] for run in result["runs"]], [True, True])
        self.assertTrue(result["ok"])
        self.assertFalse(old.exists())
        self.assertFalse(batch.exists())
        self.assertTrue(recent.is_dir())
        self.assertEqual((notes / "keep.txt").read_text(encoding="utf-8"), "mine")
        text = prune_runs.report(result)
        self.assertIn(f"- removed {old.name}: ", text)
        self.assertIn("Removed 2 run folder(s), ", text)
        self.assertNotIn("Nothing was deleted", text)

    def test_age_counts_from_the_latest_change_inside(self) -> None:
        touched = self.make_run("/touched.mp4", 30 * DAY)
        os.utime(touched / "media" / "video.mp4", (NOW - HOUR, NOW - HOUR))
        new_name = self.make_run("/clock.mp4", 2 * DAY)
        age_tree(new_name, 30 * DAY)  # an old modification time, but it started two days ago

        result = prune_runs.prune(self.root, 7 * DAY, delete=True, now=NOW)

        self.assertEqual((result["runs"], result["kept_newer"]), ([], 2))
        self.assertTrue(touched.is_dir())
        self.assertTrue(new_name.is_dir())

    def test_links_inside_a_run_are_removed_without_touching_their_targets(self) -> None:
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("mine", encoding="utf-8")
        run = self.make_run("/linked.mp4", 9 * DAY)
        (run / "media" / "link").symlink_to(outside, target_is_directory=True)
        age_tree(run, 9 * DAY)

        result = prune_runs.prune(self.root, 7 * DAY, delete=True, now=NOW)

        self.assertEqual([entry["removed"] for entry in result["runs"]], [True])
        self.assertFalse(run.exists())
        self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "mine")

    def test_a_folder_that_fails_to_delete_is_reported_and_the_rest_continue(self) -> None:
        stuck = self.make_run("/a-stuck.mp4", 9 * DAY)
        gone = self.make_run("/b-gone.mp4", 9 * DAY)
        real_rmtree = prune_runs.shutil.rmtree

        def rmtree(path, *args, **kwargs):
            if Path(path) == stuck:
                raise PermissionError(13, "Permission denied")
            return real_rmtree(path, *args, **kwargs)

        with mock.patch.object(prune_runs.shutil, "rmtree", side_effect=rmtree):
            result = prune_runs.prune(self.root, 7 * DAY, delete=True, now=NOW)

        by_name = {run["name"]: run for run in result["runs"]}
        self.assertEqual((by_name[stuck.name]["removed"], by_name[stuck.name]["error"]), (False, "Permission denied"))
        self.assertTrue(by_name[gone.name]["removed"])
        self.assertFalse(result["ok"])
        self.assertTrue(stuck.is_dir())
        self.assertFalse(gone.exists())
        text = prune_runs.report(result)
        self.assertIn(f"- could not remove {stuck.name}: ", text)
        self.assertIn("Removed 1 run folder(s), ", text)
        self.assertIn("1 could not be removed.", text)

    def test_a_folder_that_changed_since_the_listing_is_left_alone(self) -> None:
        run = self.make_run("/swapped.mp4", 9 * DAY, record=None, files={"media/video.mp4": b"v"})
        real_find = prune_runs.find_runs

        def find_then_change(*args, **kwargs):
            found = real_find(*args, **kwargs)
            (run / "thesis.docx").write_text("mine", encoding="utf-8")
            return found

        with mock.patch.object(prune_runs, "find_runs", side_effect=find_then_change):
            result = prune_runs.prune(self.root, 7 * DAY, delete=True, now=NOW)

        self.assertEqual(result["runs"][0]["error"], "no longer looks like a run folder")
        self.assertFalse(result["runs"][0]["removed"])
        self.assertFalse(result["ok"])
        self.assertEqual((run / "thesis.docx").read_text(encoding="utf-8"), "mine")

    def test_a_missing_or_empty_root_is_not_an_error(self) -> None:
        for root in (self.root / "missing", self.root):
            with self.subTest(root=root.name):
                result = prune_runs.prune(root, 7 * DAY, delete=True, now=NOW)
                self.assertEqual((result["runs"], result["ok"]), ([], True))
                self.assertIn("- none", prune_runs.report(result))

    def test_sizes_and_ages_read_naturally(self) -> None:
        self.assertEqual(prune_runs.size_text(0), "0.0 MB")
        self.assertEqual(prune_runs.size_text(5 * 1024 * 1024 + 512 * 1024), "5.5 MB")
        self.assertEqual(prune_runs.size_text(312 * 1024 * 1024), "312 MB")
        self.assertEqual(prune_runs.size_text(1536 * 1024 * 1024), "1.5 GB")
        self.assertEqual(prune_runs.age_text(HOUR), "1 hour")
        self.assertEqual(prune_runs.age_text(47 * HOUR), "47 hours")
        self.assertEqual(prune_runs.age_text(7 * DAY), "7 days")
        self.assertEqual(prune_runs.age_text(14 * DAY), "14 days")


class DoctorCliTests(PruneCase):
    def cli(self, *args: str, env: dict[str, str] | None = None):
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["doctor.py", *args]), \
                mock.patch.dict(os.environ, env or {}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = doctor.main()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_prune_is_a_dry_run_until_delete_is_given(self) -> None:
        old = self.make_run("/old.mp4", 9 * DAY)
        recent = self.make_run("/recent.mp4", 2 * DAY)

        code, output, errors = self.cli("--prune", "--out-dir", str(self.root))
        self.assertEqual((code, errors), (0, ""))
        self.assertIn(f"unchanged for 7 days:\n\n- {old.name}: ", output)
        self.assertIn("Nothing was deleted.", output)
        self.assertTrue(old.is_dir())

        code, output, errors = self.cli("--prune", "--delete", "--out-dir", str(self.root))
        self.assertEqual((code, errors), (0, ""))
        self.assertIn(f"- removed {old.name}: ", output)
        self.assertFalse(old.exists())
        self.assertTrue(recent.is_dir())

    def test_older_than_and_json(self) -> None:
        self.make_run("/old.mp4", 9 * DAY)
        recent = self.make_run("/recent.mp4", 2 * DAY)

        code, output, _ = self.cli("--prune", "--older-than", "1d", "--json", "--out-dir", str(self.root))
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(result["older_than_seconds"], DAY)
        self.assertEqual(result["root"], str(self.root.resolve()))
        self.assertEqual(len(result["runs"]), 2)
        self.assertFalse(result["delete"])
        self.assertTrue(recent.is_dir())

    def test_the_default_root_is_the_configured_run_directory(self) -> None:
        old = self.make_run("/old.mp4", 9 * DAY)
        code, output, _ = self.cli("--prune", "--delete", env={"WATCH_VIDEO_RUNS_DIR": str(self.root)})
        self.assertEqual(code, 0)
        self.assertIn(f"- removed {old.name}: ", output)
        self.assertFalse(old.exists())

    def test_a_failed_removal_exits_nonzero(self) -> None:
        self.make_run("/old.mp4", 9 * DAY)
        with mock.patch.object(prune_runs.shutil, "rmtree", side_effect=PermissionError(13, "Permission denied")):
            code, output, _ = self.cli("--prune", "--delete", "--out-dir", str(self.root))
        self.assertEqual(code, 1)
        self.assertIn("could not remove", output)

    def test_bad_ages_and_mixed_modes_are_usage_errors(self) -> None:
        old = self.make_run("/old.mp4", 9 * DAY)
        for arguments, message in (
            (("--prune", "--older-than", "10m"), "12h, 7d or 2w"),
            (("--prune", "--older-than", "0d", "--delete"), "at least 1h"),
            (("--prune", "https://example.com/v.mp4"), "--prune cannot be combined with a source"),
            (("--prune", "--install"), "--prune cannot be combined with --install"),
            (("--prune", "--check"), "--prune cannot be combined with --check"),
            (("--older-than", "7d"), "--older-than only applies with --prune"),
            (("--delete",), "--delete only applies with --prune"),
            (("--out-dir", str(self.root)), "--out-dir only applies with --prune"),
        ):
            with self.subTest(arguments=arguments):
                code, output, errors = self.cli(*arguments, "--out-dir", str(self.root)) \
                    if "--out-dir" not in arguments and "--prune" in arguments else self.cli(*arguments)
                self.assertEqual((code, output), (2, ""))
                self.assertIn(message, errors)
        self.assertTrue(old.is_dir())

    def test_the_disk_warning_points_at_prune(self) -> None:
        self.make_run("/old.mp4", 9 * DAY)
        with mock.patch.object(doctor, "RUN_ARTIFACTS_WARN_BYTES", 1):
            check = doctor.check_run_artifacts(self.root)
        self.assertFalse(check["ok"])
        self.assertIn("scripts/doctor.py --prune", check["fix"])
        self.assertIn("--delete", check["fix"])


if __name__ == "__main__":
    unittest.main()
