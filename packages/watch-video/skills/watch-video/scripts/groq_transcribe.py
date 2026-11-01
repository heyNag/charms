#!/usr/bin/env python3
"""Whisper transcription helper using only the Python standard library."""

from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3"
DEFAULT_OPENAI_MODEL = "whisper-1"
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_MAX_429_RETRIES = 2
# Groq's free tier and OpenAI whisper-1 cap uploads at 25 MB. Target a margin
# under that so multipart framing overhead never pushes a chunk over.
MAX_UPLOAD_BYTES = 24_000_000
MAX_MULTIPART_BYTES = 25_000_000
CHUNK_SIZE_MARGIN_BYTES = 64_000
MAX_SPLIT_ATTEMPTS = 3
KEY_NAMES = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}

_PERM_WARNED: set[str] = set()


class TranscriptionError(RuntimeError):
    """A provider/configuration failure with an explicit chunk-stop decision."""

    def __init__(
        self, message: str, *, stop_remaining_chunks: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stop_remaining_chunks = stop_remaining_chunks
        self.http_status = http_status


class TranscriptionSegments(list):
    """List-compatible transcript with explicit missing intervals in source time."""

    def __init__(self, values=(), *, gaps=None, no_speech=False):
        super().__init__(values)
        self.gaps: list[dict[str, float]] = list(gaps or [])
        self.no_speech = bool(no_speech)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def config_env_path() -> Path:
    """Stored-key file for installed-skill use; env vars always win over it."""
    base = os.environ.get("WATCH_VIDEO_CONFIG_DIR", "~/.config/watch-video")
    return Path(base).expanduser() / ".env"


def _warn_loose_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    key = str(path)
    if key in _PERM_WARNED:
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        _PERM_WARNED.add(key)
        print(
            f"[watch-video] warning: {path} is readable by other users. "
            f"fix: chmod 600 {path}",
            file=sys.stderr,
        )


def _parse_env_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw or raw.startswith("#") or "=" not in raw:
        return None
    name, _, value = raw.partition("=")
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        value = value[1:-1]
    else:
        # Strip an inline comment from an unquoted value so
        # `GROQ_API_KEY=gsk_x  # note` does not poison the key.
        for index, char in enumerate(value):
            if char == "#" and index > 0 and value[index - 1] in " \t":
                value = value[:index].rstrip()
                break
    return name.strip(), value


def read_stored_key(name: str) -> str | None:
    """Read one key from the watch-video config file, if present."""
    path = config_env_path()
    if not path.is_file():
        return None
    _warn_loose_permissions(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        parsed = _parse_env_line(line)
        if parsed and parsed[0] == name and parsed[1]:
            return parsed[1]
    return None


def set_stored_key(name: str, value: str) -> Path:
    """Store a key in the config file with private permissions (0600)."""
    if name not in KEY_NAMES.values():
        raise ValueError(f"unsupported key name: {name}")
    value = value.strip()
    if not value:
        raise ValueError("refusing to store an empty key")
    if any(char in value for char in "\r\n"):
        raise ValueError("key must be a single line")

    path = config_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)

    lines: list[str] = []
    replaced = False
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed and parsed[0] == name:
                if not replaced:
                    lines.append(f"{name}={value}")
                    replaced = True
                continue
            lines.append(line)
    if not replaced:
        lines.append(f"{name}={value}")

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    return path


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed. fix: brew install ffmpeg")


def provider_label(provider: str) -> str:
    if provider == "groq":
        return "Groq"
    if provider == "openai":
        return "OpenAI"
    raise ValueError("provider must be groq or openai")


def provider_endpoint(provider: str) -> str:
    if provider == "groq":
        return GROQ_ENDPOINT
    if provider == "openai":
        return OPENAI_ENDPOINT
    raise ValueError("provider must be groq or openai")


def default_model(provider: str) -> str:
    if provider == "groq":
        return os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL
    if provider == "openai":
        return os.environ.get("OPENAI_TRANSCRIBE_MODEL") or DEFAULT_OPENAI_MODEL
    raise ValueError("provider must be groq or openai")


def _read_key(provider: str = "groq", api_key: str | None = None) -> str:
    env_name = "GROQ_API_KEY" if provider == "groq" else "OPENAI_API_KEY"
    key = api_key or os.environ.get(env_name, "") or (read_stored_key(env_name) or "")
    key = key.strip()
    if not key:
        raise TranscriptionError(
            f"{env_name} is not set. fix: export {env_name}=..., or store it once "
            f"with scripts/doctor.py --set-key {provider} (writes {config_env_path()})",
            stop_remaining_chunks=True,
        )
    return key


def extract_audio_clip(
    source: str | Path,
    out_path: str | Path,
    *,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
) -> Path:
    """Extract a mono 16 kHz MP3 audio clip suitable for Whisper."""
    _require_ffmpeg()
    if end is not None and duration is not None:
        raise ValueError("use either end or duration, not both")
    if start is not None and start < 0:
        raise ValueError("start must be non-negative")
    if end is not None and start is not None and end <= start:
        raise ValueError("end must be greater than start")
    if duration is not None and duration <= 0:
        raise ValueError("duration must be greater than zero")

    output = Path(out_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", str(source)])
    if duration is not None:
        cmd.extend(["-t", f"{duration:.3f}"])
    elif start is not None and end is not None:
        cmd.extend(["-t", f"{end - start:.3f}"])
    elif start is None and end is not None:
        cmd.extend(["-t", f"{end:.3f}"])
    cmd.extend(
        [
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(output),
        ]
    )

    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg audio extraction failed: {detail}")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no audio; the source may have no audio track")
    return output


def _multipart_body(fields: dict[str, str], audio_path: Path) -> tuple[bytes, str]:
    boundary = f"----WatchVideo{uuid.uuid4().hex}"
    eol = b"\r\n"
    body = io.BytesIO()

    for key, value in fields.items():
        body.write(f"--{boundary}".encode())
        body.write(eol)
        body.write(f'Content-Disposition: form-data; name="{key}"'.encode())
        body.write(eol)
        body.write(eol)
        body.write(str(value).encode())
        body.write(eol)

    mimetype = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    body.write(f"--{boundary}".encode())
    body.write(eol)
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"'.encode()
    )
    body.write(eol)
    body.write(f"Content-Type: {mimetype}".encode())
    body.write(eol)
    body.write(eol)
    body.write(audio_path.read_bytes())
    body.write(eol)
    body.write(f"--{boundary}--".encode())
    body.write(eol)

    return body.getvalue(), boundary


