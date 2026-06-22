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
    DEFAULT_MAX_FRAMES,
    DEFAULT_WIDTH,
    FRAME_FORMATS,
    extract_frames,
    format_time,
    parse_time,
    resolve_range,
    resolve_frame_plan,
)
from groq_transcribe import (  # noqa: E402
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    default_model,
    extract_audio_clip,
    segments_from_response,
    transcribe_audio,
)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".flv"}
REPORT_MODES = ("general", "tutorial", "ui-bug", "notes")
SUBTITLE_LANGS = "en,en-orig,en-US,en-GB,en.*,all,-live_chat"
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
    info = pick_caption_info(media_dir)
    return Path(str(info["path"])) if info else None


def load_raw_info(info_path: Path) -> dict[str, object]:
    if not info_path.exists():
        return {}
    try:
        data = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def caption_language_from_name(path: Path) -> str | None:
    parts = path.name.split(".")
    if len(parts) >= 3:
        return parts[-2]
    return None


def caption_language_rank(language: str | None) -> int:
    clean = (language or "").lower()
    if clean == "en":
        return 0
    if clean == "en-orig":
        return 1
    if clean == "en-us":
        return 2
    if clean == "en-gb":
        return 3
    if clean.startswith("en"):
        return 4
    return 100


def caption_type_for_language(raw_info: dict[str, object], language: str | None) -> str:
    if not language:
        return "unknown"
    subtitles = raw_info.get("subtitles")
    auto = raw_info.get("automatic_captions")
    if isinstance(subtitles, dict) and language in subtitles:
        return "manual"
    if isinstance(auto, dict) and language in auto:
        return "auto"
    return "unknown"


def pick_caption_info(media_dir: Path, raw_info: dict[str, object] | None = None) -> dict[str, object] | None:
    captions = sorted(media_dir.glob("video*.vtt"))
    if not captions:
        return None
    raw_info = raw_info or {}
    candidates: list[dict[str, object]] = []
    for path in captions:
        language = caption_language_from_name(path)
        caption_type = caption_type_for_language(raw_info, language)
        candidates.append(
            {
                "path": str(path),
                "language": language,
                "caption_type": caption_type,
            }
        )

    def sort_key(candidate: dict[str, object]) -> tuple[int, int, int, str]:
        language = str(candidate.get("language") or "")
        rank = caption_language_rank(language)
        type_rank = {"manual": 0, "auto": 1, "unknown": 2}.get(
            str(candidate.get("caption_type") or "unknown"),
            2,
        )
        return (0 if rank < 100 else 1, type_rank, rank, str(candidate["path"]))

    return sorted(candidates, key=sort_key)[0]


def compact_info(info_path: Path, fallback_url: str | None = None) -> dict[str, object]:
    raw = load_raw_info(info_path)
    if not raw:
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


def download_section_for_args(
    start: float | None,
    end: float | None,
    duration: float | None,
) -> str | None:
    """Return a yt-dlp download section for finite focused ranges."""
    section_start, section_end, _ = resolve_range(start, end, duration)
    if section_start is None or section_end is None:
        return None
    return f"*{format_download_section_time(section_start)}-{format_download_section_time(section_end)}"


def format_download_section_time(seconds: float) -> str:
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining = total_seconds % 60
    if hours or minutes:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"00:{remaining:02d}"


def download_url(
    url: str,
    media_dir: Path,
    *,
    download_section: str | None = None,
) -> tuple[Path, dict[str, object] | None, dict[str, object]]:
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
        SUBTITLE_LANGS,
        "--sub-format",
        "vtt",
        "--convert-subs",
        "vtt",
        "--no-playlist",
    ]
    if download_section is not None:
        cmd.extend(["--download-sections", download_section])
    cmd.extend(["-o", output_template, "--", url])
    result = run_command(cmd)
    video = pick_video(media_dir)
    if video is None:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"yt-dlp did not produce a video file. detail: {detail[-1200:]}")

    info_path = media_dir / "video.info.json"
    raw_info = load_raw_info(info_path)
    info = compact_info(info_path, fallback_url=url)
    if download_section is not None:
        info["download_section"] = download_section
        info["focused_download_requested"] = True
    if result.returncode != 0:
        info["yt_dlp_warning"] = (result.stderr or result.stdout).strip()[-1200:]
    return video, pick_caption_info(media_dir, raw_info), info


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


def transcript_coverage_seconds(segments: list[dict[str, object]]) -> float:
    intervals: list[tuple[float, float]] = []
    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or 0.0)
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return round(sum(end - start for start, end in merged), 3)


