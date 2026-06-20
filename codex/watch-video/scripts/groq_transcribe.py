#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/watch-video/scripts/groq_transcribe.py
# Do not edit directly; edit the source path and run make build-packages.
# END GENERATED FROM SOURCE

"""Whisper transcription helper using only the Python standard library."""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import shutil
import subprocess
import time
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3-turbo"
DEFAULT_OPENAI_MODEL = "whisper-1"
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_MAX_429_RETRIES = 2


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
    key = api_key or os.environ.get(env_name, "")
    key = key.strip()
    if not key:
        raise RuntimeError(
            f"{env_name} is not set. fix: export {env_name}=... "
            "or add it to your local shell environment"
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

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
        body, boundary = _multipart_body(fields, audio)
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "agent-tools-watch-video/0.1",
            },
        )
        try:
            with urlopen(request, timeout=300) as response:
                payload = response.read().decode("utf-8", errors="replace")
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{label} returned non-JSON response: {payload[:200]}") from exc
        except HTTPError as exc:
            detail = _error_detail(exc)
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
            raise RuntimeError(f"{label} transcription failed: HTTP {exc.code}{detail}") from exc
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
    key = _read_key(provider, api_key)
    audio = Path(audio_path).expanduser().resolve()
    if not audio.exists():
        raise RuntimeError(f"audio file not found: {audio}")

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

    if out_json is not None:
        out_path = Path(out_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def segments_from_response(data: dict, *, offset_seconds: float = 0.0) -> list[dict[str, object]]:
    """Convert Groq verbose_json into normalized transcript segments."""
    segments: list[dict[str, object]] = []
    for segment in data.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = float(segment.get("start") or 0.0) + offset_seconds
        end = float(segment.get("end") or 0.0) + offset_seconds
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
        )

    if not segments:
        text = str(data.get("text") or "").strip()
        if text:
            segments.append(
                {
                    "start": round(offset_seconds, 3),
                    "end": round(offset_seconds, 3),
                    "text": text,
                }
            )
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
