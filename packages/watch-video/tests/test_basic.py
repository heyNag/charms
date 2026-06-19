from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def test_modules_importable() -> None:
    assert importlib.import_module("watch")
    assert importlib.import_module("extract_frames")
    assert importlib.import_module("groq_transcribe")


def test_parse_time_and_format_time() -> None:
    extract_frames = importlib.import_module("extract_frames")

    assert extract_frames.parse_time("75") == 75.0
    assert extract_frames.parse_time("01:15") == 75.0
    assert extract_frames.parse_time("1:02:03") == 3723.0
    assert extract_frames.format_time(75) == "01:15"
    assert extract_frames.format_time(3723) == "1:02:03"


def test_resolve_range_duration() -> None:
    extract_frames = importlib.import_module("extract_frames")

    assert extract_frames.resolve_range(10, None, 5) == (10, 15, 5)
    assert extract_frames.resolve_range(None, 30, None) == (0.0, 30, 30)
    assert extract_frames.resolve_range(10, 30, None) == (10, 30, 20)
    with pytest.raises(ValueError, match="either --end or --duration"):
        extract_frames.resolve_range(0, 10, 5)


def test_expected_frame_count_is_capped() -> None:
    extract_frames = importlib.import_module("extract_frames")

    assert extract_frames.expected_frame_count(60, frame_interval=5, max_frames=80) == 13
    assert extract_frames.expected_frame_count(10_000, frame_interval=1, max_frames=500) == 100
    with pytest.raises(ValueError, match="frame-interval"):
        extract_frames.expected_frame_count(60, frame_interval=0)


def test_safe_run_id_is_stable_shape() -> None:
    watch = importlib.import_module("watch")

    run_id = watch.safe_run_id("https://www.youtube.com/watch?v=abc123")
    assert "youtube.com" in run_id
    assert run_id.endswith(watch.safe_run_id("https://www.youtube.com/watch?v=abc123")[-8:])
    assert "?" not in run_id


def test_create_run_dir_does_not_overwrite(tmp_path, monkeypatch) -> None:
    watch = importlib.import_module("watch")
    monkeypatch.setattr(watch, "safe_run_id", lambda _source: "fixed-run")

    first = watch.create_run_dir(tmp_path, "source.mp4")
    second = watch.create_run_dir(tmp_path, "source.mp4")

    assert first.name == "fixed-run"
    assert second.name == "fixed-run-01"
    assert first.exists()
    assert second.exists()


def test_pick_caption_prefers_english(tmp_path) -> None:
    watch = importlib.import_module("watch")
    (tmp_path / "video.fr.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (tmp_path / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")

    assert watch.pick_caption(tmp_path).name == "video.en.vtt"


def test_segments_from_response_offsets() -> None:
    groq = importlib.import_module("groq_transcribe")

    data = {"segments": [{"start": 1, "end": 2.5, "text": " hello "}]}
    assert groq.segments_from_response(data, offset_seconds=10) == [
        {"start": 11.0, "end": 12.5, "text": "hello"}
    ]


def test_transcript_markdown() -> None:
    watch = importlib.import_module("watch")

    text = watch.transcript_markdown([{"start": 5, "end": 6, "text": "hello"}])
    assert text == "[00:05] hello"


def test_parse_vtt_and_filter_range(tmp_path) -> None:
    watch = importlib.import_module("watch")
    vtt = tmp_path / "captions.vtt"
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
    assert segments == [
        {"start": 1.0, "end": 2.0, "text": "hello world"},
        {"start": 3.0, "end": 4.0, "text": "next line"},
    ]
    assert watch.filter_segments(segments, 2.5, 3.5) == [
        {"start": 3.0, "end": 4.0, "text": "next line"}
    ]


def test_parse_vtt_collapses_rolling_auto_captions(tmp_path) -> None:
    watch = importlib.import_module("watch")
    vtt = tmp_path / "captions.vtt"
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

    assert watch.parse_vtt(vtt) == [
        {
            "start": 1.0,
            "end": 4.0,
            "text": "Today I'm going to explain the different levels of building",
        },
        {"start": 5.0, "end": 6.0, "text": "Next idea starts here"},
    ]


def test_build_report_includes_artifact_paths(tmp_path) -> None:
    watch = importlib.import_module("watch")
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
    )

    assert f"`{tmp_path / 'transcript.json'}`" in report
    assert f"`{tmp_path / 'transcript.md'}`" in report
    assert f"`{tmp_path / 'frames'}`" in report
    assert str(tmp_path / "frames" / "frame.jpg") in report


def test_groq_missing_key_error(monkeypatch, tmp_path) -> None:
    groq = importlib.import_module("groq_transcribe")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"placeholder")

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        groq.transcribe_audio(audio)
