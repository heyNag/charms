#!/usr/bin/env python3
"""Extract timestamped preview frames from a video with ffmpeg.

Three sampled-frame engines share one candidate pipeline:

- scene:    ffmpeg scene-change selection
- keyframe: decode I-frames first; fall back to uniform below four keyframes
- uniform:  fixed-fps sampling driven by the duration budget

Every engine labels frames with original-frame showinfo pts_time, so a video
stream that starts after 0:00 keeps absolute source time. Scene and keyframe
candidates are deduplicated before evenly thinning to the cap. Uniform
sampling keeps the explicit rate/cap before dedup. Scene coverage checks and
pinned transcript-cue frames retain their temporal anchors through dedup.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import re
import shutil
import subprocess
import tempfile
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
# RGB keeps color-only changes that equal-brightness grayscale thumbnails lose.
# Small text changes can still disappear at this thumbnail size.
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0
SHOWINFO_TS_RE = re.compile(r"pts_time:([^\s]+)")
# A small reserved budget covers quiet spans in otherwise cut-heavy footage.
# Coverage is coarse evidence, not a guarantee of capturing brief events.
SCENE_COVERAGE_MIN_INTERVAL = 10.0
SCENE_COVERAGE_MAX_FRAMES = 20


def _seconds(value: float | None, label: str, *, positive: bool = False) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite and non-negative") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        bound = "greater than zero" if positive else "non-negative"
        raise ValueError(f"{label} must be finite and {bound}")
    return number


def parse_time(value: str | int | float | None) -> float | None:
    """Parse finite non-negative SS, MM:SS, or HH:MM:SS into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _seconds(value, "time")
    raw = str(value).strip()
    if not raw:
        return None

    parts = raw.split(":")
    try:
        if 1 <= len(parts) <= 3:
            fields = [float(part) for part in parts]
            if any(not math.isfinite(part) or part < 0 for part in fields):
                raise ValueError()
            if len(fields) > 1 and (
                any(part >= 60 for part in fields[1:])
                or any(not part.is_integer() for part in fields[:-1])
            ):
                raise ValueError()
            return _seconds(sum(part * 60 ** index for index, part in enumerate(reversed(fields))), "time")
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
    start = _seconds(start, "--start")
    end = _seconds(end, "--end")
    duration = _seconds(duration, "--duration", positive=True)
    total_duration = _seconds(total_duration, "source duration")
    if end is not None and duration is not None:
        raise ValueError("use either --end or --duration, not both")
    effective_start = start
    effective_end = end
    effective_duration = duration

    if effective_duration is not None:
        effective_start = effective_start or 0.0
        effective_end = _seconds(effective_start + effective_duration, "range end")
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
    duration_seconds = _seconds(duration_seconds, "duration")
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
    duration_seconds = _seconds(duration_seconds, "duration")
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
    duration_seconds = _seconds(duration_seconds, "duration")
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
    duration_seconds = _seconds(duration_seconds, "duration")
    frame_interval = _seconds(frame_interval, "--frame-interval", positive=True)
    capped = capped_max_frames(max_frames)
    if duration_seconds is None or duration_seconds <= 0:
        return capped
    return max(1, min(capped, int(math.ceil(duration_seconds / frame_interval)) + 1))


def _coverage_warning(
    duration_seconds: float | None,
    fps: float,
    capped: int,
    range_start: float,
    lower_hint: str,
    max_frames_at_limit: bool,
) -> str | None:
    """Warn when an explicit sampling rate runs out of frames before the range ends.

    Frames sit at range_start + k / fps for every k / fps inside the range;
    past the cap the rest of the range gets none.
    """
    if duration_seconds is None or duration_seconds <= 0:
        return None
    if int(math.ceil(fps * duration_seconds)) <= capped:
        return None
    # Floor the last frame's label (49.5 s reads 00:49) so it never rounds up
    # onto the range end; the epsilon absorbs k / fps landing just under a
    # whole second.
    last = max(range_start, math.floor(range_start + (capped - 1) / fps + 1e-6))
    raisable = capped < HARD_MAX_FRAMES and not max_frames_at_limit
    hint = "raise --max-frames" if raisable else "narrow --start/--end"
    return (
        f"frames cover only {format_time(range_start)}-{format_time(last)} of the "
        f"{format_time(range_start)}-{format_time(range_start + duration_seconds)} range; "
        f"{lower_hint} or {hint}"
    )


