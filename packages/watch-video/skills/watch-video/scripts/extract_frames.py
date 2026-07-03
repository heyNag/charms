#!/usr/bin/env python3
"""Extract timestamped preview frames from a video with ffmpeg.

Three engines share one candidate pipeline:

- scene:    ffmpeg scene-change selection with exact showinfo timestamps
- keyframe: decode only I-frames via -skip_frame nokey (near-instant)
- uniform:  fixed-fps sampling driven by the duration budget

Candidates flow through: extract -> perceptual dedup -> even-sample down to
the cap -> rename to timestamped filenames. Dedup and sampling delete the
files they drop, so the frame budget is spent on distinct content.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path


DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_MAX_FRAMES = 80
HARD_MAX_FRAMES = 100
# "full" detail keeps every scene change it can, but still bounded.
FULL_MAX_FRAMES = 300
MAX_FPS = 2.0
DEFAULT_WIDTH = 512
# Agent image readers reject very tall images; clamp height defensively.
MAX_READ_HEIGHT = 1998
FRAME_FORMATS = {"jpeg", "png", "webp"}
# Scene selection needs this many detected shots to be trusted; below it the
# video is effectively static (screen recording, talking head) and uniform
# sampling covers it better.
SCENE_THRESHOLD = 0.20
SCENE_MIN_FRAMES = 8
# Below this many keyframes a clip is too sparse for keyframe coverage.
KEYFRAME_MIN = 4
# Frame-delta dedup: compare DEDUP_THUMB x DEDUP_THUMB grayscale thumbnails by
# mean absolute per-pixel difference (0-255). The threshold is deliberately
# low so a one-line code diff or a slide gaining a bullet still survives.
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0
SHOWINFO_TS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def parse_time(value: str | int | float | None) -> float | None:
    """Parse SS, MM:SS, or HH:MM:SS into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None

    parts = raw.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError as exc:
        raise ValueError(f"invalid time value {value!r}") from exc
    raise ValueError(f"invalid time value {value!r}")


def parse_timestamps(value: str | None) -> list[float]:
    """Parse a comma-separated timestamp list into sorted unique seconds."""
    if not value:
        return []
    out: list[float] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        seconds = parse_time(token)
        if seconds is not None:
            out.append(float(seconds))
    return sorted(set(out))


def format_time(seconds: float | int | None) -> str:
    if seconds is None:
        return "unknown"
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def timestamp_name(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}h{minutes:02d}m{secs:02d}s"


def resolve_range(
    start: float | None,
    end: float | None,
    duration: float | None,
    total_duration: float | None = None,
) -> tuple[float | None, float | None, float | None]:
    """Return normalized (start, end, duration) values."""
    if end is not None and duration is not None:
        raise ValueError("use either --end or --duration, not both")
    if start is not None and start < 0:
        raise ValueError("--start must be non-negative")
    if end is not None and end < 0:
        raise ValueError("--end must be non-negative")
    if duration is not None and duration <= 0:
        raise ValueError("--duration must be greater than zero")

    effective_start = start
    effective_end = end
    effective_duration = duration

    if effective_duration is not None:
        effective_start = effective_start or 0.0
        effective_end = effective_start + effective_duration
    elif effective_start is not None and effective_end is not None:
        effective_duration = effective_end - effective_start
    elif effective_start is None and effective_end is not None:
        effective_start = 0.0
        effective_duration = effective_end
    elif total_duration is not None:
        effective_start = effective_start or 0.0
        effective_end = total_duration
        effective_duration = max(0.0, effective_end - effective_start)

    if (
        effective_start is not None
        and effective_end is not None
        and effective_end <= effective_start
    ):
        raise ValueError("--end must be greater than --start")

    return effective_start, effective_end, effective_duration


def capped_max_frames(max_frames: int) -> int:
    return max(1, min(int(max_frames), HARD_MAX_FRAMES))


def _plan_from_target(duration_seconds: float | None, target: int, max_frames: int) -> tuple[float, int]:
    capped = capped_max_frames(max_frames)
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0, min(capped, max(1, target))
    fps = min(MAX_FPS, max(0.001, float(target) / duration_seconds))
    frame_budget = max(1, min(capped, int(math.ceil(fps * duration_seconds))))
    return fps, frame_budget


