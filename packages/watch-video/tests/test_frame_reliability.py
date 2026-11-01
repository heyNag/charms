"""Real-media regressions for image provenance, color, and quiet-span coverage."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parent / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS_DIR))

import extract_frames  # noqa: E402
import network_guard  # noqa: E402


HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def run_media(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1200:])
    return result.stdout


def pixel(path: str | Path, x: int = 0, y: int = 0) -> bytes:
    return run_media([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])


class FrameValidationTests(unittest.TestCase):
    def test_invalid_controls_fail_before_reading_media(self) -> None:
        cases = [
            {"start": float("nan")}, {"end": float("inf")},
            {"duration": float("inf")}, {"fps": float("nan")},
            {"fps": float("inf")}, {"fps": 0},
            {"frame_interval": float("nan")}, {"width": 0},
            {"width": float("inf")}, {"width": 1.5},
        ]
        with mock.patch.object(extract_frames.subprocess, "run") as command:
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    extract_frames.extract_frames("unused.mp4", "unused", **case)
            command.assert_not_called()

    def test_time_parser_rejects_nonfinite_and_invalid_clock_fields(self) -> None:
        for value in ("nan", "inf", "-1", "1:60", "1.5:00", "0:nan", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                extract_frames.parse_time(value)

    def test_missing_or_invalid_pts_never_gets_an_invented_label(self) -> None:
        for stderr in ("", "pts_time:nan", "pts_time:2 pts_time:1", "pts_time:bad"):
            with self.subTest(stderr=stderr), self.assertRaises(RuntimeError):
                extract_frames._showinfo_timestamps(stderr, 1)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class FrameReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        # Each second has a different uniform gray value. The former fps
        # filter chose pixels from later seconds but labeled them 0, 3, 6, 9.
        cls.clock = cls.base / "clock.mkv"
        run_media([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "nullsrc=s=160x120:r=10:d=12,geq=lum='16+18*floor(T)':cb=128:cr=128",
            "-c:v", "ffv1", str(cls.clock),
        ])
        # Eight early cuts defeat the old all-or-nothing uniform fallback.
        # Later, a small bright panel appears in a quiet screen from 20–35s.
        # Its area is below the scene threshold, so only a coverage check sees it.
        cls.quiet = cls.base / "quiet.mkv"
        run_media([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "nullsrc=s=160x120:r=10:d=48,"
            "geq=lum='if(lt(T,4),if(mod(floor(T*2),2),230,16),"
            "if(between(T,20,35)*lt(X,40)*lt(Y,30),230,64))':cb=128:cr=128",
            "-c:v", "ffv1", str(cls.quiet),
        ])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_uniform_pixels_belong_to_the_reported_source_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            frames, _ = extract_frames.extract_frames(
                self.clock, base / "uniform", fps=1 / 3, max_frames=4,
                width=160, frame_format="png", dedup=False,
            )
            self.assertEqual([f["timestamp_seconds"] for f in frames], [0, 3, 6, 9])
            # Decode reference frames independently, without our cue helper.
            for index, frame in enumerate(frames):
                reference = base / f"reference_{index}.png"
                run_media([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss",
                    str(frame["timestamp_seconds"]), "-i", str(self.clock),
                    "-frames:v", "1", str(reference),
                ])
                self.assertEqual(pixel(frame["path"]), pixel(reference))

    def test_explicit_fps_still_stops_at_cap_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_frames(
                self.clock, tmp, fps=2, max_frames=4, dedup=False,
            )
            self.assertEqual([f["timestamp_seconds"] for f in frames], [0, 0.5, 1, 1.5])
            self.assertEqual(meta["plan"]["fps"], 2)
            self.assertTrue(any("frames cover only" in warning for warning in meta["plan"]["warnings"]))

    def test_fractional_cue_reports_requested_and_actual_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_at_timestamps(
                self.clock, tmp, [0.151, 1.011], frame_format="png",
            )
            self.assertFalse(meta["warnings"])
            self.assertEqual([f["requested_timestamp_seconds"] for f in frames], [0.151, 1.011])
            self.assertEqual([f["timestamp_seconds"] for f in frames], [0.2, 1.1])

    def test_cue_in_trimmed_media_retains_source_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, _ = extract_frames.extract_at_timestamps(
                self.clock, tmp, [100.151], media_time_offset=100,
                window_start=100, window_end=112,
            )
            self.assertEqual(frames[0]["requested_timestamp_seconds"], 100.151)
            self.assertEqual(frames[0]["timestamp_seconds"], 100.2)

    def test_actual_cue_beyond_window_end_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_at_timestamps(
                self.clock, tmp, [0.151], window_end=0.18,
            )
            self.assertEqual(frames, [])
            self.assertEqual(meta["dropped_out_of_window"], 1)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_variable_rate_frames_keep_original_pts_after_fractional_seek(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            clip = base / "variable.mkv"
            run_media([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(self.clock),
                "-vf", "select='if(lt(t,4),not(mod(n,3)),not(mod(n,7)))'",
                *extract_frames._vfr_output_args(), "-c:v", "ffv1", str(clip),
            ])
            probe = json.loads(run_media([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(clip),
            ]))
            source_times = [float(frame["best_effort_timestamp_time"]) for frame in probe["frames"]]
            frames, _ = extract_frames.extract_frames(
                clip, base / "frames", start=0.17, fps=0.5, max_frames=6, dedup=False,
            )
            self.assertGreater(frames[-1]["timestamp_seconds"], 8)
            for frame in frames:
                self.assertTrue(any(abs(frame["timestamp_seconds"] - time) < 0.002 for time in source_times))

    def test_rgb_dedup_keeps_equal_brightness_color_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidates = []
            for index, color in enumerate(("red", "0x009A00", "0x009A00")):
                path = Path(tmp) / f"frame_raw_{index:04d}.png"
                run_media([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=64x64:d=0.1", "-frames:v", "1", str(path),
                ])
                candidates.append({"raw_path": path, "timestamp_seconds": index})
            kept, dropped = extract_frames._dedupe_candidates(candidates)
            self.assertEqual([frame["timestamp_seconds"] for frame in kept], [0, 1])
            self.assertEqual(dropped, 1)

    def test_scene_coverage_finds_panel_in_long_quiet_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_scene_frames(
                self.quiet, tmp, max_frames=12, width=160, frame_format="png",
            )
            self.assertEqual(meta["engine"], "scene")
            self.assertFalse(meta["fallback"])
            self.assertGreaterEqual(meta["scene_candidate_count"], 8)
            self.assertLessEqual(len(frames), 12)
            self.assertGreater(meta["coverage_count"], 0)
            self.assertLessEqual(meta["coverage_count"], 3)
            self.assertFalse(any(20 <= f["timestamp_seconds"] <= 35 and f["reason"] == "scene-change" for f in frames))
            panel = [f for f in frames if 20 <= f["timestamp_seconds"] <= 35 and f["reason"] == "coverage"]
            self.assertTrue(panel)
            self.assertGreater(pixel(panel[0]["path"], 10, 10)[0], pixel(panel[0]["path"], 100, 100)[0] + 100)
            self.assertEqual(len(list(Path(tmp).glob("frame_*.*"))), len(frames))
            self.assertFalse(any(path.name.startswith(".") for path in Path(tmp).iterdir()))

    def test_scene_budget_above_uniform_cap_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            clip = base / "many-cuts.mkv"
            run_media([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "nullsrc=s=64x64:r=10:d=28,"
                "geq=lum='if(mod(floor(T*5),2),230,16)':cb=128:cr=128",
                "-c:v", "ffv1", str(clip),
            ])
            frames, meta = extract_frames.extract_scene_frames(
                clip, base / "frames", max_frames=120, frame_format="png",
            )
            self.assertEqual(len(frames), 120)
            self.assertGreater(meta["scene_candidate_count"], 120)
            self.assertEqual(meta["coverage_count"], 0)
            self.assertGreater(frames[-1]["timestamp_seconds"], 27)

    def test_coverage_failure_preserves_the_scene_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(extract_frames, "extract_at_timestamps", side_effect=RuntimeError("test failure")):
                frames, meta = extract_frames.extract_scene_frames(self.quiet, tmp, max_frames=12)
            self.assertTrue(frames)
            self.assertEqual(meta["coverage_count"], 0)
            self.assertTrue(any("test failure" in warning for warning in meta["warnings"]))
            self.assertTrue(all(Path(frame["path"]).exists() for frame in frames))

    def test_coverage_respects_trimmed_source_time_and_preserves_existing_cues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cue = Path(tmp) / "cue_existing.png"
            cue.write_bytes(b"existing cue owned by the caller")
            frames, meta = extract_frames.extract_scene_frames(
                self.quiet, tmp, duration=48, timestamp_offset=100, max_frames=12,
            )
            self.assertGreater(meta["coverage_count"], 0)
            self.assertTrue(all(100 <= frame["timestamp_seconds"] < 148 for frame in frames))
            self.assertTrue(any(frame["reason"] == "coverage" and 120 <= frame["timestamp_seconds"] <= 135 for frame in frames))
            self.assertEqual(cue.read_bytes(), b"existing cue owned by the caller")


if __name__ == "__main__":
    unittest.main()