def caption_coverage_ratio(
    segments: list[dict[str, object]],
    total_duration: float | None,
) -> float | None:
    if total_duration is None or total_duration <= 0:
        return None
    return round(min(1.0, transcript_coverage_seconds(segments) / total_duration), 4)


def captions_are_insufficient(
    segments: list[dict[str, object]],
    total_duration: float | None,
    *,
    threshold: float = 0.5,
) -> bool:
    if not segments:
        return True
    if total_duration is None or total_duration < 30:
        return False
    ratio = caption_coverage_ratio(segments, total_duration)
    return ratio is not None and ratio < threshold


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


def mode_sections(mode: str) -> list[str]:
    if mode == "tutorial":
        return [
            "## Tools And Services Mentioned",
            "",
            "- Review transcript and frames; list only evidence-backed tools/services here.",
            "",
            "## Commands And Config Seen Or Spoken",
            "",
            "- Review transcript and UI frames; quote timestamps for commands/config.",
            "",
            "## Implementation Checklist",
            "",
            "- Convert observed steps into a checklist after reviewing evidence.",
            "",
            "## Pitfalls And Assumptions",
            "",
            "- Note missing context, skipped steps, or uncertain commands.",
            "",
        ]
    if mode == "ui-bug":
        return [
            "## Observed Symptom",
            "",
            "- Describe the visible failure after reviewing frames and transcript.",
            "",
            "## Expected Behavior",
            "",
            "- Infer only when the recording or surrounding request provides enough evidence.",
            "",
            "## Timestamped Evidence",
            "",
            "- Cite frame paths and transcript timestamps.",
            "",
            "## Likely Causes",
            "",
            "- List hypotheses separately from observed facts.",
            "",
            "## Next Debugging Checks",
            "",
            "- Suggest targeted checks based on the evidence.",
            "",
        ]
    if mode == "notes":
        return [
            "## One-Line Summary",
            "",
            "- Fill after reviewing transcript and frames.",
            "",
            "## TL;DR",
            "",
            "- Evidence-backed bullets only.",
            "",
            "## Timeline",
            "",
            "- Use transcript timestamps and frame paths.",
            "",
            "## Key Quotes",
            "",
            "- Pull short quotes only when useful.",
            "",
            "## Visual Notes",
            "",
            "- Describe visible UI/actions after opening frames.",
            "",
        ]
    return [
        "## Summary",
        "",
        "- Fill after reviewing transcript and frames.",
        "",
        "## Timeline",
        "",
        "- Cite timestamps for actions, UI state, tools, or commands.",
        "",
        "## Visible UI And Actions",
        "",
        "- Review frames before answering visual questions.",
        "",
        "## Commands And Tools Mentioned",
        "",
        "- Extract from transcript and visible UI only.",
        "",
        "## Uncertainty",
        "",
        "- Call out missing audio, sparse frames, weak captions, or unclear UI.",
        "",
    ]


