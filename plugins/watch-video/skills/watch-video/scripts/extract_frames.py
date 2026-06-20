#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/watch-video/scripts/extract_frames.py
# Do not edit directly; edit the source path and run make build-packages.
# END GENERATED FROM SOURCE

"""Extract timestamped preview frames from a video with ffmpeg."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path


DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_MAX_FRAMES = 80
HARD_MAX_FRAMES = 100
MAX_FPS = 2.0
DEFAULT_WIDTH = 960
FRAME_FORMATS = {"jpeg", "png", "webp"}


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
    """Return frame extraction settings with hard caps applied."""
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
        warnings.append("video is longer than 10 minutes; frame coverage will be sparse")
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
) -> list[dict[str, object]]:
    """Extract frames and return metadata for each image."""
    _require_ffmpeg()
    start, end, duration = resolve_range(start, end, duration)
    extension = frame_extension(frame_format)
    mime_type = frame_mime_type(frame_format)
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
    fps_expr = f"fps={selected_fps:g},scale={int(width)}:-2"

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", str(source)])
    if duration is not None:
        cmd.extend(["-t", f"{duration:.3f}"])
    elif start is not None and end is not None:
        cmd.extend(["-t", f"{end - start:.3f}"])
    cmd.extend(["-vf", fps_expr, "-frames:v", str(target_frames), *_quality_args(frame_format), raw_pattern])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffmpeg error"
        if frame_format == "webp" and "webp" in detail.lower():
            raise RuntimeError(
                "ffmpeg frame extraction failed: WebP output requires an ffmpeg build "
                "with WebP encoder support. Try --frame-format jpeg or png."
            )
        raise RuntimeError(f"ffmpeg frame extraction failed: {detail}")

    base = timestamp_offset if timestamp_offset is not None else (start or 0.0)
    frames: list[dict[str, object]] = []
    for index, raw_file in enumerate(sorted(out_path.glob(f"frame_raw_*.{extension}")), start=1):
        timestamp = base + ((index - 1) / selected_fps)
        final = out_path / f"frame_{index:04d}_{timestamp_name(timestamp)}.{extension}"
        raw_file.rename(final)
        frames.append(
            {
                "index": index,
                "timestamp_seconds": round(timestamp, 3),
                "timestamp": format_time(timestamp),
                "path": str(final),
                "format": frame_format,
                "mime_type": mime_type,
            }
        )
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract timestamped frames with ffmpeg.")
    parser.add_argument("source", help="Video path or ffmpeg-readable source")
    parser.add_argument("out_dir", help="Directory for extracted frames")
    parser.add_argument("--start", help="Start time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--end", help="End time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--duration", help="Duration as seconds or time string")
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
    args = parser.parse_args()

    try:
        frames = extract_frames(
            args.source,
            args.out_dir,
            start=parse_time(args.start),
            end=parse_time(args.end),
            duration=parse_time(args.duration),
            frame_mode=args.frame_mode,
            frame_interval=args.frame_interval,
            fps=args.fps,
            max_frames=args.max_frames,
            width=args.width,
            frame_format=args.frame_format,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"frames": frames}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