def _error_detail(exc: HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace")
    except Exception:
        payload = ""
    return f" - {payload[:500]}" if payload else ""


class _RefuseRedirects(HTTPRedirectHandler):
    """Never follow a redirect from the transcription endpoint.

    urllib's default handler re-sends every header, Authorization included,
    to the redirect target, even on another origin or over plain http. The
    Groq and OpenAI endpoints do not redirect, and a redirected POST would
    drop its upload anyway, so refusing costs nothing.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _open_without_redirects(request: Request, *, timeout: float):
    return build_opener(_RefuseRedirects).open(request, timeout=timeout)


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Parse Retry-After seconds or HTTP-date into a non-negative delay."""
    if not value:
        return None
    clean = value.strip()
    if not clean:
        return None
    try:
        return max(0.0, float(clean))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(clean)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    timestamp = parsed.timestamp()
    return max(0.0, timestamp - (time.time() if now is None else now))


def should_retry_http(status: int, *, attempt: int, max_attempts: int, retry_429_count: int, max_429_retries: int) -> bool:
    """Return whether an HTTP failure should be retried."""
    if attempt >= max_attempts:
        return False
    if status == 429:
        return retry_429_count < max_429_retries
    return 500 <= status <= 599


def retry_delay(
    attempt: int,
    *,
    retry_after: str | None = None,
    base_seconds: float = 1.0,
    max_seconds: float = 12.0,
) -> float:
    parsed = parse_retry_after(retry_after)
    if parsed is not None:
        return min(max_seconds, parsed)
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def _post_transcription(
    *,
    endpoint: str,
    key: str,
    fields: dict[str, str],
    audio: Path,
    provider: str,
    max_attempts: int,
    max_429_retries: int,
) -> dict:
    label = provider_label(provider)
    attempt = 1
    retry_429_count = 0
    last_error: str | None = None

    while attempt <= max_attempts:
        if audio.stat().st_size > MAX_UPLOAD_BYTES:
            raise RuntimeError(
                f"audio exceeds the {MAX_UPLOAD_BYTES:,}-byte upload budget; split it first"
            )
        body, boundary = _multipart_body(fields, audio)
        if len(body) > MAX_MULTIPART_BYTES:
            raise RuntimeError(
                f"multipart request exceeds the {MAX_MULTIPART_BYTES:,}-byte upload limit"
            )
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                # A custom User-Agent is load-bearing: Groq sits behind
                # Cloudflare, and the default Python-urllib UA can trip WAF
                # rules with a 403 before auth even runs.
                "User-Agent": "charms-watch-video/0.1",
            },
        )
        try:
            with _open_without_redirects(request, timeout=300) as response:
                payload = response.read().decode("utf-8", errors="replace")
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{label} returned non-JSON response: {payload[:200]}") from exc
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                exc.close()
                raise TranscriptionError(
                    f"{label} transcription failed: endpoint redirected (HTTP {exc.code}); "
                    "refusing to resend the API key",
                    stop_remaining_chunks=True, http_status=exc.code,
                ) from exc
            detail = _error_detail(exc)
            exc.close()
            if should_retry_http(
                exc.code,
                attempt=attempt,
                max_attempts=max_attempts,
                retry_429_count=retry_429_count,
                max_429_retries=max_429_retries,
            ):
                if exc.code == 429:
                    retry_429_count += 1
                last_error = f"HTTP {exc.code}{detail}"
                time.sleep(retry_delay(attempt, retry_after=exc.headers.get("Retry-After")))
                attempt += 1
                continue
            raise TranscriptionError(
                f"{label} transcription failed: HTTP {exc.code}{detail}",
                stop_remaining_chunks=exc.code in {401, 403, 404, 429},
                http_status=exc.code,
            ) from exc
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", str(exc))
            if attempt < max_attempts:
                last_error = str(reason)
                time.sleep(retry_delay(attempt))
                attempt += 1
                continue
            raise RuntimeError(f"{label} transcription failed: {reason}") from exc

    raise RuntimeError(f"{label} transcription failed after {max_attempts} attempts: {last_error or 'unknown error'}")


