"""Offline end-to-end pipeline test using a fake yt-dlp on PATH.

Exercises watch.py's full URL orchestration - probe, download decision,
frame engines, captions, report - with zero network: a shim yt-dlp copies
fixture files (info JSON, English VTT, an ffmpeg-synthesized mp4) into the
media directory. POSIX-only because the shim relies on shebang execution.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parents[0] / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS_DIR))

import network_guard  # noqa: E402
from run_contents import unexpected_entries  # noqa: E402
from test_frame_engines import (  # noqa: E402
    build_cut_clip,
    build_static_clip,
    build_streamed_webm,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


# setUpClass prepends a shebang for the running interpreter.
FAKE_YTDLP = """import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
options = args[: args.index("--")]
if "--ignore-config" not in options:
    sys.exit("fake yt-dlp: watch.py must pass --ignore-config")
probing = "--skip-download" in args
if not probing and "--match-filters" not in options:
    sys.exit("fake yt-dlp: every download must pass --match-filters")
out_dir = Path(args[args.index("-o") + 1]).parent
out_dir.mkdir(parents=True, exist_ok=True)
fixtures = Path(os.environ["FAKE_YTDLP_FIXTURES"])
log = os.environ.get("FAKE_YTDLP_LOG")
if log:
    call = "probe" if probing else "download " + options[options.index("--match-filters") + 1]
    if "--js-runtimes" in options:
        call += " js=" + options[options.index("--js-runtimes") + 1]
    with open(log, "a", encoding="utf-8") as out:
        out.write(call + "\\n")
if probing and os.environ.get("FAKE_YTDLP_WARNING"):
    print(os.environ["FAKE_YTDLP_WARNING"], file=sys.stderr)
if os.environ.get("FAKE_YTDLP_HANG") == ("probe" if probing else "download"):
    # Like the real tool mid-download: its helper (ffmpeg) is running too.
    helper = (
        "import sys, time\\n"
        "with open(sys.argv[1], 'a') as out:\\n"
        "    while True:\\n"
        "        out.write('x'); out.flush(); time.sleep(0.02)\\n"
    )
    subprocess.Popen([sys.executable, "-c", helper, os.environ["FAKE_YTDLP_BEAT"]])
    time.sleep(600)
if probing:
    info = os.environ.get("FAKE_YTDLP_INFO", "video.info.json")
    shutil.copy(fixtures / info, out_dir / "video.info.json")
    shutil.copy(fixtures / "captions.vtt", out_dir / "video.en.vtt")
else:
    shutil.copy(fixtures / "media.mp4", out_dir / "video.mp4")
sys.exit(0)
"""

FIXTURE_VTT = """WEBVTT

00:00:00.500 --> 00:00:02.000
hello from fixtures

