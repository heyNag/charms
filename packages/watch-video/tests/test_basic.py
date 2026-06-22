from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))


class WatchVideoBasicTests(unittest.TestCase):
    def test_modules_importable(self) -> None:
        self.assertTrue(importlib.import_module("watch"))
        self.assertTrue(importlib.import_module("extract_frames"))
        self.assertTrue(importlib.import_module("groq_transcribe"))
        self.assertTrue(importlib.import_module("doctor"))

    def test_parse_time_and_format_time(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        self.assertEqual(extract_frames.parse_time("75"), 75.0)
        self.assertEqual(extract_frames.parse_time("01:15"), 75.0)
        self.assertEqual(extract_frames.parse_time("1:02:03"), 3723.0)
        self.assertEqual(extract_frames.format_time(75), "01:15")
        self.assertEqual(extract_frames.format_time(3723), "1:02:03")

    def test_resolve_range_duration(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        self.assertEqual(extract_frames.resolve_range(10, None, 5), (10, 15, 5))
        self.assertEqual(extract_frames.resolve_range(None, 30, None), (0.0, 30, 30))
        self.assertEqual(extract_frames.resolve_range(10, 30, None), (10, 30, 20))
        with self.assertRaisesRegex(ValueError, "either --end or --duration"):
            extract_frames.resolve_range(0, 10, 5)

    def test_expected_frame_count_is_capped(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        self.assertEqual(
            extract_frames.expected_frame_count(60, frame_interval=5, max_frames=80),
            13,
        )
        self.assertEqual(
            extract_frames.expected_frame_count(10_000, frame_interval=1, max_frames=500),
            100,
        )
        with self.assertRaisesRegex(ValueError, "frame-interval"):
            extract_frames.expected_frame_count(60, frame_interval=0)

    def test_auto_frame_budget_short_and_long(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        fps, target = extract_frames.auto_fps_for_duration(30, max_frames=80)
        self.assertEqual(fps, 1.0)
        self.assertEqual(target, 30)

        long_plan = extract_frames.resolve_frame_plan(
            1200,
            focused=False,
            frame_mode="auto",
            max_frames=500,
        )
        self.assertEqual(long_plan["target_frames"], 100)
        self.assertEqual(long_plan["max_frames"], 100)
        self.assertIn("sparse", " ".join(long_plan["warnings"]))

    def test_auto_frame_budget_focus_is_denser(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        focused = extract_frames.resolve_frame_plan(30, focused=True, frame_mode="auto", max_frames=80)
        full = extract_frames.resolve_frame_plan(30, focused=False, frame_mode="auto", max_frames=80)

        self.assertGreater(focused["target_frames"], full["target_frames"])
        self.assertLessEqual(focused["fps"], 2.0)

    def test_frame_plan_caps_fps_and_preserves_interval_mode(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        fps_plan = extract_frames.resolve_frame_plan(
            10,
            focused=True,
            frame_mode="auto",
            fps=10,
            max_frames=500,
        )
        self.assertEqual(fps_plan["fps"], 2.0)
        self.assertEqual(fps_plan["target_frames"], 20)
        self.assertEqual(fps_plan["max_frames"], 100)

        interval_plan = extract_frames.resolve_frame_plan(
            60,
            focused=False,
            frame_mode="interval",
            frame_interval=5,
            max_frames=80,
        )
        self.assertEqual(interval_plan["mode"], "interval")
        self.assertEqual(interval_plan["target_frames"], 13)

    def test_frame_format_helpers(self) -> None:
        extract_frames = importlib.import_module("extract_frames")

        self.assertEqual(extract_frames.frame_extension("jpeg"), "jpg")
        self.assertEqual(extract_frames.frame_extension("png"), "png")
        self.assertEqual(extract_frames.frame_mime_type("webp"), "image/webp")
        with self.assertRaisesRegex(ValueError, "frame-format"):
            extract_frames.frame_extension("gif")

    def test_safe_run_id_is_stable_shape(self) -> None:
        watch = importlib.import_module("watch")

        run_id = watch.safe_run_id("https://www.youtube.com/watch?v=abc123")
        self.assertIn("youtube.com", run_id)
        self.assertTrue(run_id.endswith(watch.safe_run_id("https://www.youtube.com/watch?v=abc123")[-8:]))
        self.assertNotIn("?", run_id)

    def test_create_run_dir_does_not_overwrite(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(watch, "safe_run_id", lambda _source: "fixed-run"):
                first = watch.create_run_dir(tmp_path, "source.mp4")
                second = watch.create_run_dir(tmp_path, "source.mp4")

            self.assertEqual(first.name, "fixed-run")
            self.assertEqual(second.name, "fixed-run-01")
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_pick_caption_prefers_english(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "video.fr.vtt").write_text("WEBVTT\n", encoding="utf-8")
            (tmp_path / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")

            self.assertEqual(watch.pick_caption(tmp_path).name, "video.en.vtt")

    def test_subtitle_language_selector_allows_fallback_tracks(self) -> None:
        watch = importlib.import_module("watch")

        self.assertIn("en", watch.SUBTITLE_LANGS)
        self.assertIn("all", watch.SUBTITLE_LANGS)
        self.assertIn("-live_chat", watch.SUBTITLE_LANGS)

    def test_pick_caption_prefers_english_even_when_auto(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "video.fr.vtt").write_text("WEBVTT\n", encoding="utf-8")
            (tmp_path / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
            raw_info = {
                "subtitles": {"fr": [{}]},
                "automatic_captions": {"en": [{}]},
            }

            caption = watch.pick_caption_info(tmp_path, raw_info)

        self.assertEqual(caption["language"], "en")
        self.assertEqual(caption["caption_type"], "auto")

    def test_download_section_for_finite_ranges(self) -> None:
        watch = importlib.import_module("watch")

        self.assertEqual(watch.download_section_for_args(None, None, 30), "*00:00-00:30")
        self.assertEqual(watch.download_section_for_args(60, 90, None), "*00:01:00-00:01:30")
        self.assertEqual(watch.download_section_for_args(60, None, 30), "*00:01:00-00:01:30")
        self.assertEqual(watch.download_section_for_args(None, 90, None), "*00:00-00:01:30")
        self.assertIsNone(watch.download_section_for_args(60, None, None))
        self.assertIsNone(watch.download_section_for_args(None, None, None))
        with self.assertRaisesRegex(ValueError, "either --end or --duration"):
            watch.download_section_for_args(0, 10, 5)

    def test_segments_from_response_offsets(self) -> None:
        groq = importlib.import_module("groq_transcribe")

        data = {"segments": [{"start": 1, "end": 2.5, "text": " hello "}]}
        self.assertEqual(
            groq.segments_from_response(data, offset_seconds=10),
            [{"start": 11.0, "end": 12.5, "text": "hello"}],
        )

    def test_transcript_markdown(self) -> None:
        watch = importlib.import_module("watch")

        text = watch.transcript_markdown([{"start": 5, "end": 6, "text": "hello"}])
        self.assertEqual(text, "[00:05] hello")

    def test_parse_vtt_and_filter_range(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            vtt = Path(tmp) / "captions.vtt"
            vtt.write_text(
                """WEBVTT

00:00:01.000 --> 00:00:02.000
<c>hello</c> world

00:00:03.000 --> 00:00:04.000
next line
""",
                encoding="utf-8",
            )

            segments = watch.parse_vtt(vtt)

        self.assertEqual(
            segments,
            [
                {"start": 1.0, "end": 2.0, "text": "hello world"},
                {"start": 3.0, "end": 4.0, "text": "next line"},
            ],
        )
        self.assertEqual(
            watch.filter_segments(segments, 2.5, 3.5),
            [{"start": 3.0, "end": 4.0, "text": "next line"}],
        )

    def test_caption_coverage_flags_low_coverage(self) -> None:
        watch = importlib.import_module("watch")

        segments = [{"start": 0, "end": 10, "text": "short"}]

        self.assertEqual(watch.transcript_coverage_seconds(segments), 10.0)
        self.assertEqual(watch.caption_coverage_ratio(segments, 100), 0.1)
        self.assertTrue(watch.captions_are_insufficient(segments, 100))
        self.assertFalse(watch.captions_are_insufficient(segments, 20))

    def test_parse_vtt_collapses_rolling_auto_captions(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            vtt = Path(tmp) / "captions.vtt"
            vtt.write_text(
                """WEBVTT

00:00:01.000 --> 00:00:02.000
Today I'm going to explain the different

00:00:02.000 --> 00:00:03.000
Today I'm going to explain the different levels of building

00:00:03.000 --> 00:00:04.000
levels of building

00:00:05.000 --> 00:00:06.000
Next idea starts here
""",
                encoding="utf-8",
            )

            segments = watch.parse_vtt(vtt)

        self.assertEqual(
            segments,
            [
                {
                    "start": 1.0,
                    "end": 4.0,
                    "text": "Today I'm going to explain the different levels of building",
                },
                {"start": 5.0, "end": 6.0, "text": "Next idea starts here"},
            ],
        )

    def test_build_report_includes_artifact_paths(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "audio.mp3"
            audio.write_bytes(b"audio")

            report = watch.build_report(
                source="source.mp4",
                run_dir=tmp_path,
                metadata={"source_info": {"title": "Demo"}, "probe": {"duration_seconds": 30}},
                clip_start=0,
                clip_end=30,
                audio_path=audio,
                audio_error=None,
                transcript_source="native captions",
                transcript_segments=[{"start": 1, "end": 2, "text": "hello"}],
                frames=[{"path": str(tmp_path / "frames" / "frame.jpg"), "timestamp": "00:01"}],
                errors=[],
                frame_plan={
                    "mode": "auto",
                    "fps": 1.0,
                    "interval": 1.0,
                    "target_frames": 30,
                    "max_frames": 80,
                },
                mode="tutorial",
            )

            self.assertIn(f"`{tmp_path / 'transcript.json'}`", report)
            self.assertIn(f"`{tmp_path / 'transcript.md'}`", report)
            self.assertIn(f"`{tmp_path / 'frames'}`", report)
            self.assertIn(str(tmp_path / "frames" / "frame.jpg"), report)
            self.assertIn("## Implementation Checklist", report)
            self.assertIn("## Frame Plan", report)

    def test_report_modes_include_expected_sections(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "audio.mp3"
            audio.write_bytes(b"audio")
            base = {
                "source": "source.mp4",
                "run_dir": tmp_path,
                "metadata": {"source_info": {"title": "Demo"}, "probe": {}},
                "clip_start": None,
                "clip_end": None,
                "audio_path": audio,
                "audio_error": None,
                "transcript_source": "none",
                "transcript_segments": [],
                "frames": [],
                "errors": [],
            }

            ui_bug = watch.build_report(**base, mode="ui-bug")
            notes = watch.build_report(**base, mode="notes")

        self.assertIn("## Observed Symptom", ui_bug)
        self.assertIn("## TL;DR", notes)

    def test_cleanup_artifacts_keeps_frames_by_default(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            media = tmp_path / "media"
            frames = tmp_path / "frames"
            audio = tmp_path / "audio.mp3"
            media.mkdir()
            frames.mkdir()
            audio.write_bytes(b"audio")

            removed = watch.cleanup_artifacts(
                media_dir=media,
                audio_path=audio,
                frames_dir=frames,
                cleanup=True,
                cleanup_frames=False,
            )

            self.assertFalse(media.exists())
            self.assertFalse(audio.exists())
            self.assertTrue(frames.exists())
            self.assertIn(str(media), removed)

    def test_cleanup_frames_requires_cleanup(self) -> None:
        watch = importlib.import_module("watch")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaisesRegex(ValueError, "cleanup-frames"):
                watch.cleanup_artifacts(
                    media_dir=tmp_path / "media",
                    audio_path=tmp_path / "audio.mp3",
                    frames_dir=tmp_path / "frames",
                    cleanup=False,
                    cleanup_frames=True,
                )

    def test_groq_retry_helpers(self) -> None:
        groq = importlib.import_module("groq_transcribe")

        self.assertTrue(
            groq.should_retry_http(
                429,
                attempt=1,
                max_attempts=4,
                retry_429_count=0,
                max_429_retries=2,
            )
        )
        self.assertFalse(
            groq.should_retry_http(
                401,
                attempt=1,
                max_attempts=4,
                retry_429_count=0,
                max_429_retries=2,
            )
        )
        self.assertEqual(groq.parse_retry_after("3"), 3.0)
        self.assertGreater(groq.retry_delay(3), groq.retry_delay(1))

    def test_doctor_key_shape_helpers(self) -> None:
        doctor = importlib.import_module("doctor")

        self.assertFalse(doctor.key_shape_status(None)["ok"])
        self.assertFalse(doctor.key_shape_status("abc")["ok"])
        self.assertTrue(doctor.key_shape_status("gsk_" + "x" * 30)["ok"])

    def test_groq_missing_key_error(self) -> None:
        groq = importlib.import_module("groq_transcribe")

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"placeholder")

            env = dict(os.environ)
            env.pop("GROQ_API_KEY", None)
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(RuntimeError, "GROQ_API_KEY is not set"):
                    groq.transcribe_audio(audio)


if __name__ == "__main__":
    unittest.main()