def transcribe_audio(
    audio_path: str | Path,
    *,
    out_json: str | Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    provider: str = "groq",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_429_retries: int = DEFAULT_MAX_429_RETRIES,
) -> dict:
    """POST an audio file and optionally save the verbose JSON response."""
    if provider not in {"groq", "openai"}:
        raise RuntimeError("transcriber provider must be groq or openai")
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file():
        raise RuntimeError(f"audio file not found: {audio}")
    if audio.stat().st_size > MAX_UPLOAD_BYTES:
        raise RuntimeError(
            f"audio exceeds the {MAX_UPLOAD_BYTES:,}-byte upload budget; split it first"
        )
    key = _read_key(provider, api_key)

    fields = {
        "model": model or default_model(provider),
        "response_format": "verbose_json",
        "temperature": "0",
    }
    data = _post_transcription(
        endpoint=endpoint or provider_endpoint(provider),
        key=key,
        fields=fields,
        audio=audio,
        provider=provider,
        max_attempts=max(1, int(max_attempts)),
        max_429_retries=max(0, int(max_429_retries)),
    )
    # Validate even for callers that consume the raw response directly. A
    # text-only response is not evidence that the words occurred at 0:00.
    segments_from_response(data)

    if out_json is not None:
        out_path = Path(out_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def audio_duration_seconds(audio_path: Path) -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is not installed. fix: brew install ffmpeg")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on audio clip: {result.stderr.strip()}")
    try:
        fmt = json.loads(result.stdout or "{}").get("format", {})
        duration = float(fmt.get("duration") or 0.0)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("invalid duration")
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("ffprobe returned invalid JSON for audio clip") from exc
    return duration


