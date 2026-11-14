"""URL runs end: time limits on every tool, no live streams, no accidental ten-hour download."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))
sys.path.insert(0, str(TESTS_DIR))

import network_guard  # noqa: E402
import timed_process  # noqa: E402
import watch  # noqa: E402


URL = "https://example.com/v"
HOURS = 3600
GEMINI_RESULT = {
    "answer": "At 00:10 a slide appears.", "source_kind": "uploaded_file", "processing": "agentic",
    "usage": {"total_tokens": 12}, "warnings": [],
}


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def vtt_time(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}.000"


class LimitsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.media = self.root / "source.mp4"
        self.media.write_bytes(b"fixture")
        # main() sets the process-wide limit from its flags; start each test clean.
        self.addCleanup(timed_process.configure, None)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in (
            timed_process.STEP_TIMEOUT_ENV, watch.MAX_DOWNLOAD_ENV, "WATCH_VIDEO_DETAIL",
            "GROQ_API_KEY", "OPENAI_API_KEY",
        ):
            os.environ.pop(name, None)
        os.environ["WATCH_VIDEO_CONFIG_DIR"] = str(self.root / "config")

    def captions(self, covered_seconds: int) -> dict[str, str]:
        path = self.root / "native.vtt"
        path.write_text(
            f"WEBVTT\n\n00:00:00.000 --> {vtt_time(covered_seconds)}\nhello\n", encoding="utf-8",
        )
        return {"path": str(path)}

    def run_main(self, *flags: str, info: dict[str, object], caption_info=None, probe_effect=None):
        """Run watch.main() on a URL whose probe returns info; the download is a mock."""
        with contextlib.ExitStack() as stack:
            probe = stack.enter_context(mock.patch.object(
                watch, "probe_url", return_value=(caption_info, dict(info)), side_effect=probe_effect,
            ))
            download = stack.enter_context(
                mock.patch.object(watch, "download_media", return_value=(self.media, None))
            )
            stack.enter_context(mock.patch.object(
                watch, "ffprobe_metadata", return_value={"duration_seconds": 10, "has_audio": True},
            ))
            stack.enter_context(mock.patch.object(
                sys, "argv", ["watch", URL, "--out-dir", str(self.root / "runs"), *flags],
            ))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            try:
                outcome: object = watch.main()
            except SystemExit as exc:
                outcome = exc
        return outcome, download, probe, stderr.getvalue()

    def refused(self, *flags: str, **kwargs) -> str:
        outcome, download, _probe, _stderr = self.run_main(*flags, **kwargs)
        self.assertIsInstance(outcome, SystemExit)
        download.assert_not_called()
        return str(outcome.code)

    def run_metadata(self) -> dict[str, object]:
        run = next((self.root / "runs").iterdir())
        return json.loads((run / "metadata.json").read_text(encoding="utf-8"))


class LiveStreamTests(LimitsTestCase):
    def test_a_stream_that_is_still_running_is_refused_before_any_download(self) -> None:
        for info in ({"is_live": True}, {"live_status": "is_live"}, {"live_status": "is_live", "duration": 60}):
            with self.subTest(info=info):
                message = self.refused(info=info, caption_info=self.captions(60))
                self.assertIn("live stream that is still running", message)
                self.assertIn("after the stream has ended", message)

    def test_a_scheduled_stream_is_refused_before_any_download(self) -> None:
        message = self.refused(info={"live_status": "is_upcoming"})
        self.assertIn("scheduled stream that has not started", message)

    def test_a_live_stream_is_refused_even_when_only_captions_were_wanted(self) -> None:
        # No download would happen for --detail transcript, but the captions
        # of a running stream stop wherever the stream happens to be.
        message = self.refused(
            "--detail", "transcript", info={"live_status": "is_live"}, caption_info=self.captions(60),
        )
        self.assertIn("live stream that is still running", message)

    def test_finished_streams_and_ordinary_videos_are_not_live(self) -> None:
        for info in (
            {}, {"is_live": False}, {"live_status": "not_live", "is_live": False},
            {"live_status": "was_live"}, {"live_status": "post_live"}, {"is_live": None},
            # Only the boolean counts; a stray string is not a live flag.
            {"is_live": "false"},
        ):
            with self.subTest(info=info):
                self.assertIsNone(watch.live_source_problem(info))

    def test_the_probe_keeps_the_live_fields(self) -> None:
        info_path = self.root / "video.info.json"
        info_path.write_text(json.dumps({
            "id": "abc", "title": "Stream", "duration": None, "live_status": "is_live",
            "is_live": True, "formats": [{"url": "https://example.com/secret-signed-url"}],
        }), encoding="utf-8")

        info = watch.compact_info(info_path)

        self.assertEqual(info["live_status"], "is_live")
        self.assertIs(info["is_live"], True)
        self.assertNotIn("formats", info)
        self.assertIsNotNone(watch.live_source_problem(info))


class DownloadLimitTests(LimitsTestCase):
    def test_a_source_over_the_limit_is_refused_with_the_ways_forward(self) -> None:
        message = self.refused(info={"duration": 5 * HOURS}, caption_info=self.captions(5 * HOURS))

        self.assertIn("This source is 5:00:00 long, over the 4:00:00 download limit", message)
        self.assertIn("--start and --end", message)
        self.assertIn("--detail transcript", message)
        self.assertIn("--max-download-duration 5:00:00", message)

    def test_the_suggested_limit_is_never_a_second_short(self) -> None:
        message = watch.download_limit_problem(4 * HOURS + 0.4, 4 * HOURS, focused=False)

        self.assertIn("is 4:00:01 long", message)
        self.assertIn("--max-download-duration 4:00:01", message)
        self.assertGreaterEqual(watch.parse_time("4:00:01"), 4 * HOURS + 0.4)

    def test_a_source_at_the_limit_is_allowed(self) -> None:
        self.assertIsNone(watch.download_limit_problem(4 * HOURS, 4 * HOURS, focused=False))
        self.assertIsNone(watch.download_limit_problem(None, 4 * HOURS, focused=False))

    def test_raising_the_limit_allows_the_download(self) -> None:
        outcome, download, _probe, _stderr = self.run_main(
            "--max-download-duration", "6:00:00",
            info={"duration": 5 * HOURS}, caption_info=self.captions(5 * HOURS),
        )

        self.assertEqual(outcome, 0)
        self.assertEqual(download.call_args.kwargs["max_duration"], 6 * HOURS)

    def test_the_environment_sets_the_default_limit_and_the_flag_wins(self) -> None:
        os.environ[watch.MAX_DOWNLOAD_ENV] = "6:00:00"
        outcome, download, _probe, _stderr = self.run_main(
            info={"duration": 5 * HOURS}, caption_info=self.captions(5 * HOURS),
        )
        self.assertEqual(outcome, 0)
        self.assertEqual(download.call_args.kwargs["max_duration"], 6 * HOURS)

        message = self.refused(
            "--max-download-duration", "30:00",
            info={"duration": 5 * HOURS}, caption_info=self.captions(5 * HOURS),
        )
        self.assertIn("over the 30:00 download limit", message)

    def test_captions_alone_never_trip_the_limit(self) -> None:
        outcome, download, _probe, stderr = self.run_main(
            "--detail", "transcript", info={"duration": 5 * HOURS}, caption_info=self.captions(5 * HOURS),
        )

        self.assertEqual(outcome, 0)
        download.assert_not_called()
        self.assertIn("skipping media download", stderr)

    def test_a_selected_range_is_measured_by_its_own_length(self) -> None:
        info = {"duration": 10 * HOURS}
        captions = self.captions(10 * HOURS)

        message = self.refused("--start", "0", "--end", "5:00:00", info=info, caption_info=captions)
        self.assertIn("The selected range is 5:00:00 long, over the 4:00:00 download limit", message)

        outcome, download, _probe, _stderr = self.run_main(
            "--start", "1:00:00", "--end", "1:10:00", info=info, caption_info=captions,
        )
        self.assertEqual(outcome, 0)
        self.assertEqual(download.call_args.kwargs["download_section"], "*01:00:00-01:10:00")

    def test_a_start_without_an_end_downloads_the_whole_source(self) -> None:
        # yt-dlp gets no section without both ends, so the whole source counts.
        message = self.refused(
            "--start", "9:00:00", info={"duration": 10 * HOURS}, caption_info=self.captions(10 * HOURS),
        )
        self.assertIn("This source is 10:00:00 long", message)

    def test_an_unknown_duration_is_left_to_yt_dlp_with_the_limit_passed_on(self) -> None:
        outcome, download, _probe, _stderr = self.run_main(info={}, caption_info=self.captions(60))

        self.assertEqual(outcome, 0)
        self.assertEqual(
            download.call_args.kwargs["max_duration"], watch.DEFAULT_MAX_DOWNLOAD_SECONDS,
        )

    def test_gemini_downloads_of_other_sites_get_the_same_limit(self) -> None:
        result = dict(GEMINI_RESULT)
        os.environ["GEMINI_API_KEY"] = "test-only"
        with mock.patch.object(watch.gemini, "analyze_video", return_value=result):
            outcome, download, probe, _stderr = self.run_main(
                "--engine", "gemini", "--max-download-duration", "2:00:00", info={},
            )

        self.assertEqual(outcome, 0)
        probe.assert_not_called()
        self.assertEqual(download.call_args.kwargs["max_duration"], 2 * HOURS)


class FlagTests(LimitsTestCase):
    def test_malformed_limits_stop_the_run_before_the_source_is_read(self) -> None:
        cases = [
            (["--process-timeout", "0"], {}, "--process-timeout must be a number of seconds"),
            (["--process-timeout", "-5"], {}, "--process-timeout must be a number of seconds"),
            (["--process-timeout", "nan"], {}, "--process-timeout must be a number of seconds"),
            (["--process-timeout", "inf"], {}, "--process-timeout must be a number of seconds"),
            (["--process-timeout", "90000"], {}, "between 0 and 86400"),
            ([], {timed_process.STEP_TIMEOUT_ENV: "soon"}, timed_process.STEP_TIMEOUT_ENV),
            (["--max-download-duration", "0"], {}, "--max-download-duration must be greater than zero"),
            (["--max-download-duration", "soon"], {}, "invalid time value 'soon'"),
            ([], {watch.MAX_DOWNLOAD_ENV: "soon"}, f"{watch.MAX_DOWNLOAD_ENV}: invalid time value"),
            ([], {watch.MAX_DOWNLOAD_ENV: "0"}, f"{watch.MAX_DOWNLOAD_ENV} must be greater than zero"),
        ]
        for flags, env, expected in cases:
            with self.subTest(flags=flags, env=env), mock.patch.dict(os.environ, env):
                outcome, download, probe, _stderr = self.run_main(*flags, info={"duration": 60})
                self.assertIsInstance(outcome, SystemExit)
                self.assertIn(expected, str(outcome.code))
                probe.assert_not_called()
                download.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_the_process_timeout_flag_sets_the_limit_for_that_run_only(self) -> None:
        seen: list[tuple[float, float]] = []

        def probe(*_args, **_kwargs):
            seen.append((timed_process.step_timeout(), timed_process.probe_timeout()))
            return mock.DEFAULT

        info = {"duration": 60}
        self.run_main("--process-timeout", "5", info=info, caption_info=self.captions(60), probe_effect=probe)
        self.run_main(info=info, caption_info=self.captions(60), probe_effect=probe)
        os.environ[timed_process.STEP_TIMEOUT_ENV] = "7200"
        self.run_main(info=info, caption_info=self.captions(60), probe_effect=probe)

        self.assertEqual(seen, [
            (5.0, 5.0),
            (timed_process.DEFAULT_STEP_TIMEOUT, timed_process.PROBE_TIMEOUT),
            (7200.0, timed_process.PROBE_TIMEOUT),
        ])

    def test_both_limits_are_offered_to_the_gemini_engine_too(self) -> None:
        # They bound the download Gemini needs for a non-YouTube URL, so the
        # local-only flag guard must not reject them.
        result = dict(GEMINI_RESULT)
        os.environ["GEMINI_API_KEY"] = "test-only"
        with mock.patch.object(watch.gemini, "analyze_video", return_value=result):
            outcome, _download, _probe, _stderr = self.run_main(
                "--engine", "gemini", "--process-timeout", "60", "--max-download-duration", "10:00",
                info={},
            )
        self.assertEqual(outcome, 0)


class YtDlpCommandTests(LimitsTestCase):
    def run_download(self, result=None, **kwargs):
        media_dir = self.root / "media"
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(cmd, **options):
            calls.append((cmd, options))
            if isinstance(result, BaseException):
                raise result
            if result is None:
                (media_dir / "video.mp4").write_bytes(b"stub")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return result

        with mock.patch.object(watch, "require_tool"), mock.patch.object(
            watch, "run_command", side_effect=fake_run,
        ):
            try:
                outcome: object = watch.download_media(URL, media_dir, **kwargs)
            except SystemExit as exc:
                outcome = exc
        return outcome, calls

    def match_filter(self, **kwargs) -> str:
        _outcome, calls = self.run_download(**kwargs)
        cmd, options = calls[0]
        # The download runs under the per-step limit, not the short probe one.
        self.assertEqual(options, {})
        options_part = cmd[: cmd.index("--")]
        return options_part[options_part.index("--match-filters") + 1]

    def test_every_download_tells_yt_dlp_to_skip_a_live_stream(self) -> None:
        self.assertEqual(self.match_filter(), "!is_live")
        self.assertEqual(self.match_filter(audio_only=True), "!is_live")

    def test_a_whole_download_also_carries_the_length_limit(self) -> None:
        # "<=?" lets a source of unknown length through; yt-dlp cannot judge it.
        self.assertEqual(self.match_filter(max_duration=4.0 * HOURS), "!is_live & duration<=?14400")
        self.assertEqual(self.match_filter(max_duration=90.5), "!is_live & duration<=?91")

    def test_a_section_download_is_bounded_by_its_range_not_the_source_length(self) -> None:
        self.assertEqual(
            self.match_filter(max_duration=4.0 * HOURS, download_section="*00:00-00:30"), "!is_live",
        )

    def test_a_source_yt_dlp_skips_is_explained(self) -> None:
        skipped = subprocess.CompletedProcess(
            ["yt-dlp"], 0, "[download] Stream does not pass filter (!is_live), skipping ..\n", "",
        )

        outcome, _calls = self.run_download(skipped, max_duration=4.0 * HOURS)
        self.assertEqual(
            str(outcome.code),
            "yt-dlp skipped this source: it is a live stream that is still running, or it is "
            "longer than the 4:00:00 download limit (raise it with --max-download-duration).",
        )

        outcome, _calls = self.run_download(skipped, download_section="*00:00-00:30")
        self.assertEqual(
            str(outcome.code),
            "yt-dlp skipped this source: it is a live stream that is still running.",
        )

    def test_a_download_that_passes_the_time_limit_is_never_used(self) -> None:
        media_dir = self.root / "media"
        media_dir.mkdir()
        # A file from the stopped download may look complete; it is not trusted.
        (media_dir / "video.mp4").write_bytes(b"cut short")

        outcome, _calls = self.run_download(timed_process.CommandTimeout("yt-dlp", 1800))

        self.assertIsInstance(outcome, SystemExit)
        self.assertEqual(
            str(outcome.code),
            "The media download was stopped: yt-dlp did not finish within 1800 seconds and was "
            "stopped. Select a shorter range with --start and --end, or raise the limit with "
            "--process-timeout.",
        )

    def test_a_probe_that_hangs_is_reported_and_uses_the_short_limit(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_run(_cmd, **options):
            calls.append(options)
            raise timed_process.CommandTimeout("yt-dlp", options["timeout"])

        with mock.patch.object(watch, "require_tool"), mock.patch.object(
            watch, "run_command", side_effect=fake_run,
        ), self.assertRaises(SystemExit) as caught:
            watch.probe_url(URL, self.root / "media")

        self.assertEqual(calls, [{"timeout": timed_process.PROBE_TIMEOUT}])
        self.assertEqual(
            str(caught.exception.code),
            "yt-dlp could not read the source: yt-dlp did not finish within 180 seconds and was "
            "stopped. Check the URL and the network, then try again.",
        )

    def test_a_media_probe_that_hangs_becomes_a_probe_error(self) -> None:
        with mock.patch.object(watch, "require_tool"), mock.patch.object(
            watch, "run_command", side_effect=timed_process.CommandTimeout("ffprobe", 180),
        ) as run:
            probe = watch.ffprobe_metadata(self.media)

        self.assertEqual(run.call_args.kwargs, {"timeout": timed_process.PROBE_TIMEOUT})
        self.assertEqual(
            probe, {"ffprobe_error": "ffprobe did not finish within 180 seconds and was stopped"},
        )

    def test_run_command_stops_a_real_tool_at_its_limit(self) -> None:
        with self.assertRaises(timed_process.CommandTimeout):
            watch.run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)


class StoppedDownloadTests(LimitsTestCase):
    def run_with_stopped_download(self, caption_info):
        with mock.patch.object(watch, "require_tool"), mock.patch.object(
            watch, "run_command", side_effect=timed_process.CommandTimeout("yt-dlp", 2),
        ), mock.patch.object(
            watch, "probe_url", return_value=(caption_info, {"duration": 60}),
        ), mock.patch.object(
            sys, "argv", ["watch", URL, "--out-dir", str(self.root / "runs")],
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return watch.main()
            except SystemExit as exc:
                return exc

    def test_a_stopped_download_still_reports_the_captions(self) -> None:
        self.assertEqual(self.run_with_stopped_download(self.captions(60)), 0)

        metadata = self.run_metadata()
        self.assertIsNone(metadata["video_path"])
        self.assertTrue(any(
            error.startswith(
                "Media unavailable; retained native captions: The media download was stopped: "
                "yt-dlp did not finish within 2 seconds and was stopped."
            )
            for error in metadata["errors"]
        ), metadata["errors"])

    def test_a_stopped_download_with_nothing_else_to_report_fails_plainly(self) -> None:
        outcome = self.run_with_stopped_download(None)

        self.assertIsInstance(outcome, SystemExit)
        self.assertIn("The media download was stopped", str(outcome.code))
        self.assertIn("--process-timeout", str(outcome.code))


if __name__ == "__main__":
    unittest.main()
