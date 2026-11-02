"""Original-audio Whisper transcription through a local oMLX endpoint."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import uuid
from pathlib import Path

from groq_transcribe import (
    TranscriptionError,
    TranscriptionSegments,
    audio_duration_seconds,
    segments_from_response,
)
from local_api import LocalAPIError, LocalClient
from local_config import get_setting


DEFAULT_ASR_MODEL = "whisper-large-v3-asr-fp16"
DEFAULT_CHUNK_SECONDS = 300.0
RECOVERY_CHUNK_SECONDS = 60.0
MAX_AUDIO_BYTES = 24_000_000


class LocalTranscriptionValidationError(RuntimeError):
    """A known validation failure with the already-sanitized response attached."""

    def __init__(self, message, response):
        super().__init__(message)
        self.response = response


def default_model() -> str:
    return get_setting("WATCH_VIDEO_LOCAL_ASR_MODEL") or DEFAULT_ASR_MODEL


def _finite(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def extract_audio_clip(source, out_path, *, start=None, end=None, duration=None) -> Path:
    """Decode the source audio to mono 16 kHz PCM WAV without a lossy re-encode."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed; install FFmpeg before local audio analysis.")
    if end is not None and duration is not None:
        raise ValueError("use either end or duration, not both")
    if start is not None and (not _finite(start) or start < 0):
        raise ValueError("start must be finite and non-negative")
    if duration is not None and (not _finite(duration) or duration <= 0):
        raise ValueError("duration must be finite and positive")
    if end is not None and (not _finite(end) or end <= (start or 0)):
        raise ValueError("end must be finite and greater than start")
    output = Path(out_path).expanduser().resolve()
    input_path = Path(source).expanduser().resolve()
    if input_path == output:
        raise ValueError("Audio output must not overwrite the source file.")
    if not input_path.is_file():
        raise RuntimeError("Local audio source file does not exist.")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        command.extend(["-ss", f"{start:.6f}"])
    command.extend(["-i", str(input_path)])
    if duration is not None or end is not None:
        command.extend(["-t", f"{duration if duration is not None else end - (start or 0):.6f}"])
    command.extend(["-map", "0:a:0", "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
                    "-ac", "1", "-f", "wav", str(output)])
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode or not output.is_file() or output.stat().st_size <= 44:
        raise RuntimeError("FFmpeg could not extract PCM audio; verify the source has an audio track.")
    return output