def auto_fps_for_duration(
    duration_seconds: float | None,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> tuple[float, int]:
    """Pick FPS and target frame budget for full-video scans."""
    capped = capped_max_frames(max_frames)
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0, capped

    if duration_seconds <= 30:
        target = min(capped, max(12, int(round(duration_seconds))))
    elif duration_seconds <= 60:
        target = min(capped, 40)
    elif duration_seconds <= 180:
        target = min(capped, 60)
    elif duration_seconds <= 600:
        target = min(capped, 80)
    else:
        target = capped
    return _plan_from_target(duration_seconds, target, capped)


def auto_fps_for_focus(
    duration_seconds: float | None,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> tuple[float, int]:
    """Pick denser FPS and target frame budget for focused ranges."""
    capped = capped_max_frames(max_frames)
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0, min(capped, 12)

    if duration_seconds <= 5:
        target = min(capped, max(8, int(math.ceil(duration_seconds * 2))))
    elif duration_seconds <= 15:
        target = min(capped, max(20, int(math.ceil(duration_seconds * 2))))
    elif duration_seconds <= 30:
        target = min(capped, 60)
    elif duration_seconds <= 60:
        target = min(capped, 80)
    else:
        target = capped
    return _plan_from_target(duration_seconds, target, capped)


def expected_frame_count(
    duration_seconds: float | None,
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> int:
    if frame_interval <= 0:
        raise ValueError("--frame-interval must be greater than zero")
    capped = capped_max_frames(max_frames)
    if duration_seconds is None or duration_seconds <= 0:
        return capped
    return max(1, min(capped, int(math.ceil(duration_seconds / frame_interval)) + 1))


def resolve_frame_plan(
    duration_seconds: float | None,
    *,
    focused: bool,
    frame_mode: str = "auto",
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    fps: float | None = None,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> dict[str, object]:
    """Return uniform-sampling settings with hard caps applied."""
    capped = capped_max_frames(max_frames)
    if frame_mode not in {"auto", "interval"}:
        raise ValueError("--frame-mode must be auto or interval")
    if frame_interval <= 0:
        raise ValueError("--frame-interval must be greater than zero")
    warnings: list[str] = []

    if fps is not None:
        if fps <= 0:
            raise ValueError("--fps must be greater than zero")
        selected_fps = min(float(fps), MAX_FPS)
        if selected_fps < float(fps):
            warnings.append(f"fps capped at {MAX_FPS:g}")
        if duration_seconds is None or duration_seconds <= 0:
            target = capped
        else:
            target = max(1, min(capped, int(math.ceil(selected_fps * duration_seconds))))
        return {
            "mode": "fps",
            "fps": selected_fps,
            "interval": 1 / selected_fps,
            "target_frames": target,
            "max_frames": capped,
            "warnings": warnings,
        }

    if frame_mode == "interval":
        target = expected_frame_count(duration_seconds, frame_interval, capped)
        return {
            "mode": "interval",
            "fps": 1 / frame_interval,
            "interval": frame_interval,
            "target_frames": target,
            "max_frames": capped,
            "warnings": warnings,
        }

    selected_fps, target = (
        auto_fps_for_focus(duration_seconds, capped)
        if focused
        else auto_fps_for_duration(duration_seconds, capped)
    )
    if not focused and duration_seconds is not None and duration_seconds > 600:
        warnings.append(
            "video is longer than 10 minutes; frame coverage will be sparse - "
            "use --start/--end for a focused range or --detail full for more scene frames"
        )
    return {
        "mode": "auto",
        "fps": selected_fps,
        "interval": 1 / selected_fps,
        "target_frames": target,
        "max_frames": capped,
        "warnings": warnings,
    }


def frame_extension(frame_format: str) -> str:
    if frame_format not in FRAME_FORMATS:
        raise ValueError("--frame-format must be jpeg, png, or webp")
    return "jpg" if frame_format == "jpeg" else frame_format


def frame_mime_type(frame_format: str) -> str:
    if frame_format == "jpeg":
        return "image/jpeg"
    if frame_format == "png":
        return "image/png"
    if frame_format == "webp":
        return "image/webp"
    raise ValueError("--frame-format must be jpeg, png, or webp")


def scale_filter(width: int) -> str:
    """Downscale-only scale filter: cap width, clamp height, never upscale."""
    return (
        f"scale=w='min({int(width)},iw)':h='min({MAX_READ_HEIGHT},ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def _quality_args(frame_format: str) -> list[str]:
    if frame_format == "jpeg":
        return ["-q:v", "4"]
    if frame_format == "png":
        return ["-compression_level", "3"]
    if frame_format == "webp":
        return ["-quality", "82"]
    raise ValueError("--frame-format must be jpeg, png, or webp")


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed. fix: brew install ffmpeg")


def _cleanup_old_frames(out_path: Path) -> None:
    for old in out_path.glob("frame_*.*"):
        if old.is_file():
            old.unlink()


def _cleanup_old_cues(out_path: Path) -> None:
    for old in out_path.glob("cue_*.*"):
        if old.is_file():
            old.unlink()


def _seek_args(
    start: float | None,
    end: float | None,
    duration: float | None,
) -> tuple[list[str], list[str]]:
    """Build (pre-input, post-input) ffmpeg seek arguments."""
    pre = ["-ss", f"{start:.3f}"] if start is not None else []
    post: list[str] = []
    if duration is not None:
        post = ["-t", f"{duration:.3f}"]
    elif start is not None and end is not None:
        post = ["-t", f"{end - start:.3f}"]
    elif start is None and end is not None:
        post = ["-t", f"{end:.3f}"]
    return pre, post


def _run_ffmpeg(cmd: list[str], frame_format: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffmpeg error"
        if frame_format == "webp" and "webp" in detail.lower():
            raise RuntimeError(
                "ffmpeg frame extraction failed: WebP output requires an ffmpeg build "
                "with WebP encoder support. Try --frame-format jpeg or png."
            )
        raise RuntimeError(f"ffmpeg frame extraction failed: {detail[-1200:]}")
    return result


def _showinfo_timestamps(stderr: str) -> list[float]:
    return [float(match.group(1)) for match in SHOWINFO_TS_RE.finditer(stderr)]


def _raw_files(out_path: Path, extension: str) -> list[Path]:
    return sorted(out_path.glob(f"frame_raw_*.{extension}"))


def _frame_delta(a: bytes, b: bytes) -> float:
    """Mean absolute per-pixel difference (0-255) between two thumbnails.

    Mismatched lengths are treated as maximally different so a decode hiccup
    never collapses distinct frames.
    """
    if not a or len(a) != len(b):
        return float("inf")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _thumbnail_sequence(files: list[Path]) -> list[bytes]:
    """Decode a numbered image sequence to grayscale thumbnails in one pass.

    ffmpeg does the pixel decode (keeps this stdlib-only); the raw grayscale
    stream is sliced into one square thumbnail per frame. Fail-open: any
    ffmpeg error or byte-count mismatch returns [] so callers skip dedup
    instead of breaking extraction.
    """
    if not files:
        return []
    match = re.match(r"(.*?)(\d+)(\.[A-Za-z0-9]+)$", files[0].name)
    if match is None:
        return []
    prefix, digits, ext = match.group(1), match.group(2), match.group(3)
    pattern = str(files[0].parent / f"{prefix}%0{len(digits)}d{ext}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-start_number",
        str(int(digits)),
        "-i",
        pattern,
        "-vf",
        f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        return []
    chunk = DEDUP_THUMB * DEDUP_THUMB
    data = result.stdout
    if len(data) != chunk * len(files):
        return []
    return [data[index * chunk:(index + 1) * chunk] for index in range(len(files))]


def _dedupe_candidates(
    candidates: list[dict],
    threshold: float = DEDUP_THRESHOLD,
) -> tuple[list[dict], int]:
    """Greedily drop frames near-identical to the last kept frame.

    Comparing against the last kept frame (not the previous one) catches slow
    fades that never trip a frame-to-frame threshold. Deletes dropped files.
    Must run while the raw sequence numbering is still consecutive.
    """
    if len(candidates) <= 1:
        return candidates, 0
    thumbs = _thumbnail_sequence([candidate["raw_path"] for candidate in candidates])
    if len(thumbs) != len(candidates):
        return candidates, 0

    kept = [candidates[0]]
    last = thumbs[0]
    dropped = 0
    for candidate, thumb in zip(candidates[1:], thumbs[1:]):
        if _frame_delta(thumb, last) <= threshold:
            candidate["raw_path"].unlink(missing_ok=True)
            dropped += 1
        else:
            kept.append(candidate)
            last = thumb
    return kept, dropped


def _even_indices(count: int, n: int) -> list[int]:
    """Indices of n evenly spaced items out of count (first + last kept)."""
    if n >= count:
        return list(range(count))
    if n <= 1:
        return [0]
    return [round(index * (count - 1) / (n - 1)) for index in range(n)]


def _even_sample(candidates: list[dict], cap: int | None) -> list[dict]:
    """Thin candidates down to cap evenly (first + last kept); delete drops."""
    if cap is None or cap >= len(candidates):
        return candidates
    keep = set(_even_indices(len(candidates), max(1, cap)))
    selected: list[dict] = []
    for index, candidate in enumerate(candidates):
        if index in keep:
            selected.append(candidate)
        else:
            candidate["raw_path"].unlink(missing_ok=True)
    return selected


def _finalize_frames(candidates: list[dict], frame_format: str) -> list[dict[str, object]]:
    """Rename surviving raw files to timestamped names and build frame dicts."""
    extension = frame_extension(frame_format)
    mime_type = frame_mime_type(frame_format)
    frames: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates, start=1):
        timestamp = float(candidate["timestamp_seconds"])
        final = candidate["raw_path"].with_name(
            f"frame_{index:04d}_{timestamp_name(timestamp)}.{extension}"
        )
        candidate["raw_path"].rename(final)
        frames.append(
            {
                "index": index,
                "timestamp_seconds": round(timestamp, 3),
                "timestamp": format_time(timestamp),
                "path": str(final),
                "format": frame_format,
                "mime_type": mime_type,
                "reason": candidate.get("reason", "selected"),
            }
        )
    return frames


def merge_frames(primary: list[dict], pinned: list[dict]) -> list[dict]:
    """Combine frame lists chronologically and reindex from 1.

    Pinned frames (transcript cues) are never dropped here; the cap is
    enforced upstream by reserving budget for them.
    """
    merged = sorted([*primary, *pinned], key=lambda frame: frame["timestamp_seconds"])
    for index, frame in enumerate(merged, start=1):
        frame["index"] = index
    return merged


def extract_frames(
    source: str | Path,
    out_dir: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    frame_mode: str = "auto",
    fps: float | None = None,
    max_frames: int = DEFAULT_MAX_FRAMES,
    width: int = DEFAULT_WIDTH,
    frame_format: str = "jpeg",
    timestamp_offset: float | None = None,
    dedup: bool = True,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Uniform engine: fixed-fps sampling with duration-aware budgets."""
    _require_ffmpeg()
    start, end, duration = resolve_range(start, end, duration)
    extension = frame_extension(frame_format)
    plan = resolve_frame_plan(
        duration,
        focused=start is not None or end is not None or duration is not None,
        frame_mode=frame_mode,
        frame_interval=frame_interval,
        fps=fps,
        max_frames=max_frames,
    )
    selected_fps = float(plan["fps"])
    target_frames = int(plan["target_frames"])

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_frames(out_path)

    raw_pattern = str(out_path / f"frame_raw_%04d.{extension}")
    pre_seek, post_seek = _seek_args(start, end, duration)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *pre_seek,
        "-i",
        str(Path(source).expanduser()),
        *post_seek,
        "-vf",
        f"fps={selected_fps:g},{scale_filter(width)}",
        "-frames:v",
        str(target_frames),
        *_quality_args(frame_format),
        raw_pattern,
    ]
    _run_ffmpeg(cmd, frame_format)

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + (index / selected_fps),
            "reason": "uniform",
        }
        for index, raw_file in enumerate(_raw_files(out_path, extension))
    ]
    candidate_count = len(candidates)
    dropped = 0
    if dedup:
        candidates, dropped = _dedupe_candidates(candidates)
    frames = _finalize_frames(candidates, frame_format)
    meta = {
        "engine": "uniform",
        "candidate_count": candidate_count,
        "deduped_count": dropped,
        "selected_count": len(frames),
        "fallback": False,
    }
    return frames, meta


def extract_keyframes(
    source: str | Path,
    out_dir: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    width: int = DEFAULT_WIDTH,
    frame_format: str = "jpeg",
    max_frames: int = 50,
    timestamp_offset: float | None = None,
    dedup: bool = True,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keyframe engine: decode only I-frames (the near-instant tier).

    Encoders emit keyframes at scene cuts, so these already approximate
    "distinct moments" without decoding every frame. Too few keyframes means
    a very short or oddly encoded clip; fall back to uniform sampling.
    """
    _require_ffmpeg()
    start, end, duration = resolve_range(start, end, duration)
    extension = frame_extension(frame_format)
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_frames(out_path)

    raw_pattern = str(out_path / f"frame_raw_%04d.{extension}")
    pre_seek, post_seek = _seek_args(start, end, duration)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-y",
        *pre_seek,
        "-skip_frame",
        "nokey",
        "-i",
        str(Path(source).expanduser()),
        *post_seek,
        "-vf",
        f"{scale_filter(width)},showinfo",
        "-vsync",
        "vfr",
        *_quality_args(frame_format),
        raw_pattern,
    ]
    result = _run_ffmpeg(cmd, frame_format)

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    exact = _showinfo_timestamps(result.stderr)
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + (exact[index] if index < len(exact) else 0.0),
            "reason": "keyframe",
        }
        for index, raw_file in enumerate(_raw_files(out_path, extension))
    ]

    if len(candidates) < KEYFRAME_MIN:
        found = len(candidates)
        for candidate in candidates:
            candidate["raw_path"].unlink(missing_ok=True)
        frames, uniform_meta = extract_frames(
            source,
            out_dir,
            start=start,
            end=end,
            duration=duration,
            frame_mode="auto",
            max_frames=max_frames,
            width=width,
            frame_format=frame_format,
            timestamp_offset=timestamp_offset,
            dedup=dedup,
        )
        return frames, {
            "engine": "uniform",
            "candidate_count": found,
            "deduped_count": uniform_meta["deduped_count"],
            "selected_count": len(frames),
            "fallback": True,
        }

    candidate_count = len(candidates)
    dropped = 0
    if dedup:
        candidates, dropped = _dedupe_candidates(candidates)
    candidates = _even_sample(candidates, max_frames)
    frames = _finalize_frames(candidates, frame_format)
    return frames, {
        "engine": "keyframe",
        "candidate_count": candidate_count,
        "deduped_count": dropped,
        "selected_count": len(frames),
        "fallback": False,
    }


def extract_scene_frames(
    source: str | Path,
    out_dir: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    width: int = DEFAULT_WIDTH,
    frame_format: str = "jpeg",
    max_frames: int = DEFAULT_MAX_FRAMES,
    timestamp_offset: float | None = None,
    dedup: bool = True,
    scene_threshold: float = SCENE_THRESHOLD,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Scene engine: first frame plus every scene change, then thin to cap.

    Detection is uncapped across the whole range so coverage spans the full
    clip (capping detection would keep only the earliest cuts). This costs a
    full decode; use the keyframe engine when speed matters more. Videos with
    fewer than SCENE_MIN_FRAMES detected shots fall back to uniform sampling.
    """
    _require_ffmpeg()
    start, end, duration = resolve_range(start, end, duration)
    extension = frame_extension(frame_format)
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_frames(out_path)

    raw_pattern = str(out_path / f"frame_raw_%04d.{extension}")
    pre_seek, post_seek = _seek_args(start, end, duration)
    select = f"select='eq(n\\,0)+gt(scene\\,{scene_threshold:g})'"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-y",
        *pre_seek,
        "-i",
        str(Path(source).expanduser()),
        *post_seek,
        "-vf",
        f"{select},{scale_filter(width)},showinfo",
        "-vsync",
        "vfr",
        *_quality_args(frame_format),
        raw_pattern,
    ]
    result = _run_ffmpeg(cmd, frame_format)

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    exact = _showinfo_timestamps(result.stderr)
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + (exact[index] if index < len(exact) else 0.0),
            "reason": "first-frame" if index == 0 else "scene-change",
        }
        for index, raw_file in enumerate(_raw_files(out_path, extension))
    ]

    if len(candidates) < SCENE_MIN_FRAMES:
        found = len(candidates)
        for candidate in candidates:
            candidate["raw_path"].unlink(missing_ok=True)
        frames, uniform_meta = extract_frames(
            source,
            out_dir,
            start=start,
            end=end,
            duration=duration,
            frame_mode="auto",
            max_frames=max_frames,
            width=width,
            frame_format=frame_format,
            timestamp_offset=timestamp_offset,
            dedup=dedup,
        )
        return frames, {
            "engine": "uniform",
            "candidate_count": found,
            "deduped_count": uniform_meta["deduped_count"],
            "selected_count": len(frames),
            "fallback": True,
        }

    candidate_count = len(candidates)
    dropped = 0
    if dedup:
        candidates, dropped = _dedupe_candidates(candidates)
    candidates = _even_sample(candidates, max_frames)
    frames = _finalize_frames(candidates, frame_format)
    return frames, {
        "engine": "scene",
        "candidate_count": candidate_count,
        "deduped_count": dropped,
        "selected_count": len(frames),
        "fallback": False,
    }


def cues_in_window(
    timestamps: list[float],
    window_start: float | None,
    window_end: float | None,
) -> tuple[list[float], int]:
    """Filter cue timestamps to the focus window; return (kept, dropped)."""
    low = window_start if window_start is not None else 0.0
    high = window_end if window_end is not None else float("inf")
    requested = sorted(set(round(float(value), 2) for value in timestamps))
    kept = [value for value in requested if low <= value <= high]
    return kept, len(requested) - len(kept)


def extract_at_timestamps(
    source: str | Path,
    out_dir: str | Path,
    timestamps: list[float],
    *,
    width: int = DEFAULT_WIDTH,
    frame_format: str = "jpeg",
    max_frames: int | None = None,
    window_start: float | None = None,
    window_end: float | None = None,
    media_time_offset: float = 0.0,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Grab exactly one frame at each requested absolute timestamp.

    Used for transcript cues ("look here", "as you can see") that visual
    selection can miss. Timestamps are absolute source seconds; when the
    media file is a pre-trimmed section download, media_time_offset maps
    them onto the trimmed file. Files use a cue_ prefix so they coexist
    with engine frame_ output.
    """
    _require_ffmpeg()
    extension = frame_extension(frame_format)
    mime_type = frame_mime_type(frame_format)
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_cues(out_path)

    in_window, dropped = cues_in_window(timestamps, window_start, window_end)
    if max_frames is not None and len(in_window) > max_frames:
        in_window = [in_window[index] for index in _even_indices(len(in_window), max_frames)]

    frames: list[dict[str, object]] = []
    for value in in_window:
        seek = max(0.0, value - media_time_offset)
        path = out_path / f"cue_{len(frames):04d}_{timestamp_name(value)}.{extension}"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{seek:.3f}",
            "-i",
            str(Path(source).expanduser()),
            "-frames:v",
            "1",
            "-vf",
            scale_filter(width),
            *_quality_args(frame_format),
            str(path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        if result.returncode == 0 and path.exists():
            frames.append(
                {
                    "index": len(frames) + 1,
                    "timestamp_seconds": round(value, 3),
                    "timestamp": format_time(value),
                    "path": str(path),
                    "format": frame_format,
                    "mime_type": mime_type,
                    "reason": "transcript-cue",
                }
            )

    meta = {
        "engine": "timestamps",
        "requested_count": len(set(round(float(value), 2) for value in timestamps)),
        "selected_count": len(frames),
        "dropped_out_of_window": dropped,
    }
    return frames, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract timestamped frames with ffmpeg.")
    parser.add_argument("source", help="Video path or ffmpeg-readable source")
    parser.add_argument("out_dir", help="Directory for extracted frames")
    parser.add_argument("--start", help="Start time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--end", help="End time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--duration", help="Duration as seconds or time string")
    parser.add_argument("--engine", choices=["uniform", "scene", "keyframe"], default="uniform")
    parser.add_argument("--frame-mode", choices=["auto", "interval"], default="auto")
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between frames in interval mode (default: 5)",
    )
    parser.add_argument("--fps", type=float, help="Explicit frames per second override")
    parser.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Frame width in pixels")
    parser.add_argument("--frame-format", choices=sorted(FRAME_FORMATS), default="jpeg")
    parser.add_argument("--no-dedup", action="store_true", help="Keep near-duplicate frames")
    args = parser.parse_args()

    try:
        common = {
            "start": parse_time(args.start),
            "end": parse_time(args.end),
            "duration": parse_time(args.duration),
            "width": args.width,
            "frame_format": args.frame_format,
            "dedup": not args.no_dedup,
        }
        if args.engine == "scene":
            frames, meta = extract_scene_frames(
                args.source, args.out_dir, max_frames=args.max_frames, **common
            )
        elif args.engine == "keyframe":
            frames, meta = extract_keyframes(
                args.source, args.out_dir, max_frames=args.max_frames, **common
            )
        else:
            frames, meta = extract_frames(
                args.source,
                args.out_dir,
                frame_mode=args.frame_mode,
                frame_interval=args.frame_interval,
                fps=args.fps,
                max_frames=args.max_frames,
                **common,
            )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"frames": frames, "meta": meta}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
