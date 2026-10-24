"""Frame-engine integration tests against ffmpeg-synthesized clips.

These build tiny lavfi color clips (hard cuts force keyframes and scene
changes) so the scene, keyframe, uniform-fallback, dedup, and cue paths run
against real ffmpeg output with no network and no fixtures. Skipped when
ffmpeg/ffprobe are unavailable (for example on bare CI runners).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parents[0] / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS_DIR))

import extract_frames  # noqa: E402
import network_guard  # noqa: E402


HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()

COLORS = ["red", "green", "blue", "white", "black", "yellow", "cyan", "magenta", "gray", "orange"]


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg setup failed: {result.stderr.strip()[:400]}")


def build_cut_clip(path: Path, colors: int = 10, segment: float = 0.4) -> None:
    """Concatenate solid-color segments; every color change is a hard cut."""
    inputs: list[str] = []
    for index in range(colors):
        inputs += [
            "-f", "lavfi", "-t", str(segment),
            "-i", f"color=c={COLORS[index % len(COLORS)]}:s=160x120:r=10",
        ]
    streams = "".join(f"[{index}:v]" for index in range(colors))
    graph = f"{streams}concat=n={colors}:v=1:a=0[out]"
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", graph, "-map", "[out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-force_key_frames", f"expr:gte(t,n_forced*{segment})",
        str(path),
    ])


def build_static_clip(path: Path, duration: float = 3.0, rate: int = 10) -> None:
    """One solid color: no scene changes, one keyframe -> both fallbacks."""
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-t", str(duration), "-i", f"color=c=blue:s=160x120:r={rate}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "600",
        str(path),
    ])


def build_late_video_clip(path: Path) -> None:
    """Audio from 0:00, video only from 0:02 to 0:06, as some recordings have."""
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-t", "4", "-i", "color=c=red:s=160x120:r=10",
        "-f", "lavfi", "-t", "6", "-i", "anullsrc=r=8000:cl=mono",
        "-filter:v", "setpts=PTS+2/TB",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ])
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=start_time", "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    if abs(float(probe.stdout.strip() or 0) - 2.0) > 0.05:
        raise RuntimeError(f"video stream does not start at 0:02: {probe.stdout.strip()}")


def build_streamed_webm(path: Path, duration: float = 40.0, rate: int = 2) -> None:
    """Static WebM muxed to a pipe, like a browser MediaRecorder recording.

    A non-seekable output gets no Duration element, so ffprobe reports
    neither a format nor a stream duration.
    """
    with path.open("wb") as handle:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-t", str(duration), "-i", f"color=c=blue:s=160x120:r={rate}",
                "-c:v", "libvpx", "-g", "600", "-f", "webm", "pipe:1",
            ],
            stdout=handle, stderr=subprocess.PIPE, text=True, check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg setup failed: {result.stderr.strip()[:400]}")
    header = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    if set(header.stdout.split()) != {"N/A"}:
        raise RuntimeError(f"streamed WebM still has a duration: {header.stdout.strip()}")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class FrameEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.cut_clip = base / "cuts.mp4"
        cls.static_clip = base / "static.mp4"
        # Longer in seconds than the fallback cap below, so 1 fps sampling
        # would stop well before the end.
        cls.long_static_clip = base / "static-long.mp4"
        build_cut_clip(cls.cut_clip)
        build_static_clip(cls.static_clip)
        build_static_clip(cls.long_static_clip, duration=40.0, rate=2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_scene_engine_finds_cuts_with_exact_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_scene_frames(
                self.cut_clip, tmp, max_frames=100, dedup=False
            )

        self.assertEqual(meta["engine"], "scene")
        self.assertFalse(meta["fallback"])
        self.assertGreaterEqual(len(frames), extract_frames.SCENE_MIN_FRAMES)
        self.assertEqual(frames[0]["reason"], "first-frame")
        self.assertTrue(all(frame["reason"] == "scene-change" for frame in frames[1:]))
        timestamps = [frame["timestamp_seconds"] for frame in frames]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertGreater(timestamps[-1], timestamps[0])

    def test_scene_engine_falls_back_to_uniform_on_static_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_scene_frames(
                self.static_clip, tmp, max_frames=100, dedup=False
            )
            # The scene candidates set aside during the fallback are gone.
            left = sorted(entry.name for entry in Path(tmp).iterdir())

        self.assertEqual(meta["engine"], "uniform")
        self.assertTrue(meta["fallback"])
        self.assertGreaterEqual(len(frames), 1)
        self.assertTrue(all(frame["reason"] == "uniform" for frame in frames))
        self.assertEqual(left, sorted(Path(str(frame["path"])).name for frame in frames))

    def test_failed_uniform_fallback_keeps_the_engine_candidates(self) -> None:
        outcomes = {
            "raises": RuntimeError("ffmpeg frame extraction failed: no frames"),
            "empty": [([], {"deduped_count": 0, "plan": {}})],
        }
        for label, outcome in outcomes.items():
            with self.subTest(uniform=label), tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(extract_frames, "extract_frames", side_effect=outcome):
                    frames, meta = extract_frames.extract_scene_frames(
                        self.static_clip, tmp, max_frames=100, dedup=False
                    )
                left = sorted(entry.name for entry in Path(tmp).iterdir())

                self.assertEqual(meta["engine"], "scene")
                self.assertFalse(meta["fallback"])
                self.assertEqual(meta["candidate_count"], 1)
                self.assertEqual([frame["reason"] for frame in frames], ["first-frame"])
                self.assertEqual(frames[0]["timestamp_seconds"], 0.0)
                self.assertEqual(left, [Path(str(frames[0]["path"])).name])

    def test_tail_range_shorter_than_one_interval_keeps_its_frame(self) -> None:
        # The last 0.2 s of the 4 s clip; uniform sampling steps every 0.5 s.
        engines = (
            extract_frames.extract_scene_frames,
            extract_frames.extract_keyframes,
            extract_frames.extract_frames,
        )
        for engine in engines:
            with self.subTest(engine=engine.__name__), tempfile.TemporaryDirectory() as tmp:
                frames, _ = engine(self.cut_clip, tmp, start=3.8, end=4.0, dedup=False)

                self.assertEqual([frame["timestamp_seconds"] for frame in frames], [3.8])
                self.assertTrue(Path(str(frames[0]["path"])).is_file())

    def test_uniform_engine_labels_a_late_video_start_in_source_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "late.mp4"
            build_late_video_clip(clip)
            whole, _ = extract_frames.extract_frames(
                clip, Path(tmp) / "whole", fps=1, dedup=False
            )
            focused, _ = extract_frames.extract_frames(
                clip, Path(tmp) / "focused", fps=1, start=1, end=4, dedup=False
            )

        # Not 0:00 and 0:01: no video exists before 0:02.
        self.assertEqual([frame["timestamp_seconds"] for frame in whole], [2.0, 3.0, 4.0, 5.0])
        self.assertEqual([frame["timestamp_seconds"] for frame in focused], [2.0, 3.0])

    def test_dedup_collapses_static_uniform_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_scene_frames(
                self.static_clip, tmp, max_frames=100, dedup=True
            )

        self.assertTrue(meta["fallback"])
        self.assertGreaterEqual(int(meta["deduped_count"]), 1)
        self.assertEqual(len(frames), 1)

    def test_keyframe_engine_reads_forced_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_keyframes(
                self.cut_clip, tmp, max_frames=50, dedup=False
            )

        self.assertEqual(meta["engine"], "keyframe")
        self.assertFalse(meta["fallback"])
        self.assertGreaterEqual(len(frames), extract_frames.KEYFRAME_MIN)
        self.assertTrue(all(frame["reason"] == "keyframe" for frame in frames))

    def test_keyframe_engine_falls_back_when_keyframes_are_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_keyframes(
                self.static_clip, tmp, max_frames=50, dedup=False
            )

        self.assertEqual(meta["engine"], "uniform")
        self.assertTrue(meta["fallback"])
        self.assertGreaterEqual(len(frames), 1)

    def test_fallbacks_honor_focused_ranges(self) -> None:
        engines = (extract_frames.extract_scene_frames, extract_frames.extract_keyframes)
        ranges = (
            ({"duration": 2.0}, 0.0, 2.0),
            ({"start": 0.5, "end": 2.5}, 0.5, 2.5),
            ({"end": 2.0}, 0.0, 2.0),
        )
        for engine in engines:
            for kwargs, low, high in ranges:
                with self.subTest(engine=engine.__name__, **kwargs):
                    with tempfile.TemporaryDirectory() as tmp:
                        frames, meta = engine(
                            self.static_clip, tmp, max_frames=50, dedup=False, **kwargs
                        )

                    self.assertTrue(meta["fallback"])
                    self.assertEqual(meta["engine"], "uniform")
                    self.assertGreaterEqual(len(frames), 2)
                    for frame in frames:
                        self.assertGreaterEqual(frame["timestamp_seconds"], low)
                        self.assertLess(frame["timestamp_seconds"], high)

    def test_unfocused_fallback_spans_the_whole_video(self) -> None:
        engines = (extract_frames.extract_scene_frames, extract_frames.extract_keyframes)
        for engine in engines:
            # Omitted: the fallback probes the length with ffprobe.
            for extra in ({}, {"total_duration": 40.0}):
                with self.subTest(engine=engine.__name__, **extra):
                    with tempfile.TemporaryDirectory() as tmp:
                        frames, meta = engine(
                            self.long_static_clip, tmp, max_frames=10, dedup=False, **extra
                        )

                    self.assertTrue(meta["fallback"])
                    self.assertEqual(len(frames), 10)
                    # 1 fps capped at 10 frames would end near 0:09.
                    self.assertGreater(frames[-1]["timestamp_seconds"], 30.0)
                    self.assertAlmostEqual(meta["plan"]["fps"], 0.25)
                    self.assertEqual(meta["plan"]["target_frames"], 10)

    def test_fallback_spans_streamed_webm_without_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "recording.webm"
            build_streamed_webm(clip)
            # Last packet at 39.5 s; the header has no length at all.
            self.assertAlmostEqual(extract_frames.probe_duration(clip), 39.5, delta=0.6)
            frames, meta = extract_frames.extract_scene_frames(
                clip, Path(tmp) / "frames", max_frames=5, dedup=False
            )

        self.assertTrue(meta["fallback"])
        self.assertEqual(len(frames), 5)
        # 1 fps capped at 5 frames would end at 0:04.
        self.assertGreater(frames[-1]["timestamp_seconds"], 25.0)

    def test_even_sample_cap_keeps_first_and_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            all_frames, _ = extract_frames.extract_scene_frames(
                self.cut_clip, tmp, max_frames=100, dedup=False
            )
        with tempfile.TemporaryDirectory() as tmp:
            capped, meta = extract_frames.extract_scene_frames(
                self.cut_clip, tmp, max_frames=5, dedup=False
            )

        self.assertEqual(len(capped), 5)
        self.assertEqual(meta["selected_count"], 5)
        self.assertAlmostEqual(
            capped[0]["timestamp_seconds"], all_frames[0]["timestamp_seconds"], places=1
        )
        self.assertAlmostEqual(
            capped[-1]["timestamp_seconds"], all_frames[-1]["timestamp_seconds"], places=1
        )

    def test_extract_at_timestamps_pins_cue_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_at_timestamps(
                self.cut_clip,
                tmp,
                [0.2, 1.4, 99.0],
                window_start=None,
                window_end=3.9,
            )

        self.assertEqual(meta["dropped_out_of_window"], 1)
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(frame["reason"] == "transcript-cue" for frame in frames))
        self.assertTrue(all(Path(str(frame["path"])).name.startswith("cue_") for frame in frames))
        self.assertEqual(
            [frame["timestamp_seconds"] for frame in frames],
            [0.2, 1.4],
        )

    def test_uniform_engine_reports_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frames, meta = extract_frames.extract_frames(
                self.cut_clip, tmp, max_frames=10, dedup=False
            )

        self.assertEqual(meta["engine"], "uniform")
        self.assertEqual(meta["selected_count"], len(frames))
        self.assertTrue(all(frame["reason"] == "uniform" for frame in frames))


if __name__ == "__main__":
    unittest.main()
