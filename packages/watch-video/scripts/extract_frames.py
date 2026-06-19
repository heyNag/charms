#!/usr/bin/env python3
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


def expected_frame_count(
    duration_seconds: float | None,
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> int:
    if frame_interval <= 0:
        raise ValueError("--frame-interval must be greater than zero")
    capped = max(1, min(int(max_frames), HARD_MAX_FRAMES))
    if duration_seconds is None or duration_seconds <= 0:
        return capped
    return max(1, min(capped, int(math.ceil(duration_seconds / frame_interval)) + 1))


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed. fix: brew install ffmpeg")


def extract_frames(
    source: str | Path,
    out_dir: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    frame_interval: float = DEFAULT_INTERVAL_SECONDS,
    max_frames: int = DEFAULT_MAX_FRAMES,
    width: int = 960,
) -> list[dict[str, object]]:
    """Extract frames and return metadata for each image."""
    _require_ffmpeg()
    if frame_interval <= 0:
        raise ValueError("--frame-interval must be greater than zero")

    start, end, duration = resolve_range(start, end, duration)
    max_frames = max(1, min(int(max_frames), HARD_MAX_FRAMES))
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    for old in out_path.glob("frame_*.jpg"):
        old.unlink()

    raw_pattern = str(out_path / "frame_raw_%04d.jpg")
    fps_expr = f"fps=1/{frame_interval:g},scale={int(width)}:-2"

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", str(source)])
    if duration is not None:
        cmd.extend(["-t", f"{duration:.3f}"])
    elif start is not None and end is not None:
        cmd.extend(["-t", f"{end - start:.3f}"])
    cmd.extend(["-vf", fps_expr, "-frames:v", str(max_frames), "-q:v", "4", raw_pattern])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg frame extraction failed: {detail}")

    base = start or 0.0
    frames: list[dict[str, object]] = []
    for index, raw_file in enumerate(sorted(out_path.glob("frame_raw_*.jpg")), start=1):
        timestamp = base + ((index - 1) * frame_interval)
        final = out_path / f"frame_{index:04d}_{timestamp_name(timestamp)}.jpg"
        raw_file.rename(final)
        frames.append(
            {
                "index": index,
                "timestamp_seconds": round(timestamp, 3),
                "timestamp": format_time(timestamp),
                "path": str(final),
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
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between frames (default: 5)",
    )
    parser.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES)
    parser.add_argument("--width", type=int, default=960, help="Frame width in pixels")
    args = parser.parse_args()

    try:
        frames = extract_frames(
            args.source,
            args.out_dir,
            start=parse_time(args.start),
            end=parse_time(args.end),
            duration=parse_time(args.duration),
            frame_interval=args.frame_interval,
            max_frames=args.max_frames,
            width=args.width,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"frames": frames}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
