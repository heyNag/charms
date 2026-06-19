#!/usr/bin/env python3
"""Watch Video CLI entrypoint."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from extract_frames import (  # noqa: E402
    DEFAULT_INTERVAL_SECONDS,
    extract_frames,
    format_time,
    parse_time,
    resolve_range,
)
from groq_transcribe import (  # noqa: E402
    DEFAULT_GROQ_MODEL,
    extract_audio_clip,
    segments_from_response,
    transcribe_audio,
)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".flv"}
TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}[\.,]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")


def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def safe_run_id(source: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parsed = urlparse(source)
    if parsed.netloc:
        seed = f"{parsed.netloc}{parsed.path}"
    else:
        seed = Path(source).stem or "video"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", seed).strip("-._")[:48] or "video"
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    return f"{stamp}-{slug}-{digest}"


def create_run_dir(base_dir: str | Path, source: str) -> Path:
    """Create a predictable run directory without overwriting prior runs."""
    base = Path(base_dir).expanduser().resolve()
    run_id = safe_run_id(source)
    for suffix in ["", *[f"-{index:02d}" for index in range(1, 100)]]:
        candidate = base / f"{run_id}{suffix}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"could not create a unique run directory under {base}")


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require_tool(name: str, fix: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"{name} is not installed. fix: {fix}")


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def pick_video(media_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
        matches = sorted(media_dir.glob(f"video*{ext}"))
        if matches:
            return matches[0]
    for candidate in sorted(media_dir.glob("video.*")):
        if candidate.suffix.lower() in VIDEO_EXTENSIONS:
            return candidate
    return None


def pick_caption(media_dir: Path) -> Path | None:
    captions = sorted(media_dir.glob("video*.vtt"))
    if not captions:
        return None
    preferred = [path for path in captions if ".en" in path.name]
    return preferred[0] if preferred else captions[0]


def compact_info(info_path: Path, fallback_url: str | None = None) -> dict[str, object]:
    if not info_path.exists():
        return {"url": fallback_url} if fallback_url else {}
    try:
        raw = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"url": fallback_url} if fallback_url else {}

    keys = [
        "id",
        "title",
        "fulltitle",
        "uploader",
        "channel",
        "duration",
        "webpage_url",
        "extractor",
        "upload_date",
        "availability",
    ]
    return {key: raw.get(key) for key in keys if raw.get(key) is not None}


def download_url(url: str, media_dir: Path) -> tuple[Path, Path | None, dict[str, object]]:
    require_tool("yt-dlp", "brew install yt-dlp")
    media_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(media_dir / "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "-N",
        "4",
        "-f",
        "bv*[height<=720]+ba/b[height<=720]/b",
        "--merge-output-format",
        "mp4",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "en,en-US,en-GB,en-orig",
        "--sub-format",
        "vtt",
        "--convert-subs",
        "vtt",
        "--no-playlist",
        "-o",
        output_template,
        "--",
        url,
    ]
    result = run_command(cmd)
    video = pick_video(media_dir)
    if video is None:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"yt-dlp did not produce a video file. detail: {detail[-1200:]}")

    info = compact_info(media_dir / "video.info.json", fallback_url=url)
    if result.returncode != 0:
        info["yt_dlp_warning"] = (result.stderr or result.stdout).strip()[-1200:]
    return video, pick_caption(media_dir), info


def resolve_local(source: str) -> tuple[Path, None, dict[str, object]]:
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    info: dict[str, object] = {
        "title": path.name,
        "path": str(path),
        "source_type": "local",
    }
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        info["warning"] = f"{path.suffix} is not a common video extension"
    return path, None, info


def ffprobe_metadata(video_path: Path) -> dict[str, object]:
    require_tool("ffprobe", "brew install ffmpeg")
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = run_command(cmd)
    if result.returncode != 0:
        return {"ffprobe_error": result.stderr.strip()}
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"ffprobe_error": "ffprobe returned invalid JSON"}

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = fmt.get("duration") or video_stream.get("duration")
    return {
        "duration_seconds": float(duration) if duration else None,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "video_codec": video_stream.get("codec_name"),
        "has_audio": audio_stream is not None,
        "size_bytes": int(fmt.get("size") or 0),
        "format_name": fmt.get("format_name"),
    }


def vtt_time_to_seconds(value: str) -> float:
    clean = value.replace(",", ".")
    hours, minutes, seconds = clean.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_text(lines: list[str]) -> str:
    cleaned: list[str] = []
    for line in lines:
        text = TAG_RE.sub("", line)
        text = html.unescape(text).strip()
        if text:
            cleaned.append(text)
    return " ".join(cleaned).strip()


def parse_vtt(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    segments: list[dict[str, object]] = []
    index = 0
    while index < len(lines):
        match = TIMESTAMP_RE.search(lines[index])
        if not match:
            index += 1
            continue
        start = vtt_time_to_seconds(match.group("start"))
        end = vtt_time_to_seconds(match.group("end"))
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            body.append(lines[index])
            index += 1
        text = clean_caption_text(body)
        if text:
            append_caption_segment(segments, start, end, text)
        index += 1
    return segments


def append_caption_segment(
    segments: list[dict[str, object]],
    start: float,
    end: float,
    text: str,
) -> None:
    """Append a VTT segment, collapsing rolling auto-caption duplicates."""
    clean_text = " ".join(text.split())
    if not clean_text:
        return
    rounded_end = round(end, 3)

    if segments:
        previous = str(segments[-1].get("text") or "")
        if clean_text == previous:
            segments[-1]["end"] = rounded_end
            return
        if clean_text.startswith(f"{previous} "):
            segments[-1]["text"] = clean_text
            segments[-1]["end"] = rounded_end
            return
        if previous.startswith(f"{clean_text} "):
            segments[-1]["end"] = rounded_end
            return
        if previous.endswith(f" {clean_text}"):
            segments[-1]["end"] = rounded_end
            return

    segments.append({"start": round(start, 3), "end": rounded_end, "text": clean_text})


def filter_segments(
    segments: list[dict[str, object]],
    start: float | None,
    end: float | None,
) -> list[dict[str, object]]:
    if start is None and end is None:
        return segments
    low = start if start is not None else float("-inf")
    high = end if end is not None else float("inf")
    return [
        segment
        for segment in segments
        if float(segment.get("end") or 0.0) >= low and float(segment.get("start") or 0.0) <= high
    ]


def transcript_markdown(segments: list[dict[str, object]]) -> str:
    lines = []
    for segment in segments:
        stamp = format_time(float(segment.get("start") or 0.0))
        text = str(segment.get("text") or "").strip()
        if text:
            lines.append(f"[{stamp}] {text}")
    return "\n".join(lines)


def source_title(metadata: dict[str, object], source: str) -> str:
    return str(
        metadata.get("title")
        or metadata.get("fulltitle")
        or metadata.get("path")
        or metadata.get("webpage_url")
        or source
    )


def build_report(
    *,
    source: str,
    run_dir: Path,
    metadata: dict[str, object],
    clip_start: float | None,
    clip_end: float | None,
    audio_path: Path,
    audio_error: str | None,
    transcript_source: str,
    transcript_segments: list[dict[str, object]],
    frames: list[dict[str, object]],
    errors: list[str],
) -> str:
    title = source_title(metadata.get("source_info", {}) if metadata else {}, source)
    probe = metadata.get("probe", {}) if isinstance(metadata.get("probe"), dict) else {}
    duration = probe.get("duration_seconds")
    range_text = "full source"
    if clip_start is not None or clip_end is not None:
        range_text = f"{format_time(clip_start or 0.0)} to {format_time(clip_end)}"

    lines = [
        "# Watch Video Report",
        "",
        f"- Source: {source}",
        f"- Title: {title}",
        f"- Run directory: `{run_dir}`",
        f"- Range: {range_text}",
    ]
    if duration is not None:
        lines.append(f"- Duration: {format_time(float(duration))} ({float(duration):.1f}s)")
    if probe.get("width") and probe.get("height"):
        lines.append(f"- Resolution: {probe['width']}x{probe['height']}")
    lines.extend(
        [
            f"- Audio clip: `{audio_path}`" if audio_path.exists() else "- Audio clip: unavailable",
            f"- Transcript: {len(transcript_segments)} segments via {transcript_source}",
            f"- Frames: {len(frames)}",
            "",
            "## Artifacts",
            "",
            f"- Metadata JSON: `{run_dir / 'metadata.json'}`",
            f"- Audio MP3: `{audio_path}`" if audio_path.exists() else "- Audio MP3: unavailable",
            f"- Transcript JSON: `{run_dir / 'transcript.json'}`",
            f"- Transcript Markdown: `{run_dir / 'transcript.md'}`",
            f"- Frames directory: `{run_dir / 'frames'}`",
            "",
        ]
    )

    if audio_error:
        lines.extend(["## Audio Notes", "", f"- {audio_error}", ""])

    if errors:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")

    if frames:
        lines.extend(["## Frames", ""])
        for frame in frames[:20]:
            lines.append(f"- `{frame['path']}` at {frame['timestamp']}")
        if len(frames) > 20:
            lines.append(f"- ... {len(frames) - 20} more frame(s)")
        lines.append("")

    lines.extend(["## Transcript Preview", ""])
    if transcript_segments:
        preview = transcript_markdown(transcript_segments[:12])
        lines.append(preview)
        if len(transcript_segments) > 12:
            lines.append("")
            lines.append(f"... {len(transcript_segments) - 12} more segment(s) in `transcript.md`.")
    else:
        lines.append("No transcript was available. Use frames and metadata only.")

    lines.extend(
        [
            "",
            "## Agent Notes",
            "",
            "- Read frames before answering visual questions.",
            "- Summarize the transcript unless the user asks for the full text.",
            "- Cite timestamps when describing actions, UI state, tools, or commands.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a video source for local agents.")
    parser.add_argument("source", help="Video URL or local path")
    parser.add_argument("--start", help="Start time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--end", help="End time as SS, MM:SS, or HH:MM:SS")
    parser.add_argument("--duration", help="Duration as seconds or time string")
    parser.add_argument(
        "--out-dir",
        default=".watch-video/runs",
        help="Base directory for run artifacts (default: .watch-video/runs)",
    )
    parser.add_argument("--transcriber", choices=["groq", "none"], default="groq")
    parser.add_argument("--frames", dest="frames", action="store_true", default=True)
    parser.add_argument("--no-frames", dest="frames", action="store_false")
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between extracted frames (default: 5)",
    )
    parser.add_argument("--max-frames", type=int, default=80)
    parser.add_argument("--frame-width", type=int, default=960)
    args = parser.parse_args()

    try:
        run_dir = create_run_dir(args.out_dir, args.source)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    media_dir = run_dir / "media"
    frames_dir = run_dir / "frames"

    print(f"[watch-video] run directory: {run_dir}", file=sys.stderr)

    if is_url(args.source):
        print("[watch-video] downloading source with yt-dlp", file=sys.stderr)
        video_path, caption_path, source_info = download_url(args.source, media_dir)
    else:
        print("[watch-video] using local source", file=sys.stderr)
        video_path, caption_path, source_info = resolve_local(args.source)

    probe = ffprobe_metadata(video_path)
    total_duration = (
        float(probe["duration_seconds"])
        if isinstance(probe.get("duration_seconds"), (int, float))
        else None
    )
    try:
        clip_start, clip_end, clip_duration = resolve_range(
            parse_time(args.start),
            parse_time(args.end),
            parse_time(args.duration),
            total_duration=total_duration,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    focused = any([args.start, args.end, args.duration])
    audio_path = run_dir / "audio.mp3"
    errors: list[str] = []
    audio_error: str | None = None

    try:
        extract_audio_clip(
            video_path,
            audio_path,
            start=(clip_start or 0.0) if focused else None,
            duration=clip_duration if focused else None,
        )
    except (RuntimeError, ValueError) as exc:
        audio_error = str(exc)
        errors.append(audio_error)

    transcript_source = "none"
    transcript_segments: list[dict[str, object]] = []
    raw_transcript: dict[str, object] = {"source": "none", "segments": []}

    if caption_path is not None:
        try:
            all_caption_segments = parse_vtt(caption_path)
            transcript_segments = filter_segments(all_caption_segments, clip_start, clip_end)
            transcript_source = "native captions"
            raw_transcript = {
                "source": "native_captions",
                "caption_path": str(caption_path),
                "segments": transcript_segments,
            }
        except OSError as exc:
            errors.append(f"caption parse failed: {exc}")

    if not transcript_segments and args.transcriber == "groq":
        if not audio_path.exists():
            errors.append("Groq fallback skipped because no audio clip was available")
        else:
            try:
                groq_raw_path = run_dir / "groq_transcript.raw.json"
                groq_data = transcribe_audio(
                    audio_path,
                    out_json=groq_raw_path,
                    model=DEFAULT_GROQ_MODEL,
                )
                transcript_segments = segments_from_response(
                    groq_data,
                    offset_seconds=(clip_start or 0.0) if focused else 0.0,
                )
                transcript_source = "groq whisper"
                raw_transcript = {
                    "source": "groq_whisper",
                    "model": DEFAULT_GROQ_MODEL,
                    "raw_response_path": str(groq_raw_path),
                    "segments": transcript_segments,
                }
            except RuntimeError as exc:
                errors.append(str(exc))

    if args.transcriber == "none" and not transcript_segments:
        raw_transcript = {"source": "none", "segments": []}

    frames: list[dict[str, object]] = []
    if args.frames:
        try:
            frames = extract_frames(
                video_path,
                frames_dir,
                start=(clip_start or 0.0) if focused else None,
                duration=clip_duration if focused else None,
                frame_interval=args.frame_interval,
                max_frames=args.max_frames,
                width=args.frame_width,
            )
        except (RuntimeError, ValueError) as exc:
            errors.append(str(exc))

    metadata = {
        "source": args.source,
        "source_info": source_info,
        "video_path": str(video_path),
        "caption_path": str(caption_path) if caption_path else None,
        "probe": probe,
        "range": {
            "start_seconds": clip_start,
            "end_seconds": clip_end,
            "duration_seconds": clip_duration,
            "focused": focused,
        },
        "frames": {
            "enabled": args.frames,
            "count": len(frames),
            "frame_interval": args.frame_interval,
            "max_frames": args.max_frames,
            "width": args.frame_width,
        },
        "transcriber": args.transcriber,
        "errors": errors,
    }
    write_json(run_dir / "metadata.json", metadata)
    write_json(run_dir / "transcript.json", raw_transcript)
    (run_dir / "transcript.md").write_text(transcript_markdown(transcript_segments) + "\n", encoding="utf-8")

    report = build_report(
        source=args.source,
        run_dir=run_dir,
        metadata=metadata,
        clip_start=clip_start,
        clip_end=clip_end,
        audio_path=audio_path,
        audio_error=audio_error,
        transcript_source=transcript_source,
        transcript_segments=transcript_segments,
        frames=frames,
        errors=errors,
    )
    report_path = run_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"[watch-video] report: {report_path}")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