00:00:02.000 --> 00:00:03.500
second caption line
"""


@unittest.skipUnless(os.name == "posix" and HAVE_FFMPEG, "needs POSIX shim and ffmpeg")
class OfflinePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)

        fixtures = base / "fixtures"
        fixtures.mkdir()
        build_cut_clip(fixtures / "media.mp4")
        cls.static_clip = fixtures / "static-long.mp4"
        build_static_clip(cls.static_clip, duration=40.0, rate=2)
        (fixtures / "captions.vtt").write_text(FIXTURE_VTT, encoding="utf-8")
        info = {
            "id": "fixture",
            "title": "Fixture Video",
            "uploader": "Tester",
            "duration": 4.0,
            "webpage_url": "https://example.com/v",
        }
        variants = {
            "video.info.json": {},
            "live.info.json": {"duration": None, "is_live": True, "live_status": "is_live"},
            "long.info.json": {"duration": 5 * 3600.0},
        }
        for name, changes in variants.items():
            (fixtures / name).write_text(json.dumps({**info, **changes}), encoding="utf-8")

        shim_dir = base / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "yt-dlp"
        # Not `env python3`: that can resolve to a version-manager shim (mise,
        # pyenv) which reads the XDG dirs moved below and refuses to run.
        shim.write_text(f"#!{sys.executable}\n{FAKE_YTDLP}", encoding="utf-8")
        shim.chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_YTDLP_FIXTURES"] = str(fixtures)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("WATCH_VIDEO_DETAIL", None)
        # Keep the child off the user's real config and state.
        for name in (
            "WATCH_VIDEO_CONFIG_DIR",
            "WATCH_VIDEO_RUNS_DIR",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
        ):
            env[name] = str(base / name.lower())
        cls.env = env
        cls.base = base

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def run_watch(
        self, *extra: str, source: str = "https://example.com/v", env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        out_dir = Path(tempfile.mkdtemp(dir=self.base))
        cmd = [
            sys.executable,
            str(SCRIPTS / "watch.py"),
            source,
            "--transcriber",
            "none",
            "--out-dir",
            str(out_dir),
            *extra,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=180,
            check=False,
        )
        return proc, out_dir

    def _single_run_dir(self, out_dir: Path) -> Path:
        runs = [entry for entry in out_dir.iterdir() if entry.is_dir()]
        self.assertEqual(len(runs), 1)
        self.assertEqual(unexpected_entries(runs[0]), [])
        return runs[0]

    def test_full_run_produces_frames_captions_and_report(self) -> None:
        proc, out_dir = self.run_watch("--max-frames", "6")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("native captions", report)
        self.assertIn("Fixture Video", report)
        self.assertIn(
            "hello from fixtures", (run_dir / "transcript.md").read_text(encoding="utf-8")
        )
        frames = list((run_dir / "frames").glob("frame_*"))
        self.assertTrue(frames)
        self.assertLessEqual(len(frames), 6)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["detail"], "balanced")
        self.assertIn(metadata["frames"]["engine"]["engine"], {"scene", "uniform"})
        self.assertTrue((run_dir / "media" / "video.mp4").exists())

    def test_transcript_detail_skips_media_download(self) -> None:
        proc, out_dir = self.run_watch("--detail", "transcript")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skipping media download", proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        self.assertFalse((run_dir / "media" / "video.mp4").exists())
        self.assertIn(
            "hello from fixtures", (run_dir / "transcript.md").read_text(encoding="utf-8")
        )
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["count"], 0)

    def test_focused_ranges_fall_back_to_uniform_frames(self) -> None:
        # Too few scene changes in the window forces the uniform fallback,
        # which used to fail with "use either --end or --duration".
        runs = {
            "url": self.run_watch("--start", "1", "--end", "3", "--no-dedup"),
            "local": self.run_watch(
                "--start", "10", "--end", "20", "--no-dedup", source=str(self.static_clip)
            ),
        }
        for label, (proc, out_dir) in runs.items():
            with self.subTest(source=label):
                self.assertEqual(proc.returncode, 0, proc.stderr)
                run_dir = self._single_run_dir(out_dir)
                report = (run_dir / "report.md").read_text(encoding="utf-8")
                self.assertNotIn("either --end or --duration", report)
                self.assertIn("- Engine: uniform (uniform fallback)", report)
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertGreater(metadata["frames"]["count"], 0)
                # Only a trimmed URL download has a section length apart from
                # the source's own Duration.
                if label == "url":
                    self.assertIn(
                        "- Duration: 00:04 (4.0s)\n- Downloaded section length: ", report
                    )
                else:
                    self.assertIn("- Duration: 00:40 (40.0s)\n", report)
                    self.assertNotIn("Downloaded section length", report)

    def test_unfocused_fallback_spans_the_whole_local_video(self) -> None:
        proc, out_dir = self.run_watch(
            "--max-frames", "10", "--no-dedup", source=str(self.static_clip)
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        engine = metadata["frames"]["engine"]
        self.assertTrue(engine["fallback"])
        self.assertEqual(metadata["frames"]["count"], 10)
        last = sorted((run_dir / "frames").glob("frame_*"))[-1].name
        # 1 fps capped at 10 frames would end at 00h00m09s on this 40 s clip.
        self.assertEqual(last, "frame_0010_00h00m36s.jpg")
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("- Uniform budget: mode auto, fps 0.25, target 10, max 10", report)

    def test_streamed_webm_without_duration_spans_the_whole_video(self) -> None:
        clip = Path(tempfile.mkdtemp(dir=self.base)) / "recording.webm"
        build_streamed_webm(clip)
        proc, out_dir = self.run_watch(
            "--max-frames", "10", "--no-dedup", source=str(clip)
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("- Duration: 00:40 (39.5s)", report)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["count"], 10)
        last = sorted((run_dir / "frames").glob("frame_*"))[-1].name
        # 1 fps capped at 10 frames would end at 00h00m09s.
        self.assertEqual(last, "frame_0010_00h00m36s.jpg")

    def test_interval_mode_reports_its_own_budget(self) -> None:
        proc, out_dir = self.run_watch(
            "--frame-mode", "interval", "--frame-interval", "5", "--max-frames", "20",
            "--no-dedup", source=str(self.static_clip),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        # Not "mode fps ... max <target>": the engine gets the user's flags.
        self.assertRegex(report, r"- Uniform budget: mode interval, fps 0\.2, target \d+, max 20\n")
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["mode"], "interval")
        self.assertEqual(metadata["frames"]["count"], 8)

    def _warnings(self, report: str) -> list[str]:
        lines = report.splitlines()
        start = lines.index("## Warnings") + 2
        end = lines.index("", start)
        return lines[start:end]

    def test_interval_below_the_fps_cap_is_capped_and_warned(self) -> None:
        proc, out_dir = self.run_watch(
            "--frame-mode", "interval", "--frame-interval", "0.1", "--start", "0", "--end", "10",
            "--no-dedup", source=str(self.static_clip),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("- fps capped at 2 (frame interval raised to 0.5s)", self._warnings(report))
        self.assertIn("- Uniform budget: mode interval, fps 2, target 21, max 80\n", report)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        frames = metadata["frames"]
        # The plan watch.py reports is the one the engine ran.
        self.assertEqual(frames["selected_fps"], 2.0)
        self.assertEqual(frames["engine"]["plan"]["fps"], 2.0)
        self.assertEqual(frames["target_frames"], frames["engine"]["plan"]["target_frames"])
        self.assertEqual(frames["count"], 20)

    def test_fps_past_the_frame_cap_warns_what_the_frames_cover(self) -> None:
        # Four cue frames leave eight of the twelve for 2 fps sampling, so
        # sampled frames stop at 0:03.5 of the 40 s clip.
        proc, out_dir = self.run_watch(
            "--fps", "2", "--max-frames", "12", "--timestamps", "10,20,30,35",
            "--no-dedup", source=str(self.static_clip),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertEqual(
            self._warnings(report),
            [
                "- frames cover only 00:00-00:03 of the 00:00-00:40 range; "
                "lower --fps or raise --max-frames"
            ],
        )
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["count"], 12)
        self.assertEqual(metadata["frames"]["target_frames"], 8)
        uniform = sorted((run_dir / "frames").glob("frame_*"))
        self.assertEqual(uniform[-1].name, "frame_0008_00h00m04s.jpg")

    def test_no_coverage_warning_without_sampled_frames(self) -> None:
        # At 2 fps each cap runs out seconds into the 40 s clip, but no
        # uniform frames are sampled, so there is no span to warn about.
        runs = {
            "no-frames": ("--no-frames", "--fps", "5", "--max-frames", "12"),
            "transcript": ("--detail", "transcript", "--fps", "2", "--max-frames", "12"),
            "cues-fill-cap": ("--fps", "2", "--max-frames", "4", "--timestamps", "1,2,3,4"),
        }
        for label, flags in runs.items():
            with self.subTest(run=label):
                proc, out_dir = self.run_watch(*flags, source=str(self.static_clip))

                self.assertEqual(proc.returncode, 0, proc.stderr)
                run_dir = self._single_run_dir(out_dir)
                report = (run_dir / "report.md").read_text(encoding="utf-8")
                self.assertNotIn("frames cover only", report)
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["frames"]["count"], 4 if label == "cues-fill-cap" else 0)
                if label == "no-frames":
                    # The plan's other warnings still reach the report.
                    self.assertEqual(self._warnings(report), ["- fps capped at 2"])

    def test_coverage_hint_at_the_detail_cap_says_to_narrow_the_range(self) -> None:
        # Four cues leave 96 of balanced detail's hard cap of 100 for 2 fps
        # sampling of 60 s; a higher --max-frames is clamped back to 100.
        clip = Path(tempfile.mkdtemp(dir=self.base)) / "static-60.mp4"
        build_static_clip(clip, duration=60.0, rate=2)
        proc, out_dir = self.run_watch(
            "--fps", "2", "--max-frames", "200", "--timestamps", "10,20,30,35",
            "--no-dedup", source=str(clip),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertEqual(
            self._warnings(report),
            [
                "- frames cover only 00:00-00:47 of the 00:00-01:00 range; "
                "lower --fps or narrow --start/--end"
            ],
        )
        self.assertIn("- Uniform budget: mode fps, fps 2, target 96, max 96\n", report)

    def _shim_calls(self, log: Path) -> list[str]:
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def _assert_helper_stopped(self, beat: Path) -> None:
        size = beat.stat().st_size
        self.assertGreater(size, 0, "the helper never ran")
        time.sleep(0.3)
        self.assertEqual(beat.stat().st_size, size, "the helper outlived the stopped download")

    def test_downloads_tell_yt_dlp_to_skip_live_streams_and_over_long_sources(self) -> None:
        scratch = Path(tempfile.mkdtemp(dir=self.base))
        whole, section = scratch / "whole.log", scratch / "section.log"

        proc, _ = self.run_watch("--max-frames", "4", env={"FAKE_YTDLP_LOG": str(whole)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._shim_calls(whole), ["probe", "download !is_live & duration<=?14400"])

        proc, _ = self.run_watch(
            "--start", "1", "--end", "3", "--max-frames", "4", env={"FAKE_YTDLP_LOG": str(section)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._shim_calls(section), ["probe", "download !is_live"])

    def test_a_download_that_hangs_is_stopped_and_the_captions_are_still_reported(self) -> None:
        scratch = Path(tempfile.mkdtemp(dir=self.base))
        beat = scratch / "beat"
        started = time.monotonic()
        proc, out_dir = self.run_watch(
            "--process-timeout", "2",
            env={"FAKE_YTDLP_HANG": "download", "FAKE_YTDLP_BEAT": str(beat)},
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Far less than the helper's ten-minute sleep.
        self.assertLess(time.monotonic() - started, 60)
        self._assert_helper_stopped(beat)
        run_dir = self._single_run_dir(out_dir)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(any(
            error.startswith(
                "Media unavailable; retained native captions: The media download was stopped: "
                "yt-dlp did not finish within 2 seconds and was stopped."
            )
            for error in metadata["errors"]
        ), metadata["errors"])
        self.assertIsNone(metadata["video_path"])
        self.assertIn(
            "hello from fixtures", (run_dir / "transcript.md").read_text(encoding="utf-8")
        )

    def test_a_probe_that_hangs_ends_the_run_with_a_clear_message(self) -> None:
        scratch = Path(tempfile.mkdtemp(dir=self.base))
        beat = scratch / "beat"
        proc, _ = self.run_watch(
            "--process-timeout", "2",
            env={"FAKE_YTDLP_HANG": "probe", "FAKE_YTDLP_BEAT": str(beat)},
        )

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn(
            "yt-dlp could not read the source: yt-dlp did not finish within 2 seconds and was stopped",
            proc.stderr,
        )
        self.assertNotIn("Traceback", proc.stderr)
        self._assert_helper_stopped(beat)

    def test_a_live_stream_is_refused_without_a_download(self) -> None:
        log = Path(tempfile.mkdtemp(dir=self.base)) / "calls.log"
        proc, _ = self.run_watch(env={"FAKE_YTDLP_INFO": "live.info.json", "FAKE_YTDLP_LOG": str(log)})

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("live stream that is still running", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(self._shim_calls(log), ["probe"])

    def test_an_over_long_source_needs_a_range_or_a_raised_limit(self) -> None:
        scratch = Path(tempfile.mkdtemp(dir=self.base))
        refused, raised = scratch / "refused.log", scratch / "raised.log"

        proc, _ = self.run_watch(env={"FAKE_YTDLP_INFO": "long.info.json", "FAKE_YTDLP_LOG": str(refused)})
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("This source is 5:00:00 long, over the 4:00:00 download limit", proc.stderr)
        self.assertIn("--max-download-duration 5:00:00", proc.stderr)
        self.assertEqual(self._shim_calls(refused), ["probe"])

        proc, _ = self.run_watch(
            "--max-download-duration", "5:00:00", "--max-frames", "4",
            env={"FAKE_YTDLP_INFO": "long.info.json", "FAKE_YTDLP_LOG": str(raised)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._shim_calls(raised), ["probe", "download !is_live & duration<=?18000"])

    def test_an_opted_in_javascript_runtime_reaches_both_yt_dlp_calls(self) -> None:
        scratch = Path(tempfile.mkdtemp(dir=self.base))
        flag, env, default = scratch / "flag.log", scratch / "env.log", scratch / "default.log"

        proc, _ = self.run_watch(
            "--js-runtime", "node", "--max-frames", "4", env={"FAKE_YTDLP_LOG": str(flag)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self._shim_calls(flag), ["probe js=node", "download !is_live & duration<=?14400 js=node"],
        )

        proc, _ = self.run_watch(
            "--max-frames", "4", env={"FAKE_YTDLP_LOG": str(env), "WATCH_VIDEO_JS_RUNTIME": "bun"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self._shim_calls(env), ["probe js=bun", "download !is_live & duration<=?14400 js=bun"],
        )

        # Unasked, yt-dlp keeps its own default of Deno only.
        proc, _ = self.run_watch("--detail", "transcript", env={"FAKE_YTDLP_LOG": str(default)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._shim_calls(default), ["probe"])

    def test_a_missing_javascript_runtime_is_a_warning_in_the_report(self) -> None:
        warning = (
            "WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is "
            "enabled by default; to use another runtime add  --js-runtimes RUNTIME[:PATH]  to "
            "your command/config."
        )
        proc, out_dir = self.run_watch("--detail", "transcript", env={"FAKE_YTDLP_WARNING": warning})

        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = (self._single_run_dir(out_dir) / "report.md").read_text(encoding="utf-8")
        self.assertIn(
            "- yt-dlp found no JavaScript runtime it may use, so YouTube formats may be missing "
            "or the download may fail. Run scripts/doctor.py with this URL for the fix.",
            self._warnings(report),
        )


if __name__ == "__main__":
    unittest.main()
