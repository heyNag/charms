"""Preserve supplied TXT/SRT transcripts as separate supporting evidence."""

from __future__ import annotations

import codecs
import hashlib
import html
import math
import re
from pathlib import Path

from captions import TIMESTAMP_RE, vtt_time_to_seconds


_HEADER = re.compile(r"^\s*\[([0-9]{2,}):([0-5][0-9]):([0-5][0-9])([.][0-9]+)?\]\s*(.*)$")
_TIME_LIKE = re.compile(r"^\s*\[[+-]?[0-9][^\]\r\n]*:")
_SRT_TIME_LIKE = re.compile(r"^\s*[+-]?[0-9]+:[^\r\n]*-->")
_SPEAKER = re.compile(r"^([^:\[\]\r\n]+):\s*(.*)$")


def discover_supporting_transcripts(video_path: Path) -> list[Path]:
    """Return exact-name sidecars, with TXT files first and every match retained."""
    names = {
        video_path.stem: 0,
        f"{video_path.stem}_transcript": 1,
        f"{video_path.stem}_transcript_grouped": 2,
    }
    matches = [
        entry for entry in video_path.parent.iterdir()
        if not entry.is_symlink() and entry.is_file()
        and entry.suffix.lower() in {".txt", ".srt"} and entry.stem in names
    ]
    return sorted(matches, key=lambda entry: (
        0 if entry.suffix.lower() == ".txt" else 1, names[entry.stem], entry.name,
    ))


def _txt_blocks(text: str) -> tuple[list[dict], list[str]]:
    blocks: list[dict] = []
    warnings: list[str] = []
    lines: list[str] = []
    metadata: dict = {}
    previous_start: float | None = None

    def flush() -> None:
        content = "\n".join(lines).strip()
        if content or metadata:
            blocks.append({**metadata, "text": content})
        lines.clear()

    for line_number, line in enumerate(text.splitlines(), start=1):
        header = _HEADER.match(line)
        start = None
        if header:
            hours, minutes, seconds, fraction, remainder = header.groups()
            try:
                start = float(int(hours) * 3600 + int(minutes) * 60 + int(seconds)) + float(fraction or 0)
            except (ValueError, OverflowError):
                pass
            if start is not None and not math.isfinite(start):
                start = None
        if start is not None:
            flush()
            metadata = {"start": start}
            speaker = _SPEAKER.match(remainder)
            if speaker and speaker.group(1).strip():
                metadata["speaker"] = speaker.group(1).strip()
                remainder = speaker.group(2)
            lines.append(remainder)
            if previous_start is not None and start < previous_start:
                warnings.append(f"Line {line_number}: block start precedes the previous timestamp; source order preserved.")
            previous_start = start
        elif _TIME_LIKE.match(line):
            # Do not attribute a malformed new block to the previous valid time.
            flush()
            metadata = {}
            lines.append(line)
            warnings.append(f"Line {line_number}: unsupported or malformed timestamp retained as untimed text.")
        else:
            lines.append(line)
    flush()
    return blocks, warnings


def _srt_blocks(text: str) -> tuple[list[dict], list[str]]:
    """Read cue paragraphs without rolling-caption cleanup or invented times."""
    chunks: list[tuple[int, list[str]]] = []
    lines: list[str] = []
    first_line = 1
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not lines:
                first_line = line_number
            lines.append(line)
        elif lines:
            chunks.append((first_line, lines))
            lines = []
    if lines:
        chunks.append((first_line, lines))

    blocks: list[dict] = []
    warnings: list[str] = []
    for first_line, lines in chunks:
        timing_index = 1 if lines[0].strip().isdigit() else 0
        timing = lines[timing_index].strip() if timing_index < len(lines) else ""
        match = TIMESTAMP_RE.match(timing)
        body = lines[timing_index + 1:]
        try:
            # SRT has no arbitrary text after its end timestamp. Refuse extra
            # timing lines too, rather than assigning several cues one range.
            if not match or match["settings"].strip() or any(_SRT_TIME_LIKE.match(line) for line in body):
                raise ValueError("unsupported cue structure")
            start = vtt_time_to_seconds(match["start"])
            end = vtt_time_to_seconds(match["end"])
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("invalid cue range")
        except (ValueError, OverflowError):
            blocks.append({"text": "\n".join(lines)})
            warnings.append(f"Line {first_line}: unsupported or malformed SRT cue retained as untimed text.")
            continue
        content = "\n".join(body)
        block = {"start": start, "end": end, "text": content}
        voices = {
            html.unescape(voice).strip()
            for voice in re.findall(r"<v(?:\.[^\s>]*)?\s+([^>]+)>", content)
            if html.unescape(voice).strip()
        }
        if len(voices) == 1:
            block["speaker"] = next(iter(voices))
        blocks.append(block)
    return blocks, warnings


def load_supporting_transcript(path: Path) -> dict:
    """Preserve original text and only the timing supplied by its file format.

    Filesystem and decoding exceptions are intentionally left to the caller.
    Untimed text is evidence too: it remains in ``text`` and untimed blocks.
    """
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    text = raw.decode(encoding)
    is_srt = path.suffix.lower() == ".srt"
    blocks, warnings = _srt_blocks(text) if is_srt else _txt_blocks(text)
    timestamps = "cue_range" if is_srt else "block_start"
    return {
        "path": str(path),
        "role": "supporting",
        "provenance": "supplied_transcript",
        "timestamps": timestamps if any("start" in block for block in blocks) else "unavailable",
        "content_hash": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "text": text,
        "blocks": blocks,
        "warnings": warnings,
    }