def plan_chunks(
    total_seconds: float,
    total_bytes: int,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> list[tuple[float, float]]:
    """Split a duration into contiguous (offset, duration) chunks under max_bytes.

    Size scales linearly with duration (constant-bitrate mono mp3), so an even
    time split yields evenly sized chunks. Returns one full-length chunk when
    the audio already fits.
    """
    if (
        not _is_finite_number(total_seconds)
        or total_seconds < 0
        or isinstance(total_bytes, bool)
        or not isinstance(total_bytes, int)
        or total_bytes < 0
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes <= 0
    ):
        raise RuntimeError("invalid audio chunk duration or byte budget")
    if total_bytes > max_bytes and total_seconds <= 0:
        raise RuntimeError("cannot split oversized audio with unknown duration")
    if total_bytes <= max_bytes:
        return [(0.0, total_seconds)]

    count = math.ceil(total_bytes / max_bytes)
    chunk = total_seconds / count
    plan: list[tuple[float, float]] = []
    for index in range(count):
        offset = round(index * chunk, 3)
        endpoint = round(total_seconds if index == count - 1 else (index + 1) * chunk, 3)
        duration = round(endpoint - offset, 3)
        if duration <= 0:
            raise RuntimeError("audio chunk budget is too small for millisecond-aligned chunks")
        plan.append((offset, duration))
    return plan


def split_audio(
    full_audio: Path,
    chunk_dir: Path,
    plan: list[tuple[float, float]],
) -> list[tuple[Path, float]]:
    """Slice audio into per-plan chunk files, returning (path, offset) pairs.

    Stream copy: no re-encode, no quality loss; mp3 frame boundaries are close
    enough for transcription purposes.
    """
    _require_ffmpeg()
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple[Path, float]] = []
    for index, (offset, duration) in enumerate(plan):
        out_path = chunk_dir / f"chunk_{index:03d}.mp3"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{offset:.3f}",
            "-i",
            str(full_audio),
            "-t",
            f"{duration:.3f}",
            "-c",
            "copy",
            str(out_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(
                f"ffmpeg failed to split audio chunk {index + 1}: {result.stderr.strip()}"
            )
        chunks.append((out_path, offset))
    return chunks


def _prepare_chunks(
    audio: Path, duration: float, size: int, max_bytes: int
) -> tuple[list[tuple[Path, float]], list[tuple[float, float]]]:
    """Check all actual chunk sizes before uploading; retry smaller splits at most twice."""
    margin = min(CHUNK_SIZE_MARGIN_BYTES, max(1, max_bytes // 20))
    planning_budget = max(1, max_bytes - margin)
    for _attempt in range(MAX_SPLIT_ATTEMPTS):
        plan = plan_chunks(duration, size, planning_budget)
        chunks = split_audio(audio, audio.parent / "audio_chunks", plan)
        if len(chunks) != len(plan):
            raise RuntimeError("audio splitter returned an incomplete chunk plan")
        sizes = [path.stat().st_size for path, _offset in chunks]
        if any(size <= 0 for size in sizes):
            raise RuntimeError("audio splitter returned an empty chunk; no chunks were uploaded")
        if all(size <= max_bytes for size in sizes):
            return chunks, plan
        planning_budget = max(1, planning_budget // 2)
    raise RuntimeError(
        f"audio chunks still exceed the {max_bytes:,}-byte upload budget after "
        f"{MAX_SPLIT_ATTEMPTS} splitting attempts; no chunks were uploaded"
    )


def transcribe_with_chunking(
    audio_path: str | Path,
    *,
    out_json: str | Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    provider: str = "groq",
    offset_seconds: float = 0.0,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[TranscriptionSegments, list[str]]:
    """Transcribe audio of any length, splitting past the provider upload cap.

    Chunks are transcribed independently and their segment timestamps shifted
    back into source time. A failed chunk is skipped with a warning so one bad
    slice does not discard the whole transcript. Provider-wide failures stop
    further uploads; raises RuntimeError only when no chunk succeeds.
    Returns (segments, warnings); segments.gaps contains
    failed intervals in source time, and segments.no_speech distinguishes a
    valid empty transcript from missing evidence.
    """
    audio = Path(audio_path).expanduser().resolve()
    if not audio.is_file():
        raise RuntimeError(f"audio file not found: {audio}")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise RuntimeError("invalid audio upload byte budget")
    if not _is_finite_number(offset_seconds) or offset_seconds < 0:
        raise RuntimeError("invalid transcription timestamp offset")
    max_bytes = min(max_bytes, MAX_UPLOAD_BYTES)

    size = audio.stat().st_size
    if size <= max_bytes:
        data = transcribe_audio(
            audio, out_json=out_json, model=model, api_key=api_key, provider=provider
        )
        return segments_from_response(data, offset_seconds=offset_seconds), []

    label = provider_label(provider)
    duration = audio_duration_seconds(audio)
    chunks, plan = _prepare_chunks(audio, duration, size, max_bytes)

    segments = TranscriptionSegments()
    raw_chunks: list[dict[str, object]] = []
    warnings: list[str] = []
    failures = 0
    last_failure: RuntimeError | None = None
    for index, (chunk_path, chunk_offset) in enumerate(chunks, start=1):
        try:
            data = transcribe_audio(
                chunk_path, out_json=None, model=model, api_key=api_key, provider=provider
            )
            chunk_segments = segments_from_response(
                data, offset_seconds=offset_seconds + chunk_offset
            )
        except RuntimeError as exc:
            last_failure = exc
            failures += 1
            interval_end = plan[index - 1][0] + plan[index - 1][1]
            segments.gaps.append(
                {
                    "start": round(offset_seconds + chunk_offset, 3),
                    "end": round(offset_seconds + interval_end, 3),
                }
            )
            warnings.append(
                f"{label} transcription chunk {index}/{len(chunks)} failed and was skipped: {exc}"
            )
            if isinstance(exc, TranscriptionError) and exc.stop_remaining_chunks:
                remaining = plan[index:]
                segments.gaps.extend(
                    {"start": round(offset_seconds + offset, 3),
                     "end": round(offset_seconds + offset + duration, 3)}
                    for offset, duration in remaining
                )
                failures += len(remaining)
                if remaining:
                    warnings.append(
                        f"{len(remaining)} remaining audio chunk(s) were not uploaded "
                        "after the provider/configuration failure."
                    )
                break
            continue
        segments.extend(chunk_segments)
        raw_chunks.append(
            {"index": index, "offset_seconds": chunk_offset, "response": data}
        )

    segments.no_speech = not segments and not segments.gaps

    if out_json is not None:
        out_path = Path(out_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chunked": True,
            "chunk_count": len(chunks),
            "chunks": raw_chunks,
            "gaps": segments.gaps,
            "no_speech": segments.no_speech,
        }
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if failures == len(chunks):
        raise TranscriptionError(
            f"{label} transcription failed for all {len(chunks)} audio chunks: {last_failure}",
            stop_remaining_chunks=(
                isinstance(last_failure, TranscriptionError) and last_failure.stop_remaining_chunks
            ),
            http_status=last_failure.http_status if isinstance(last_failure, TranscriptionError) else None,
        ) from last_failure
    return segments, warnings


def segments_from_response(data: object, *, offset_seconds: float = 0.0) -> TranscriptionSegments:
    """Validate timestamped Whisper output; never invent times for text-only output."""
    if not _is_finite_number(offset_seconds) or offset_seconds < 0:
        raise RuntimeError("invalid transcription timestamp offset")
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise RuntimeError("malformed transcription response: expected a segments array")
    segments = TranscriptionSegments()
    previous_start = -1.0
    for segment in data["segments"]:
        if not isinstance(segment, dict):
            raise RuntimeError("malformed transcription response: invalid segment")
        start, end, text = segment.get("start"), segment.get("end"), segment.get("text")
        if (
            not _is_finite_number(start)
            or not _is_finite_number(end)
            or start < 0
            or end < start
            or start < previous_start
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise RuntimeError("malformed transcription response: invalid timestamps or text")
        previous_start = start
        start += offset_seconds
        end += offset_seconds
        if not math.isfinite(start) or not math.isfinite(end):
            raise RuntimeError("malformed transcription response: timestamp offset overflow")
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text.strip(),
            }
        )

    text = data.get("text")
    if not segments and text is not None and (not isinstance(text, str) or text.strip()):
        raise RuntimeError("malformed transcription response: text has no timestamped segments")
    segments.no_speech = not segments
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe audio with Groq or OpenAI Whisper.")
    parser.add_argument("audio_file", help="Audio file to transcribe")
    parser.add_argument("--out", help="Path for the raw JSON response")
    parser.add_argument("--provider", choices=["groq", "openai"], default="groq")
    parser.add_argument(
        "--model",
        help=(
            f"Transcription model (Groq default: {DEFAULT_GROQ_MODEL}; "
            f"OpenAI default: {DEFAULT_OPENAI_MODEL})"
        ),
    )
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--quiet", action="store_true", help="Do not print JSON to stdout")
    args = parser.parse_args()

    try:
        data = transcribe_audio(
            args.audio_file,
            out_json=args.out,
            model=args.model,
            provider=args.provider,
            max_attempts=args.max_attempts,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    if not args.quiet:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