def resolve_frame_plan(
    duration_seconds: float | None,
    *,
    focused: bool,
    frame_mode: str = "auto",
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    fps: float | None = None,
    max_frames: int = DEFAULT_MAX_FRAMES,
    range_start: float = 0.0,
    max_frames_at_limit: bool = False,
    warn_coverage: bool = True,
) -> dict[str, object]:
    """Return uniform-sampling settings with hard caps applied.

    range_start is the absolute source time of the range's first frame; it
    only labels the coverage warning. max_frames_at_limit means a higher
    --max-frames cannot raise this budget, so that warning says to narrow the
    range instead. warn_coverage=False leaves the warning out of a plan made
    before any frames are sampled.
    """
    duration_seconds = _seconds(duration_seconds, "duration")
    frame_interval = _seconds(frame_interval, "--frame-interval", positive=True)
    fps = _seconds(fps, "--fps", positive=True)
    range_start = _seconds(range_start, "range start")
    capped = capped_max_frames(max_frames)
    if frame_mode not in {"auto", "interval"}:
        raise ValueError("--frame-mode must be auto or interval")
    warnings: list[str] = []

    if fps is not None:
        selected_fps = min(float(fps), MAX_FPS)
        if selected_fps < float(fps):
            warnings.append(f"fps capped at {MAX_FPS:g}")
        if duration_seconds is None or duration_seconds <= 0:
            target = capped
        else:
            target = max(1, min(capped, int(math.ceil(selected_fps * duration_seconds))))
        coverage = _coverage_warning(
            duration_seconds, selected_fps, capped, range_start, "lower --fps",
            max_frames_at_limit,
        )
        if coverage and warn_coverage:
            warnings.append(coverage)
        return {
            "mode": "fps",
            "fps": selected_fps,
            "interval": 1 / selected_fps,
            "target_frames": target,
            "max_frames": capped,
            "warnings": warnings,
        }

    if frame_mode == "interval":
        interval = max(float(frame_interval), 1 / MAX_FPS)
        if interval > frame_interval:
            warnings.append(f"fps capped at {MAX_FPS:g} (frame interval raised to {interval:g}s)")
        target = expected_frame_count(duration_seconds, interval, capped)
        coverage = _coverage_warning(
            duration_seconds, 1 / interval, capped, range_start, "raise --frame-interval",
            max_frames_at_limit,
        )
        if coverage and warn_coverage:
            warnings.append(coverage)
        return {
            "mode": "interval",
            "fps": 1 / interval,
            "interval": interval,
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
    if not isinstance(width, int) or isinstance(width, bool) or width < 2:
        raise ValueError("--resolution must be an integer of at least 2 pixels")
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


@functools.lru_cache(maxsize=1)
def _vfr_output_args() -> tuple[str, str]:
    """Use -fps_mode when available, with a -vsync capability fallback."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-h", "full"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    help_text = f"{result.stdout}\n{result.stderr}"
    if "-fps_mode" in help_text:
        return "-fps_mode", "vfr"
    if "-vsync" in help_text:
        return "-vsync", "vfr"
    raise RuntimeError(
        "unable to detect FFmpeg frame-rate mode support; "
        "expected -fps_mode or -vsync support in `ffmpeg -h full`"
    )


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed. fix: brew install ffmpeg")


def probe_duration(source: str | Path) -> float | None:
    """Return the media duration in seconds via ffprobe, or None.

    Streamed WebM, such as a browser MediaRecorder screen recording, stores
    no format or stream duration. The last video packet time is then the only
    length on record; reading it demuxes the file without decoding.
    """
    if shutil.which("ffprobe") is None:
        return None
    for entries in ("format=duration:stream=duration", "packet=pts_time"):
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                entries,
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(Path(source).expanduser()),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            return None
        values: list[float] = []
        for field in result.stdout.split():
            try:
                value = float(field)
            except ValueError:
                continue  # "N/A"
            if math.isfinite(value) and value > 0:
                values.append(value)
        if values:
            return max(values)
    return None


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
    pre = ["-ss", f"{start:.6f}"] if start is not None else []
    post: list[str] = []
    if duration is not None:
        post = ["-t", f"{duration:.6f}"]
    elif start is not None and end is not None:
        post = ["-t", f"{end - start:.6f}"]
    elif start is None and end is not None:
        post = ["-t", f"{end:.6f}"]
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


def _showinfo_timestamps(stderr: str, frame_count: int | None = None) -> list[float]:
    """Read emitted PTS without inventing labels when FFmpeg omits them."""
    try:
        times = [float(match.group(1)) for match in SHOWINFO_TS_RE.finditer(stderr)]
        if any(not math.isfinite(value) for value in times):
            raise ValueError()
        if any(after < before for before, after in zip(times, times[1:])):
            raise ValueError()
        if frame_count is not None and len(times) < frame_count:
            raise ValueError()
    except ValueError as exc:
        raise RuntimeError("ffmpeg did not provide valid timestamps for every extracted frame") from exc
    # -frames:v can stop output after showinfo has already seen another frame.
    return times if frame_count is None else times[:frame_count]


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
    """Decode a numbered image sequence to RGB thumbnails in one pass.

    ffmpeg does the pixel decode (keeps this stdlib-only); the raw RGB
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
        f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        return []
    chunk = DEDUP_THUMB * DEDUP_THUMB * 3
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
                "timestamp_seconds": round(timestamp, 6),
                "timestamp": format_time(timestamp),
                "path": str(final),
                "format": frame_format,
                "mime_type": mime_type,
                "reason": candidate.get("reason", "selected"),
                **(
                    {"requested_timestamp_seconds": candidate["requested_timestamp_seconds"]}
                    if "requested_timestamp_seconds" in candidate else {}
                ),
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
    total_duration: float | None = None,
    max_frames_at_limit: bool = False,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Uniform engine: fixed-fps sampling with duration-aware budgets.

    total_duration is the full source length. It sizes the budget for an
    unbounded range without trimming the input; ffprobe fills it when omitted.
    max_frames_at_limit is passed to resolve_frame_plan for the coverage hint.
    """
    scale = scale_filter(width)
    start, end, duration = resolve_range(start, end, duration)
    fps = _seconds(fps, "--fps", positive=True)
    frame_interval = _seconds(frame_interval, "--frame-interval", positive=True)
    timestamp_offset = _seconds(timestamp_offset, "timestamp offset")
    total_duration = _seconds(total_duration, "source duration")
    extension = frame_extension(frame_format)
    plan_duration = duration
    if plan_duration is None:
        # Without a length the plan defaults to 1 fps, which stops after
        # max_frames seconds instead of spanning the whole video.
        known = total_duration if total_duration is not None else probe_duration(source)
        if known is not None and known > (start or 0.0):
            plan_duration = known - (start or 0.0)
    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    plan = resolve_frame_plan(
        plan_duration,
        focused=start is not None or end is not None or duration is not None,
        frame_mode=frame_mode,
        frame_interval=frame_interval,
        fps=fps,
        max_frames=max_frames,
        range_start=base,
        max_frames_at_limit=max_frames_at_limit,
    )
    selected_fps = float(plan["fps"])
    target_frames = int(plan["target_frames"])
    _require_ffmpeg()

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_frames(out_path)

    raw_pattern = str(out_path / f"frame_raw_%04d.{extension}")
    pre_seek, _ = _seek_args(start, end, duration)
    # Select the first real frame in each time bucket. The fps filter rewrites
    # timestamps and can label pixels from half an interval later as the bucket
    # start. Selection retains source PTS, including delayed video streams and
    # irregular frame rates. The explicit rate still stops at the requested cap.
    trim = f"trim=end={duration:.6f}," if duration is not None else ""
    select = (
        f"select='isnan(prev_selected_t)+"
        f"gt(floor(t*{selected_fps:.17g}),floor(prev_selected_t*{selected_fps:.17g}))'"
    )
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "info",
        "-y",
        *pre_seek,
        "-i",
        str(Path(source).expanduser()),
        "-vf",
        f"{trim}{select},trim=end_frame={target_frames},{scale},showinfo",
        *_vfr_output_args(),
        "-frames:v",
        str(target_frames),
        *_quality_args(frame_format),
        raw_pattern,
    ]
    stderr = _run_ffmpeg(cmd, frame_format).stderr

    raw_files = _raw_files(out_path, extension)
    exact = _showinfo_timestamps(stderr, len(raw_files))
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + exact[index],
            "reason": "uniform",
        }
        for index, raw_file in enumerate(raw_files)
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
        "plan": {
            "mode": plan["mode"],
            "fps": selected_fps,
            "target_frames": target_frames,
            "max_frames": plan["max_frames"],
            "warnings": plan["warnings"],
        },
    }
    return frames, meta


def _select_candidates(
    engine: str,
    candidates: list[dict],
    *,
    max_frames: int,
    frame_format: str,
    dedup: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Dedup, thin to the cap, and finalize an engine's own candidates."""
    candidate_count = len(candidates)
    dropped = 0
    if dedup:
        candidates, dropped = _dedupe_candidates(candidates)
    candidates = _even_sample(candidates, max_frames)
    frames = _finalize_frames(candidates, frame_format)
    return frames, {
        "engine": engine,
        "candidate_count": candidate_count,
        "deduped_count": dropped,
        "selected_count": len(frames),
        "fallback": False,
    }


def _uniform_fallback(
    engine: str,
    source: str | Path,
    out_dir: str | Path,
    candidates: list[dict],
    *,
    start: float | None,
    duration: float | None,
    total_duration: float | None,
    max_frames: int,
    width: int,
    frame_format: str,
    timestamp_offset: float | None,
    dedup: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Replace too-few engine candidates with uniform sampling of the same range.

    Takes the range already normalized by resolve_range. end is left out on
    purpose: it is derived from start + duration, and passing all three back
    would fail resolve_range's "--end or --duration" check.

    The candidates wait in a side directory while uniform sampling runs and
    are deleted only once it returns frames. If it finds none or fails, the
    engine's own candidates are finalized instead; with none of those either,
    a uniform failure propagates.
    """
    found = len(candidates)
    out_path = Path(out_dir).expanduser().resolve()
    held = Path(tempfile.mkdtemp(prefix=".held-", dir=out_path))
    try:
        for candidate in candidates:
            candidate["raw_path"] = candidate["raw_path"].rename(
                held / candidate["raw_path"].name
            )
        try:
            frames, uniform_meta = extract_frames(
                source,
                out_dir,
                start=start,
                duration=duration,
                total_duration=total_duration,
                frame_mode="auto",
                max_frames=max_frames,
                width=width,
                frame_format=frame_format,
                timestamp_offset=timestamp_offset,
                dedup=dedup,
            )
        except RuntimeError:
            if not candidates:
                raise
            frames, uniform_meta = [], {}
        if frames or not candidates:
            return frames, {
                "engine": "uniform",
                "candidate_count": found,
                "deduped_count": uniform_meta["deduped_count"],
                "selected_count": len(frames),
                "fallback": True,
                "plan": uniform_meta["plan"],
            }

        _cleanup_old_frames(out_path)
        for candidate in candidates:
            candidate["raw_path"] = candidate["raw_path"].rename(
                out_path / candidate["raw_path"].name
            )
        return _select_candidates(
            engine, candidates, max_frames=max_frames, frame_format=frame_format, dedup=dedup
        )
    finally:
        shutil.rmtree(held, ignore_errors=True)


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
    total_duration: float | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keyframe engine: decode only I-frames (the near-instant tier).

    Encoders emit keyframes at scene cuts, so these already approximate
    "distinct moments" without decoding every frame. Too few keyframes means
    a very short or oddly encoded clip; fall back to uniform sampling.
    total_duration only sizes that fallback's budget.
    """
    scale = scale_filter(width)
    start, end, duration = resolve_range(start, end, duration)
    timestamp_offset = _seconds(timestamp_offset, "timestamp offset")
    total_duration = _seconds(total_duration, "source duration")
    _require_ffmpeg()
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
        f"{scale},showinfo",
        *_vfr_output_args(),
        *_quality_args(frame_format),
        raw_pattern,
    ]
    try:
        stderr = _run_ffmpeg(cmd, frame_format).stderr
    except RuntimeError:
        # A focused range can hold no keyframe at all, and ffmpeg then fails
        # because nothing was written. Treat that as zero candidates so the
        # uniform fallback runs; a broken source fails again there.
        if _raw_files(out_path, extension):
            raise
        stderr = ""

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    raw_files = _raw_files(out_path, extension)
    exact = _showinfo_timestamps(stderr, len(raw_files))
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + exact[index],
            "reason": "keyframe",
        }
        for index, raw_file in enumerate(raw_files)
    ]

    if len(candidates) < KEYFRAME_MIN:
        return _uniform_fallback(
            "keyframe",
            source,
            out_dir,
            candidates,
            start=start,
            duration=duration,
            total_duration=total_duration,
            max_frames=max_frames,
            width=width,
            frame_format=frame_format,
            timestamp_offset=timestamp_offset,
            dedup=dedup,
        )
    return _select_candidates(
        "keyframe", candidates, max_frames=max_frames, frame_format=frame_format, dedup=dedup
    )


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
    total_duration: float | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Scene engine: cuts plus a bounded coarse check of long quiet spans.

    Detection is uncapped across the whole range so coverage spans the full
    clip (capping detection would keep only the earliest cuts). This costs a
    full decode; use the keyframe engine when speed matters more. Videos with
    fewer than SCENE_MIN_FRAMES detected shots fall back to uniform sampling,
    whose budget total_duration sizes. Otherwise up to a quarter of the cap
    (at most 20 frames) checks long gaps between the selected scenes.
    """
    scale = scale_filter(width)
    start, end, duration = resolve_range(start, end, duration)
    timestamp_offset = _seconds(timestamp_offset, "timestamp offset")
    total_duration = _seconds(total_duration, "source duration")
    scene_threshold = _seconds(scene_threshold, "scene threshold")
    _require_ffmpeg()
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
        f"{select},{scale},showinfo",
        *_vfr_output_args(),
        *_quality_args(frame_format),
        raw_pattern,
    ]
    result = _run_ffmpeg(cmd, frame_format)

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    raw_files = _raw_files(out_path, extension)
    exact = _showinfo_timestamps(result.stderr, len(raw_files))
    candidates = [
        {
            "raw_path": raw_file,
            "timestamp_seconds": base + exact[index],
            "reason": "first-frame" if index == 0 else "scene-change",
        }
        for index, raw_file in enumerate(raw_files)
    ]

    if len(candidates) < SCENE_MIN_FRAMES:
        return _uniform_fallback(
            "scene",
            source,
            out_dir,
            candidates,
            start=start,
            duration=duration,
            total_duration=total_duration,
            max_frames=max_frames,
            width=width,
            frame_format=frame_format,
            timestamp_offset=timestamp_offset,
            dedup=dedup,
        )
    return _select_scenes_with_coverage(
        source, out_path, candidates,
        start=start, duration=duration, total_duration=total_duration,
        max_frames=max_frames, width=width, frame_format=frame_format,
        timestamp_offset=timestamp_offset, dedup=dedup,
    )


def _scene_coverage_points(
    scenes: list[dict], base: float, span: float | None, budget: int,
) -> tuple[list[float], float | None]:
    """Divide long gaps into coarse intervals without adding dense screenshots."""
    if span is None or span <= 0 or budget <= 0:
        return [], None
    interval = max(SCENE_COVERAGE_MIN_INTERVAL, span / (budget + 1))
    end = base + span
    anchors = sorted({base, end, *(
        float(frame["timestamp_seconds"]) for frame in scenes
        if base <= float(frame["timestamp_seconds"]) <= end
    )})
    points: list[float] = []
    for low, high in zip(anchors, anchors[1:]):
        pieces = max(1, math.ceil((high - low) / interval - 1e-9))
        points.extend(low + (high - low) * index / pieces for index in range(1, pieces))
    # Floating-point boundary effects must never exceed the reserved budget.
    return [points[index] for index in _even_indices(len(points), budget)], interval


def _select_scenes_with_coverage(
    source: str | Path,
    out_path: Path,
    candidates: list[dict],
    *,
    start: float | None,
    duration: float | None,
    total_duration: float | None,
    max_frames: int,
    width: int,
    frame_format: str,
    timestamp_offset: float | None,
    dedup: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    scene_count = len(candidates)
    dropped = 0
    if dedup:
        candidates, dropped = _dedupe_candidates(candidates)
    cap = max(1, int(max_frames))
    coverage_budget = min(SCENE_COVERAGE_MAX_FRAMES, cap // 4)
    # Plan against a conservative scene subset. Any unused coverage slots go
    # back to scene selection; those extra scenes only improve the coverage.
    provisional = [candidates[index] for index in _even_indices(
        len(candidates), max(1, cap - coverage_budget)
    )]
    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    span = duration
    if span is None:
        known = total_duration if total_duration is not None else probe_duration(source)
        if known is not None:
            span = max(0.0, known - (start or 0.0))
    points, interval = _scene_coverage_points(provisional, base, span, coverage_budget)
    coverage: list[dict] = []
    warnings: list[str] = []
    if points:
        # A separate directory protects pinned cues and the consecutive raw
        # scene files. Coverage anchors deliberately survive visual dedup: they
        # make the coarse checks of long quiet spans available for inspection.
        with tempfile.TemporaryDirectory(prefix=".coverage-", dir=out_path) as tmp:
            try:
                frames, meta = extract_at_timestamps(
                    source, tmp, points,
                    width=width, frame_format=frame_format,
                    window_start=base, window_end=base + span,
                    media_time_offset=base - (start or 0.0),
                )
                warnings.extend(f"scene coverage: {warning}" for warning in meta["warnings"])
            except (RuntimeError, ValueError) as exc:
                frames = []
                warnings.append(f"scene coverage unavailable: {exc}")
            for index, frame in enumerate(frames):
                original = Path(str(frame["path"]))
                raw = original.rename(out_path / f"frame_coverage_raw_{index:04d}{original.suffix}")
                coverage.append({
                    "raw_path": raw,
                    "timestamp_seconds": frame["timestamp_seconds"],
                    "requested_timestamp_seconds": frame["requested_timestamp_seconds"],
                    "reason": "coverage",
                })
    selected = _even_sample(candidates, cap - len(coverage))
    selected = sorted([*selected, *coverage], key=lambda frame: frame["timestamp_seconds"])
    frames = _finalize_frames(selected, frame_format)
    return frames, {
        "engine": "scene",
        "candidate_count": scene_count + len(coverage),
        "scene_candidate_count": scene_count,
        "deduped_count": dropped,
        "selected_count": len(frames),
        "fallback": False,
        "coverage_count": len(coverage),
        "coverage_requested_count": len(points),
        "coverage_interval_seconds": interval,
        "warnings": warnings,
    }


def cues_in_window(
    timestamps: list[float],
    window_start: float | None,
    window_end: float | None,
) -> tuple[list[float], int]:
    """Filter cue timestamps to the focus window; return (kept, dropped)."""
    low = _seconds(window_start, "window start") or 0.0
    high = _seconds(window_end, "window end")
    if high is not None and high < low:
        raise ValueError("window end must not precede window start")
    high = high if high is not None else float("inf")
    requested = sorted(set(round(_seconds(value, "cue timestamp"), 6) for value in timestamps))
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
    scale = scale_filter(width)
    media_time_offset = _seconds(media_time_offset, "media time offset")
    in_window, dropped = cues_in_window(timestamps, window_start, window_end)
    _require_ffmpeg()
    extension = frame_extension(frame_format)
    mime_type = frame_mime_type(frame_format)
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    _cleanup_old_cues(out_path)

    if max_frames is not None and len(in_window) > max_frames:
        in_window = [in_window[index] for index in _even_indices(len(in_window), max_frames)]

    frames: list[dict[str, object]] = []
    warnings: list[str] = []
    for value in in_window:
        seek = max(0.0, value - media_time_offset)
        path = out_path / f"cue_{len(frames):04d}_{timestamp_name(value)}.{extension}"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-y",
            "-ss",
            f"{seek:.6f}",
            "-i",
            str(Path(source).expanduser()),
            "-frames:v",
            "1",
            "-vf",
            f"{scale},showinfo",
            *_vfr_output_args(),
            *_quality_args(frame_format),
            str(path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        if result.returncode == 0 and path.exists():
            try:
                actual = media_time_offset + seek + _showinfo_timestamps(result.stderr, 1)[0]
            except RuntimeError as exc:
                path.unlink(missing_ok=True)
                warnings.append(f"cue at {value:g}s: {exc}")
                continue
            if window_end is not None and actual > window_end:
                path.unlink(missing_ok=True)
                dropped += 1
                continue
            frames.append(
                {
                    "index": len(frames) + 1,
                    "timestamp_seconds": round(actual, 6),
                    "requested_timestamp_seconds": value,
                    "timestamp": format_time(actual),
                    "path": str(path),
                    "format": frame_format,
                    "mime_type": mime_type,
                    "reason": "transcript-cue",
                }
            )
        else:
            path.unlink(missing_ok=True)
            warnings.append(f"no frame available at cue timestamp {value:g}s")

    meta = {
        "engine": "timestamps",
        "requested_count": len(set(round(float(value), 6) for value in timestamps)),
        "selected_count": len(frames),
        "dropped_out_of_window": dropped,
        "warnings": warnings,
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
        help="Seconds between frames in interval mode (default: 5; at least 0.5, the 2 fps cap)",
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