def _multipart(audio: Path, model: str, language=None) -> tuple[bytes, str]:
    boundary = "----WatchVideoLocal" + uuid.uuid4().hex
    fields = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if language:
        fields["language"] = language
    # No supplied transcript or prompt is sent to ASR, so the transcription is
    # an independent reading of the original audio rather than caption copying.
    parts = []
    for name, value in fields.items():
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                      f"\r\n\r\n{value}\r\n").encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                  'filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode())
    parts.extend([audio.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    return b"".join(parts), boundary


def _validated_response(data: dict, *, duration: float | None = None):
    original = data
    # oMLX represents a valid empty Whisper segment list as null. Accept only
    # when there is an explicit empty text value; missing/malformed is not silence.
    if data.get("segments") is None and isinstance(data.get("text"), str) \
            and not data["text"].strip():
        data = {**data, "segments": []}
    try:
        parsed = segments_from_response(data)
    except RuntimeError as exc:
        # segments_from_response emits fixed validation descriptions, never
        # the model's response text. Preserve these actionable safe details.
        raise LocalTranscriptionValidationError(str(exc), original) from None
    if duration is not None:
        for segment in parsed:
            if segment["start"] > duration + 0.5 or segment["end"] > duration + 0.5:
                raise LocalTranscriptionValidationError(
                    "Local ASR returned timestamps beyond the audio chunk.", original,
                )
            segment["start"] = min(duration, segment["start"])
            segment["end"] = min(duration, segment["end"])
    return data, parsed


def transcribe_audio(audio_path, *, model=None, base_url=None, api_key=None, timeout=600,
                     language=None, client=None):
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
        raise RuntimeError("Local ASR needs a nonempty audio file below the 24 MB request limit.")
    client = client or LocalClient(base_url, api_key, timeout)
    body, boundary = _multipart(audio, model or default_model(), language)
    data = client.request_json("audio/transcriptions", body=body,
                               content_type=f"multipart/form-data; boundary={boundary}")
    data, _segments = _validated_response(data)
    return data


def _recovery_intervals(start: float, end: float) -> list[tuple[float, float]]:
    """One subdivision, at most five children; never repeat the original interval."""
    if end - start < 0.002:
        return []
    count = max(2, math.ceil((end - start) / RECOVERY_CHUNK_SECONDS))
    boundaries = [round(start + (end - start) * i / count, 3) for i in range(count + 1)]
    return [(a, b) for a, b in zip(boundaries, boundaries[1:]) if b > a]


def transcribe_with_chunking(audio_path, *, out_json=None, model=None, api_key=None,
                            base_url=None, timeout=600, offset_seconds=0.0,
                            chunk_seconds=DEFAULT_CHUNK_SECONDS, language=None):
    """Transcribe sequential five-minute PCM chunks, retaining source-time gaps.

    Malformed response evidence gets one attempt in smaller chunks; those
    children are never subdivided again. Returns the same list-compatible
    TranscriptionSegments/warnings contract as hosted transcription. Request or
    model failures never trigger cloud fallback.
    """
    if not _finite(offset_seconds) or offset_seconds < 0:
        raise ValueError("Transcription timestamp offset must be finite and non-negative.")
    if not _finite(chunk_seconds) or not 0 < chunk_seconds <= DEFAULT_CHUNK_SECONDS:
        raise ValueError("Local ASR chunk duration must be between 0 and 300 seconds.")
    client = LocalClient(base_url, api_key, timeout)
    model = model or default_model()
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file():
        raise RuntimeError("Local audio file does not exist.")
    duration = audio_duration_seconds(audio)
    if not _finite(duration) or duration <= 0:
        raise RuntimeError("Local audio duration could not be determined.")
    count = math.ceil(duration / chunk_seconds)
    # Millisecond boundaries avoid accumulating rounding gaps between chunks.
    plan = [(round(i * chunk_seconds, 3), round(min((i + 1) * chunk_seconds, duration), 3))
            for i in range(count)]
    segments = TranscriptionSegments()
    warnings, records = [], []
    successes = 0
    last_failure = None

    def gap(start, end):
        segments.gaps.append({"start": round(start + offset_seconds, 3),
                              "end": round(end + offset_seconds, 3)})

    def attempt(start, end, *, index, filename, extract):
        nonlocal successes, last_failure
        record = {"index": index, "offset_seconds": start, "duration_seconds": end - start}
        chunk = audio
        data = None
        try:
            if extract:
                chunk = extract_audio_clip(
                    audio, audio.parent / "audio_chunks" / filename,
                    start=start, duration=end - start,
                )
            data = transcribe_audio(chunk, model=model, client=client, language=language)
            data, parsed = _validated_response(data, duration=end - start)
            for segment in parsed:
                segment["start"] = round(segment["start"] + start + offset_seconds, 3)
                segment["end"] = round(segment["end"] + start + offset_seconds, 3)
            segments.extend(parsed)
            successes += 1
            record["response"] = data
            return record, None
        except (RuntimeError, OSError) as exc:
            # Local API errors and our fixed validation descriptions are safe
            # to persist; arbitrary process exceptions can contain private text.
            known_error = isinstance(exc, (LocalAPIError, LocalTranscriptionValidationError))
            message = str(exc) if known_error else "audio processing or timestamp validation failed"
            last_failure = exc
            record["error"] = message
            if isinstance(exc, LocalTranscriptionValidationError):
                data = exc.response
            if data is not None:
                # LocalClient already strips any echoed credential. Keep an
                # invalid timestamp response for diagnosis without treating it
                # as accepted transcript evidence or copying a prior chunk.
                record["response"] = data
            return record, exc

    for index, (start, end) in enumerate(plan):
        record, failure = attempt(start, end, index=index + 1, filename=f"chunk_{index:03d}.wav",
                                  extract=count > 1 or audio.stat().st_size > MAX_AUDIO_BYTES)
        records.append(record)
        if failure is None:
            continue
        stop_remaining = isinstance(failure, LocalAPIError) and failure.stop_remaining_chunks
        recovery_plan = _recovery_intervals(start, end) if isinstance(failure, LocalTranscriptionValidationError) else []
        if recovery_plan:
            recovery = {"strategy": "subdivide_once", "max_chunk_seconds": RECOVERY_CHUNK_SECONDS,
                        "chunk_count": len(recovery_plan), "chunks": [], "status": "complete"}
            record["recovery"] = recovery
            for child_index, (a, b) in enumerate(recovery_plan):
                child, child_failure = attempt(
                    a, b, index=child_index + 1,
                    filename=f"chunk_{index:03d}_recovery_{child_index:03d}.wav", extract=True,
                )
                recovery["chunks"].append(child)
                if child_failure is None:
                    continue
                recovery["status"] = "partial"
                gap(a, b)
                warnings.append(f"Local ASR recovery {child_index + 1}/{len(recovery_plan)} "
                                f"for chunk {index + 1}/{count} failed: {child['error']}.")
                if isinstance(child_failure, LocalAPIError) and child_failure.stop_remaining_chunks:
                    stop_remaining = True
                    for c, d in recovery_plan[child_index + 1:]:
                        gap(c, d)
                    break
            record["status"] = "recovered" if recovery["status"] == "complete" else "partial"
            outcome = (f"recovered using {len(recovery_plan)} smaller chunks" if recovery["status"] == "complete"
                       else "recovery remains incomplete")
            warnings.append(f"Local ASR chunk {index + 1}/{count} returned invalid evidence "
                            f"({record['error']}); {outcome}.")
        else:
            gap(start, end)
            warnings.append(f"Local ASR chunk {index + 1}/{count} failed: {record['error']}.")
        if stop_remaining:
            for a, b in plan[index + 1:]:
                gap(a, b)
            if index + 1 < count:
                warnings.append(f"{count - index - 1} remaining audio chunks skipped after local service failure.")
            break
    segments.no_speech = not segments and not segments.gaps
    if out_json is not None:
        output = Path(out_json).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        result = {"provider": "local", "model": model, "base_url": client.base_url,
                  "audio_format": "pcm_s16le_16000_mono",
                  "chunked": count > 1 or any("recovery" in record for record in records),
                  "chunk_count": count, "chunks": records, "gaps": segments.gaps,
                  "no_speech": segments.no_speech, "warnings": warnings}
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not successes:
        raise TranscriptionError(
            "Local ASR failed for every audio chunk; see the saved local ASR evidence for gaps.",
            stop_remaining_chunks=True,
            http_status=getattr(last_failure, "http_status", None),
        ) from None
    return segments, warnings
