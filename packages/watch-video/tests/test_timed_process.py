"""Time limits for the external tools: a stalled tool is stopped with its helpers."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import doctor  # noqa: E402
import extract_frames  # noqa: E402
import groq_transcribe  # noqa: E402
import local_transcribe  # noqa: E402
import timed_process  # noqa: E402


# A stand-in for yt-dlp and the ffmpeg it starts: every process appends to its
# own file until it is stopped, and all but the last start one more helper.
HEARTBEAT = """import os
import subprocess
import sys
import time

directory, depth = sys.argv[1], int(sys.argv[2])
with open(os.path.join(directory, f"pid-{depth}"), "w") as out:
    out.write(str(os.getpid()))
if depth:
    subprocess.Popen([sys.executable, __file__, directory, str(depth - 1)])
with open(os.path.join(directory, f"beat-{depth}"), "a") as out:
    while True:
        out.write("x")
        out.flush()
        time.sleep(0.02)
"""


def beat_sizes(directory: Path) -> dict[str, int]:
    return {path.name: path.stat().st_size for path in sorted(directory.glob("beat-*"))}


@unittest.skipUnless(os.name == "posix", "process signals are POSIX-only")
class StalledToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.script = self.directory / "heartbeat.py"
        self.script.write_text(HEARTBEAT, encoding="utf-8")
        # Nothing this test starts may outlive it, whatever the assertions say.
        self.addCleanup(self._stop_leftovers)

    def _stop_leftovers(self) -> None:
        for path in self.directory.glob("pid-*"):
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def assert_stopped(self, expected: int) -> None:
        before = beat_sizes(self.directory)
        self.assertEqual(len(before), expected, "every process should have started")
        self.assertTrue(all(before.values()), before)
        time.sleep(0.3)
        self.assertEqual(beat_sizes(self.directory), before, "a process is still running")

    def test_a_tool_past_its_limit_is_stopped_with_every_helper_it_started(self) -> None:
        started = time.monotonic()
        with self.assertRaises(timed_process.CommandTimeout) as caught:
            timed_process.run_tree(
                [sys.executable, str(self.script), str(self.directory), "2"], timeout=2.0,
            )

        self.assertLess(time.monotonic() - started, 2.0 + timed_process._REAP_SECONDS)
        self.assertEqual(caught.exception.seconds, 2.0)
        self.assertEqual(caught.exception.tool, Path(sys.executable).name)
        # The tool, its helper, and the helper's helper.
        self.assert_stopped(3)

    def test_a_helper_that_escapes_cannot_hold_the_run_open(self) -> None:
        # Without a process listing only the tool itself can be stopped. Its
        # helper keeps the output pipes open; the run must still come back.
        started = time.monotonic()
        with mock.patch.object(timed_process, "_descendants", return_value=[]), \
                mock.patch.object(timed_process, "_REAP_SECONDS", 0.5):
            with self.assertRaises(timed_process.CommandTimeout):
                timed_process.run_tree(
                    [sys.executable, str(self.script), str(self.directory), "1"], timeout=1.5,
                )

        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue((self.directory / "pid-1").exists())

    def test_a_single_tool_past_its_limit_is_stopped(self) -> None:
        with self.assertRaises(timed_process.CommandTimeout) as caught:
            timed_process.run(
                [sys.executable, str(self.script), str(self.directory), "0"],
                timeout=1.0, capture_output=True,
            )

        self.assertEqual(caught.exception.seconds, 1.0)
        self.assert_stopped(1)


class TimedProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(timed_process.configure, None)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(timed_process.STEP_TIMEOUT_ENV, None)

    def test_a_finished_tool_returns_its_output_and_exit_code(self) -> None:
        code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
        tree = timed_process.run_tree([sys.executable, "-c", code])
        self.assertEqual((tree.returncode, tree.stdout, tree.stderr), (3, "out\n", "err\n"))

        single = timed_process.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual((single.returncode, single.stdout, single.stderr), (3, "out\n", "err\n"))

    def test_undecodable_output_does_not_fail_the_run(self) -> None:
        code = "import sys; sys.stdout.buffer.write(b'caf\\xe9')"
        self.assertEqual(timed_process.run_tree([sys.executable, "-c", code]).stdout, "caf�")

    def test_the_message_names_the_tool_and_the_limit_only(self) -> None:
        completed = subprocess.TimeoutExpired(["ffmpeg"], 2.5)
        with mock.patch.object(timed_process.subprocess, "run", side_effect=completed):
            with self.assertRaises(timed_process.CommandTimeout) as caught:
                timed_process.run(
                    ["/opt/tools/ffmpeg", "-i", "/Users/someone/Private Recording.mp4"],
                    timeout=2.5,
                )

        self.assertEqual(
            str(caught.exception), "ffmpeg did not finish within 2.5 seconds and was stopped",
        )
        # A report may keep the message, so the arguments stay out of it.
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_the_limit_comes_from_the_flag_then_the_environment_then_the_default(self) -> None:
        self.assertEqual(timed_process.step_timeout(), timed_process.DEFAULT_STEP_TIMEOUT)
        self.assertEqual(timed_process.probe_timeout(), timed_process.PROBE_TIMEOUT)

        os.environ[timed_process.STEP_TIMEOUT_ENV] = " 90 "
        self.assertEqual(timed_process.step_timeout(), 90.0)
        # A metadata read never waits longer than a whole step may.
        self.assertEqual(timed_process.probe_timeout(), 90.0)

        timed_process.configure(7200)
        self.assertEqual(timed_process.step_timeout(), 7200.0)
        self.assertEqual(timed_process.probe_timeout(), timed_process.PROBE_TIMEOUT)

        timed_process.configure(None)
        self.assertEqual(timed_process.step_timeout(), 90.0)

    def test_run_uses_the_configured_limit_unless_one_is_given(self) -> None:
        timed_process.configure(42)
        with mock.patch.object(timed_process.subprocess, "run") as run:
            timed_process.run(["ffmpeg"], capture_output=True)
            timed_process.run(["ffprobe"], timeout=3, capture_output=True)

        self.assertEqual([call.kwargs["timeout"] for call in run.call_args_list], [42.0, 3])
        self.assertTrue(all(call.kwargs["check"] is False for call in run.call_args_list))

    def test_malformed_limits_are_rejected(self) -> None:
        for value in ("abc", "", None, 0, -1, "nan", "inf", True, timed_process.MAX_STEP_TIMEOUT + 1):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                timed_process.parse_timeout(value, "--process-timeout")
            self.assertIn("--process-timeout must be a number of seconds", str(caught.exception))
        self.assertEqual(timed_process.parse_timeout("2.5", "limit"), 2.5)
        self.assertEqual(
            timed_process.parse_timeout(timed_process.MAX_STEP_TIMEOUT, "limit"),
            timed_process.MAX_STEP_TIMEOUT,
        )

        os.environ[timed_process.STEP_TIMEOUT_ENV] = "soon"
        with self.assertRaises(ValueError) as caught:
            timed_process.step_timeout()
        self.assertIn(timed_process.STEP_TIMEOUT_ENV, str(caught.exception))

    def test_descendants_follow_the_parent_links(self) -> None:
        listing = "    1     0\n   10     1\n   11    10\n   12    11\n   13     1\nPID PPID\n 14 10 extra\n"
        completed = subprocess.CompletedProcess(["ps"], 0, listing, "")
        with mock.patch.object(timed_process.subprocess, "run", return_value=completed) as run:
            self.assertEqual(timed_process._descendants(10), [11, 12])
            self.assertEqual(timed_process._descendants(13), [])

        # One -o per column: BSD ps reads "pid=,ppid=" as a single heading.
        self.assertEqual(run.call_args.args[0], ["ps", "-A", "-o", "pid=", "-o", "ppid="])

    def test_descendants_are_empty_when_the_process_table_cannot_be_read(self) -> None:
        for failure in (FileNotFoundError("ps"), subprocess.TimeoutExpired(["ps"], 5)):
            with self.subTest(failure=type(failure).__name__), mock.patch.object(
                timed_process.subprocess, "run", side_effect=failure,
            ):
                self.assertEqual(timed_process._descendants(os.getpid()), [])

    @unittest.skipUnless(os.name == "posix", "needs ps")
    def test_descendants_find_a_real_child(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertIn(child.pid, timed_process._descendants(os.getpid()))
        finally:
            child.kill()
            child.wait()


class CallerTests(unittest.TestCase):
    """Each caller turns a stopped tool into the failure its pipeline already handles."""

    def setUp(self) -> None:
        self.addCleanup(timed_process.configure, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.source = self.directory / "source.mp4"
        self.source.write_bytes(b"fixture")
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(timed_process.STEP_TIMEOUT_ENV, None)
        for module in (extract_frames, groq_transcribe, local_transcribe):
            which = mock.patch.object(module.shutil, "which", return_value="/usr/bin/tool")
            which.start()
            self.addCleanup(which.stop)
        # Every tool the callers start now "hangs" until its limit.
        self.calls: list[tuple[list[str], float]] = []

        def hang(cmd, **kwargs):
            self.calls.append((cmd, kwargs["timeout"]))
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        run = mock.patch.object(timed_process.subprocess, "run", side_effect=hang)
        run.start()
        self.addCleanup(run.stop)

    def test_frame_extraction_fails_with_the_way_to_raise_the_limit(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            extract_frames._run_ffmpeg(["ffmpeg", "-i", str(self.source)], "jpeg")

        self.assertEqual(
            str(caught.exception),
            "ffmpeg frame extraction failed: ffmpeg did not finish within 1800 seconds and was "
            "stopped. Select a shorter range, or raise the limit with --process-timeout.",
        )
        self.assertEqual(self.calls[0][1], timed_process.DEFAULT_STEP_TIMEOUT)

    def test_optional_frame_steps_are_skipped_when_they_hang(self) -> None:
        # Duration probing and near-duplicate removal are best effort.
        self.assertIsNone(extract_frames.probe_duration(self.source))
        self.assertEqual(self.calls[-1][1], timed_process.PROBE_TIMEOUT)

        frame = self.directory / "frame_0001.jpg"
        frame.write_bytes(b"jpeg")
        self.assertEqual(extract_frames._thumbnail_sequence([frame]), [])

    def test_a_cue_frame_that_hangs_is_reported_and_the_next_cue_still_runs(self) -> None:
        with mock.patch.object(extract_frames, "_vfr_output_args", return_value=("-fps_mode", "vfr")):
            frames, meta = extract_frames.extract_at_timestamps(
                self.source, self.directory / "frames", [1.0, 2.0],
            )

        self.assertEqual(frames, [])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(meta["warnings"], [
            "cue at 1s: ffmpeg did not finish within 1800 seconds and was stopped",
            "cue at 2s: ffmpeg did not finish within 1800 seconds and was stopped",
        ])
        self.assertEqual(list((self.directory / "frames").iterdir()), [])

    def test_hosted_audio_steps_fail_as_audio_errors(self) -> None:
        cases = {
            "ffmpeg audio extraction failed: ffmpeg did not finish within 1800 seconds and was stopped":
                lambda: groq_transcribe.extract_audio_clip(self.source, self.directory / "audio.mp3"),
            "ffprobe failed on audio clip: ffprobe did not finish within 180 seconds and was stopped":
                lambda: groq_transcribe.audio_duration_seconds(self.source),
            "ffmpeg failed to split audio chunk 1: ffmpeg did not finish within 1800 seconds and was stopped":
                lambda: groq_transcribe.split_audio(self.source, self.directory / "chunks", [(0.0, 30.0)]),
        }
        for expected, call in cases.items():
            with self.subTest(expected=expected), self.assertRaises(RuntimeError) as caught:
                call()
            self.assertEqual(str(caught.exception), expected)

    def test_local_audio_extraction_reports_the_timeout_without_the_command(self) -> None:
        with self.assertRaises(timed_process.CommandTimeout) as caught:
            local_transcribe.extract_audio_clip(self.source, self.directory / "audio.wav")

        self.assertEqual(
            str(caught.exception), "ffmpeg did not finish within 1800 seconds and was stopped",
        )
        self.assertNotIn(str(self.source), str(caught.exception))

    def test_a_local_chunk_that_hangs_is_recorded_by_name_and_later_chunks_still_run(self) -> None:
        audio, raw = self.directory / "audio.wav", self.directory / "raw.json"
        audio.write_bytes(b"audio")
        reply = {"text": "words", "segments": [{"start": 1.5, "end": 2.5, "text": "words"}]}

        def split(_source, output, **_kwargs):
            if output.name == "chunk_000.wav":
                raise timed_process.CommandTimeout("ffmpeg", 1800)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"chunk-audio")
            return output

        with mock.patch.object(local_transcribe, "audio_duration_seconds", return_value=650), \
                mock.patch.object(local_transcribe, "extract_audio_clip", side_effect=split), \
                mock.patch.object(local_transcribe, "transcribe_audio", return_value=reply) as transcribe:
            segments, _warnings = local_transcribe.transcribe_with_chunking(audio, out_json=raw)

        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(segments.gaps, [{"start": 0, "end": 300}])
        # The fixed message is safe to keep; other process errors stay generic.
        self.assertIn("ffmpeg did not finish within 1800 seconds and was stopped", raw.read_text())

    def test_the_flag_limit_reaches_every_caller(self) -> None:
        timed_process.configure(42)
        with self.assertRaises(RuntimeError):
            groq_transcribe.extract_audio_clip(self.source, self.directory / "audio.mp3")
        with self.assertRaises(RuntimeError):
            groq_transcribe.audio_duration_seconds(self.source)

        self.assertEqual([limit for _cmd, limit in self.calls], [42.0, 42.0])


class DoctorTimeoutTests(unittest.TestCase):
    def test_an_installer_that_never_returns_is_stopped_and_reported(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(doctor, "current_platform", return_value="macOS"), \
                mock.patch.object(doctor.shutil, "which", side_effect=lambda name: "/brew" if name == "brew" else None), \
                mock.patch.object(
                    doctor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["brew"], 1800),
                ) as run, \
                mock.patch.object(sys, "stderr", stderr):
            code = doctor.install_missing("local", "https://example.com/v")

        self.assertEqual(code, 2)
        self.assertEqual(run.call_args.kwargs["timeout"], doctor.INSTALL_TIMEOUT)
        self.assertIn("brew install did not finish within 30 minutes", stderr.getvalue())

    def test_a_git_check_that_hangs_reads_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            doctor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["git"], 10),
        ) as run:
            self.assertIsNone(doctor.is_gitignored(Path(tmp), Path(tmp) / ".env.local"))
        self.assertEqual(run.call_args.kwargs["timeout"], doctor.COMMAND_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