def cleanup_artifacts(
    *,
    media_dir: Path,
    audio_path: Path,
    frames_dir: Path,
    cleanup: bool,
    cleanup_frames: bool,
) -> list[str]:
    if cleanup_frames and not cleanup:
        raise ValueError("--cleanup-frames requires --cleanup")
    removed: list[str] = []
    if not cleanup:
        return removed
    if media_dir.exists():
        shutil.rmtree(media_dir)
        removed.append(str(media_dir))
    if audio_path.exists():
        audio_path.unlink()
        removed.append(str(audio_path))
    if cleanup_frames and frames_dir.exists():
        shutil.rmtree(frames_dir)
        removed.append(str(frames_dir))
    return removed


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
    frame_plan: dict[str, object] | None = None,
    mode: str = "general",
    download_section: str | None = None,
    cleanup_note: str | None = None,
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
            f"- Report mode: {mode}",
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
    if download_section:
        lines.insert(5, f"- Focused download section requested: `{download_section}`")
    if frame_plan:
        mode_name = frame_plan.get("mode")
        fps = float(frame_plan.get("fps") or 0.0)
        interval = float(frame_plan.get("interval") or 0.0)
        target = frame_plan.get("target_frames")
        maximum = frame_plan.get("max_frames")
        lines.extend(
            [
                "## Frame Plan",
                "",
                f"- Mode: {mode_name}",
                f"- Selected FPS: {fps:.3g}",
                f"- Selected interval: {interval:.3g}s",
                f"- Target frames: {target}",
                f"- Max frames: {maximum}",
                "",
            ]
        )

    if audio_error:
        lines.extend(["## Audio Notes", "", f"- {audio_error}", ""])

    if cleanup_note:
        lines.extend(["## Cleanup", "", f"- {cleanup_note}", ""])

    if errors:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")

    lines.extend(mode_sections(mode))

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
    parser.add_argument(
        "--transcriber",
        choices=["groq", "openai", "none"],
        default="groq",
        help="Transcription fallback provider when captions are missing or weak (default: groq)",
    )
    parser.add_argument(
        "--mode",
        choices=REPORT_MODES,
        default="general",
        help="Report scaffold to generate (default: general)",
    )
    parser.add_argument("--frames", dest="frames", action="store_true", default=True, help="Extract frames")
    parser.add_argument("--no-frames", dest="frames", action="store_false", help="Skip frame extraction")
    parser.add_argument(
        "--frame-mode",
        choices=["auto", "interval"],
        default="auto",
        help="Use automatic frame budgeting or a fixed interval (default: auto)",
    )
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between frames in interval mode (default: 5)",
    )
    parser.add_argument("--fps", type=float, help="Explicit FPS override, capped at 2")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help="Maximum extracted frames, hard-capped at 100 (default: 80)",
    )
    parser.add_argument(
        "--frame-width",
        "--resolution",
        type=int,
        default=DEFAULT_WIDTH,
        help="Output frame width in pixels (default: 960)",
    )
    parser.add_argument(
        "--frame-format",
        choices=sorted(FRAME_FORMATS),
        default="jpeg",
        help="Frame image format; use png for UI text (default: jpeg)",
    )
    parser.add_argument("--cleanup", action="store_true", help="Remove media/audio artifacts after report")
    parser.add_argument(
        "--cleanup-frames",
        action="store_true",
        help="With --cleanup, also remove extracted frames after report",
    )
    args = parser.parse_args()

    try:
        if args.cleanup_frames and not args.cleanup:
            raise ValueError("--cleanup-frames requires --cleanup")
        requested_start = parse_time(args.start)
        requested_end = parse_time(args.end)
        requested_duration = parse_time(args.duration)
        download_section = download_section_for_args(
            requested_start,
            requested_end,
            requested_duration,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        run_dir = create_run_dir(args.out_dir, args.source)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    media_dir = run_dir / "media"
    frames_dir = run_dir / "frames"

    print(f"[watch-video] run directory: {run_dir}", file=sys.stderr)

    caption_info: dict[str, object] | None
    if is_url(args.source):
        print("[watch-video] downloading source with yt-dlp", file=sys.stderr)
        video_path, caption_info, source_info = download_url(
            args.source,
            media_dir,
            download_section=download_section,
        )
    else:
        print("[watch-video] using local source", file=sys.stderr)
        video_path, caption_info, source_info = resolve_local(args.source)

    caption_path = Path(str(caption_info["path"])) if caption_info else None

    probe = ffprobe_metadata(video_path)
    total_duration = (
        float(probe["duration_seconds"])
        if isinstance(probe.get("duration_seconds"), (int, float))
        else None
    )
    source_total_duration = total_duration
    if isinstance(source_info.get("duration"), (int, float)):
        source_total_duration = float(source_info["duration"])
    try:
        clip_start, clip_end, clip_duration = resolve_range(
            requested_start,
            requested_end,
            requested_duration,
            total_duration=source_total_duration,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    focused = any(value is not None for value in [requested_start, requested_end, requested_duration])
    focused_download = is_url(args.source) and download_section is not None
    processing_start = None if focused_download else ((clip_start or 0.0) if focused else None)
    processing_duration = clip_duration if focused else None
    timestamp_offset = (clip_start or 0.0) if focused else None
    plan_duration = clip_duration if focused else source_total_duration
    try:
        frame_plan = resolve_frame_plan(
            plan_duration,
            focused=focused,
            frame_mode=args.frame_mode,
            frame_interval=args.frame_interval,
            fps=args.fps,
            max_frames=args.max_frames,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    audio_path = run_dir / "audio.mp3"
    errors: list[str] = []
    errors.extend(str(warning) for warning in frame_plan.get("warnings", []))
    audio_error: str | None = None

    try:
        extract_audio_clip(
            video_path,
            audio_path,
            start=processing_start,
            duration=processing_duration,
        )
    except (RuntimeError, ValueError) as exc:
        audio_error = str(exc)
        errors.append(audio_error)

    transcript_source = "none"
    transcript_segments: list[dict[str, object]] = []
    raw_transcript: dict[str, object] = {"source": "none", "segments": []}
    captions_insufficient = False

    if caption_path is not None:
        try:
            all_caption_segments = parse_vtt(caption_path)
            transcript_segments = filter_segments(all_caption_segments, clip_start, clip_end)
            transcript_source = "native captions"
            coverage_seconds = transcript_coverage_seconds(all_caption_segments)
            coverage_ratio = caption_coverage_ratio(all_caption_segments, source_total_duration)
            captions_insufficient = captions_are_insufficient(
                all_caption_segments,
                source_total_duration,
            )
            if captions_insufficient:
                ratio_text = f"{coverage_ratio:.0%}" if coverage_ratio is not None else "unknown"
                errors.append(
                    "native captions look incomplete "
                    f"({coverage_seconds:.1f}s coverage, ratio {ratio_text}); trying fallback if available"
                )
            raw_transcript = {
                "source": "native_captions",
                "caption_path": str(caption_path),
                "caption_type": caption_info.get("caption_type") if caption_info else "unknown",
                "language": caption_info.get("language") if caption_info else None,
                "coverage_seconds": coverage_seconds,
                "coverage_ratio": coverage_ratio,
                "segments": transcript_segments,
            }
        except OSError as exc:
            errors.append(f"caption parse failed: {exc}")

    needs_transcription = (not transcript_segments or captions_insufficient) and args.transcriber != "none"
    if needs_transcription:
        if not audio_path.exists():
            errors.append(f"{args.transcriber} fallback skipped because no audio clip was available")
        else:
            try:
                raw_path = run_dir / f"{args.transcriber}_transcript.raw.json"
                provider_model = default_model(args.transcriber)
                transcriber_data = transcribe_audio(
                    audio_path,
                    out_json=raw_path,
                    model=provider_model,
                    provider=args.transcriber,
                )
                fallback_segments = segments_from_response(
                    transcriber_data,
                    offset_seconds=(clip_start or 0.0) if focused else 0.0,
                )
                if fallback_segments:
                    transcript_segments = fallback_segments
                    transcript_source = f"{args.transcriber} whisper"
                    raw_transcript = {
                        "source": f"{args.transcriber}_whisper",
                        "model": provider_model,
                        "raw_response_path": str(raw_path),
                        "segments": transcript_segments,
                    }
                else:
                    errors.append(f"{args.transcriber} fallback returned no transcript segments")
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
                start=processing_start,
                duration=processing_duration,
                frame_mode=args.frame_mode,
                frame_interval=args.frame_interval,
                fps=float(frame_plan["fps"]),
                max_frames=int(frame_plan["target_frames"]),
                width=args.frame_width,
                frame_format=args.frame_format,
                timestamp_offset=timestamp_offset,
            )
        except (RuntimeError, ValueError) as exc:
            errors.append(str(exc))

    metadata = {
        "source": args.source,
        "source_info": source_info,
        "video_path": str(video_path),
        "caption_path": str(caption_path) if caption_path else None,
        "caption_info": caption_info,
        "probe": probe,
        "range": {
            "start_seconds": clip_start,
            "end_seconds": clip_end,
            "duration_seconds": clip_duration,
            "focused": focused,
            "focused_download_section": download_section,
            "focused_download_requested": focused_download,
        },
        "frames": {
            "enabled": args.frames,
            "count": len(frames),
            "mode": args.frame_mode,
            "frame_interval": args.frame_interval,
            "fps": args.fps,
            "selected_fps": frame_plan.get("fps"),
            "target_frames": frame_plan.get("target_frames"),
            "max_frames": args.max_frames,
            "width": args.frame_width,
            "format": args.frame_format,
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
        frame_plan=frame_plan,
        mode=args.mode,
        download_section=download_section,
        cleanup_note=(
            "cleanup requested; media/audio will be removed"
            + (" and frames will be removed" if args.cleanup_frames else "; frames will be kept")
            if args.cleanup
            else None
        ),
    )
    report_path = run_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    try:
        removed = cleanup_artifacts(
            media_dir=media_dir,
            audio_path=audio_path,
            frames_dir=frames_dir,
            cleanup=args.cleanup,
            cleanup_frames=args.cleanup_frames,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if removed:
        metadata["cleanup"] = {
            "enabled": args.cleanup,
            "frames_removed": args.cleanup_frames,
            "removed_paths": removed,
        }
        write_json(run_dir / "metadata.json", metadata)

    print(f"[watch-video] report: {report_path}")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
