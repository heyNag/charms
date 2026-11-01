"""Caption parsing, range coverage, and conservative rolling-cue deduplication."""
from __future__ import annotations

import html
import re
from pathlib import Path

_TIME = r"(?:\d+:)?\d{2}:\d{2}[.,]\d{3}"
TIMESTAMP_RE = re.compile(rf"^(?P<start>{_TIME})\s+-->\s+(?P<end>{_TIME})(?P<settings>.*)$")
TAG_RE = re.compile(r"<[^>]+>")


def vtt_time_to_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    hours, minutes, seconds = (["0", *parts] if len(parts) == 2 else parts)
    if not 0 <= int(minutes) < 60 or not 0 <= float(seconds) < 60:
        raise ValueError("invalid caption timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_text(lines: list[str]) -> str:
    return " ".join(html.unescape(TAG_RE.sub("", line)).strip() for line in lines).strip()


def _trim_word_overlap(previous: str, current: str) -> str:
    old, new = previous.split(), current.split()
    for size in range(min(len(old), len(new)), 0, -1):
        if old[-size:] == new[:size]:
            if size >= 3 or size == len(new):
                return " ".join(new[size:])
            break
    return current


def append_caption_segment(
    segments, start, end, text, *, region="", speaker="", display_refresh=False
) -> None:
    text = " ".join(text.split())
    if not text or end <= start:
        return
    segment = {"start": round(start, 3), "end": round(end, 3), "text": text}
    if region:
        segment["region"] = region
    if speaker:
        segment["speaker"] = speaker
    if segments:
        previous = segments[-1]
        same_display = previous.get("region", "") == region and previous.get("speaker", "") == speaker
        old = previous["text"]
        overlaps = float(previous["start"]) <= start < float(previous["end"])
        # YouTube inserts tiny padded display-refresh cues between rolling
        # windows. They repeat the previous line without new speech. Other
        # touching identical cues remain independent repeated utterances.
        touches = abs(start - float(previous["end"])) < 0.001 and (text != old or display_refresh)
        if same_display and (overlaps or touches):
            extended_end = round(max(end, float(previous["end"])), 3)
            if text == old or old.startswith(text + " ") or old.endswith(" " + text):
                previous["end"] = extended_end
                return
            if text.startswith(old + " "):
                previous.update(text=text, end=extended_end)
                return
            trimmed = _trim_word_overlap(old, text)
            if trimmed != text:
                if not trimmed:
                    previous["end"] = extended_end
                    return
                segment["text"] = trimmed
    segments.append(segment)


def parse_vtt(path: Path) -> list[dict[str, object]]:
    """Read VTT/SRT, including optional hours, voice labels and metadata blocks."""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    segments: list[dict[str, object]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line in {"STYLE", "REGION", "NOTE"} or line.startswith(("NOTE ", "NOTE\t")):
            index += 1
            while index < len(lines) and lines[index] != "":
                index += 1
            continue
        match = TIMESTAMP_RE.match(line)
        index += 1
        if not match:
            continue
        body = []
        # A whitespace-only line is display padding, not an empty separator.
        # YouTube commonly places one before the first spoken line in a cue.
        while index < len(lines) and lines[index] != "":
            if TIMESTAMP_RE.match(lines[index].strip()):
                break
            # A cue identifier may appear without the recommended blank line.
            if lines[index].strip().isdigit() and index + 1 < len(lines) and TIMESTAMP_RE.match(lines[index + 1].strip()):
                break
            body.append(lines[index])
            index += 1
        try:
            start = vtt_time_to_seconds(match["start"])
            end = vtt_time_to_seconds(match["end"])
        except ValueError:
            continue
        voices = {html.unescape(voice).strip() for voice in re.findall(r"<v(?:\.[^\s>]*)?\s+([^>]+)>", " ".join(body))}
        display_refresh = (
            0 < end - start <= 0.02 + 1e-9
            and any(line != "" and not line.strip() for line in body)
            and not re.search(rf"<{_TIME}>", " ".join(body))
        )
        append_caption_segment(
            segments, start, end, clean_caption_text(body),
            region=" ".join(match["settings"].split()),
            speaker=next(iter(voices)) if len(voices) == 1 else "",
            display_refresh=display_refresh,
        )
    return segments


def filter_segments(segments, start, end):
    low = start if start is not None else float("-inf")
    high = end if end is not None else float("inf")
    return [s for s in segments if float(s["end"]) > low and float(s["start"]) < high]


def clipped_segments(segments, start=None, end=None):
    return [
        {**s, "start": max(float(s["start"]), start) if start is not None else float(s["start"]),
         "end": min(float(s["end"]), end) if end is not None else float(s["end"])}
        for s in filter_segments(segments, start, end)
    ]


def transcript_coverage_seconds(segments, *, start=None, end=None) -> float:
    intervals = sorted((s["start"], s["end"]) for s in clipped_segments(segments, start, end) if s["end"] > s["start"])
    merged: list[list[float]] = []
    for low, high in intervals:
        if not merged or low > merged[-1][1]:
            merged.append([low, high])
        else:
            merged[-1][1] = max(merged[-1][1], high)
    return round(sum(high - low for low, high in merged), 3)


def caption_coverage_ratio(segments, total_duration, *, start=None, end=None):
    high = min(end, total_duration) if end is not None and total_duration is not None else end
    high = total_duration if high is None else high
    duration = high - (start or 0.0) if high is not None else None
    if duration is None or duration <= 0:
        return None
    return round(min(1.0, transcript_coverage_seconds(segments, start=start, end=high) / duration), 4)


def captions_are_insufficient(segments, total_duration, *, threshold=0.5, start=None, end=None):
    selected = filter_segments(segments, start, end)
    if not selected:
        return True
    if total_duration is not None and total_duration < 30:
        return False
    # A finite requested range gives enough information to assess coverage
    # even when the source metadata does not report the full duration.
    ratio = caption_coverage_ratio(selected, total_duration, start=start, end=end)
    return ratio is not None and ratio < threshold
