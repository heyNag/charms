#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/codex-reset-credit/scripts/check_reset_credits.py
# Do not edit directly; edit the source path and run make rebuild-generated.
# END GENERATED FROM SOURCE

"""Show Codex reset credits and local rate-limit windows without printing auth secrets.

Ported from Nag's local dotfiles codex-reset-credit skill.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ENDPOINT = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
DEFAULT_TIMEOUT_SECONDS = 20.0


class AuthError(Exception):
    """Raised when local Codex auth cannot be used."""


class ResetCreditError(Exception):
    """Raised when reset credit data cannot be fetched."""


class SessionSnapshotError(Exception):
    """Raised when local Codex session snapshots cannot be read."""


@dataclasses.dataclass(frozen=True)
class CodexAuth:
    access_token: str
    account_id: str


@dataclasses.dataclass(frozen=True)
class RateLimitSnapshot:
    session_file: Path
    thread_id: str | None
    event_timestamp: str | None
    rate_limits: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Codex reset credits and rate-limit windows.")
    parser.add_argument(
        "--auth-file",
        default=None,
        help="Path to Codex auth JSON. Defaults to CODEX_HOME/auth.json, ~/.codex/auth.json, then Codex Desktop app-support auth.",
    )
    parser.add_argument(
        "--sessions-root",
        default=None,
        help="Override the Codex sessions directory used for local rate-limit windows.",
    )
    parser.add_argument(
        "--session-file",
        default=None,
        help="Read one specific Codex rollout JSONL file for rate-limit windows.",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Limit local session snapshot search to rollout files whose name contains this thread id.",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help="Timezone for rendered dates. Default: this machine's local timezone.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit sanitized JSON instead of text.",
    )
    parser.add_argument(
        "--no-live",
        action="store_true",
        help="Skip the live reset-credit endpoint and report local rate-limit windows only.",
    )
    parser.add_argument(
        "--show-source",
        action="store_true",
        help="Include local source file/thread metadata in output. Never includes auth paths or tokens.",
    )
    args = parser.parse_args(argv)

    timezone = ZoneInfo(args.timezone) if args.timezone else _local_timezone()
    reset_summary: dict[str, Any] | None = None
    reset_error: str | None = None
    snapshot_summary: dict[str, Any] | None = None
    snapshot_error: str | None = None

    if not args.no_live:
        try:
            auth = load_auth(args.auth_file)
            reset_summary = normalize_reset_credits(fetch_reset_credits(auth), timezone)
        except (AuthError, ResetCreditError) as exc:
            reset_error = str(exc)

    try:
        snapshot = find_latest_rate_limit_snapshot(
            sessions_root=args.sessions_root,
            session_file=args.session_file,
            thread_id=args.thread_id,
        )
        if snapshot is not None:
            snapshot_summary = normalize_rate_limit_snapshot(snapshot, timezone, show_source=args.show_source)
    except SessionSnapshotError as exc:
        snapshot_error = str(exc)

    output = {
        "reset_credits": reset_summary,
        "reset_credits_error": reset_error,
        "rate_limits": snapshot_summary,
        "rate_limits_error": snapshot_error,
    }

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(format_report(output))

    if reset_summary is None and snapshot_summary is None:
        return 1
    return 0


def load_auth(explicit_auth_file: str | None = None) -> CodexAuth:
    candidates = auth_candidates(explicit_auth_file)
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                auth_json = json.load(handle)
        except json.JSONDecodeError as exc:
            raise AuthError("Codex auth file is not valid JSON.") from exc
        except OSError as exc:
            raise AuthError(f"Could not read Codex auth file: {exc}") from exc

        if not isinstance(auth_json, dict):
            raise AuthError("Codex auth file did not contain a JSON object.")
        return extract_auth(auth_json)

    searched = ", ".join(_redact_home(path) for path in candidates)
    raise AuthError(f"Codex auth file not found. Searched: {searched}")


def auth_candidates(explicit_auth_file: str | None = None) -> list[Path]:
    if explicit_auth_file:
        return [Path(explicit_auth_file).expanduser()]

    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return _dedupe_paths(
        [
            codex_home / "auth.json",
            Path.home() / ".codex" / "auth.json",
            Path.home() / "Library/Application Support/Parall/Codex/.codex/auth.json",
        ]
    )


def extract_auth(auth_json: dict[str, Any]) -> CodexAuth:
    access_token = _first_string(
        auth_json,
        (
            ("tokens", "access_token"),
            ("tokens", "accessToken"),
            ("access_token",),
            ("accessToken",),
        ),
    )
    account_id = _first_string(
        auth_json,
        (
            ("account", "id"),
            ("tokens", "account_id"),
            ("tokens", "accountId"),
            ("account_id",),
            ("accountId",),
            ("profile", "account_id"),
            ("profile", "accountId"),
        ),
    )

    if not access_token:
        raise AuthError("Could not find an access token in Codex auth.")
    if not account_id:
        raise AuthError("Could not find an account ID in Codex auth.")

    return CodexAuth(access_token=access_token, account_id=account_id)


def fetch_reset_credits(auth: CodexAuth, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = urllib.request.Request(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {auth.access_token}",
            "ChatGPT-Account-ID": auth.account_id,
            "OpenAI-Beta": "codex-1",
            "originator": "Codex Desktop",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "codex-reset-credit/0.2",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ResetCreditError(f"Endpoint returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ResetCreditError(f"Could not reach reset credit endpoint: {reason}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ResetCreditError("Endpoint response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ResetCreditError("Endpoint response did not contain a JSON object.")
    return parsed


def normalize_reset_credits(data: dict[str, Any], timezone: dt.tzinfo) -> dict[str, Any]:
    raw_credits = _find_credits(data)
    credits: list[dict[str, Any]] = []

    for index, credit in enumerate(raw_credits, start=1):
        expires_at = _find_first(credit, ("expires_at", "expiresAt", "expiration_time", "expirationTime"))
        granted_at = _find_first(credit, ("granted_at", "grantedAt", "created_at", "createdAt"))
        expires_local, time_until_expiry, expires_sort = _format_datetime_with_remaining(expires_at, timezone)
        granted_local, _, _ = _format_datetime_with_remaining(granted_at, timezone)
        credits.append(
            {
                "index": index,
                "status": _display_string(_find_first(credit, ("status", "state"))),
                "granted_at_local": granted_local,
                "expires_at_local": expires_local,
                "time_until_expiry": time_until_expiry,
                "_expires_sort": expires_sort,
            }
        )

    credits.sort(key=lambda item: item["_expires_sort"] or dt.datetime.max.replace(tzinfo=dt.timezone.utc))
    for credit in credits:
        credit.pop("_expires_sort", None)

    available = _find_first(
        data,
        ("available_reset_credits", "availableResetCredits", "available_count", "availableCount", "available"),
    )
    if available is None and credits:
        available = sum(1 for credit in credits if credit.get("status") == "available")
    total_earned = _find_first(data, ("total_earned_count", "totalEarnedCount", "total_earned"))

    next_expiring = next((credit for credit in credits if credit.get("status") == "available"), None)
    if next_expiring is None and credits:
        next_expiring = credits[0]

    return {
        "source": "live_reset_credit_endpoint",
        "available": _display_count(available),
        "total_earned": _display_count(total_earned),
        "next_expiring_credit": next_expiring,
        "credits": credits,
    }


def find_latest_rate_limit_snapshot(
    *,
    sessions_root: str | None,
    session_file: str | None,
    thread_id: str | None,
) -> RateLimitSnapshot | None:
    files = candidate_session_files(sessions_root=sessions_root, session_file=session_file, thread_id=thread_id)
    for path in files:
        snapshot = extract_snapshot(path)
        if snapshot is not None:
            return snapshot
    return None


def candidate_session_files(
    *,
    sessions_root: str | None,
    session_file: str | None,
    thread_id: str | None,
) -> list[Path]:
    if session_file:
        path = Path(session_file).expanduser()
        if not path.exists():
            raise SessionSnapshotError(f"Session file not found: {_redact_home(path)}")
        return [path]

    files: list[Path] = []
    for root in session_roots(sessions_root):
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("rollout-*.jsonl") if not thread_id or thread_id in path.name)

    return sorted(files, key=lambda path: _safe_mtime(path), reverse=True)


def session_roots(explicit_root: str | None = None) -> list[Path]:
    if explicit_root:
        return [Path(explicit_root).expanduser()]

    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return _dedupe_paths(
        [
            codex_home / "sessions",
            Path.home() / ".codex" / "sessions",
            Path.home() / "Library/Application Support/Parall/Codex/.codex/sessions",
        ]
    )


def extract_snapshot(session_file: Path) -> RateLimitSnapshot | None:
    thread_id = None
    latest: RateLimitSnapshot | None = None

    try:
        with session_file.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") == "session_meta":
                    payload = entry.get("payload", {})
                    if isinstance(payload, dict):
                        thread_id = _string_or_none(payload.get("id")) or thread_id

                if entry.get("type") != "event_msg":
                    continue
                payload = entry.get("payload", {})
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits")
                if not isinstance(rate_limits, dict):
                    continue

                latest = RateLimitSnapshot(
                    session_file=session_file,
                    thread_id=thread_id,
                    event_timestamp=_string_or_none(entry.get("timestamp")),
                    rate_limits=rate_limits,
                )
    except OSError:
        return None

    return latest


def normalize_rate_limit_snapshot(
    snapshot: RateLimitSnapshot,
    timezone: dt.tzinfo,
    *,
    show_source: bool = False,
) -> dict[str, Any]:
    rate_limits = snapshot.rate_limits
    result: dict[str, Any] = {
        "source": "local_session_snapshot",
        "snapshot_timestamp": snapshot.event_timestamp,
        "plan_type": _display_string(rate_limits.get("plan_type")),
        "limit_name": _display_string(rate_limits.get("limit_name")),
        "rate_limit_reached_type": _display_string(rate_limits.get("rate_limit_reached_type")),
        "primary": normalize_rate_limit_window(rate_limits.get("primary"), timezone),
        "secondary": normalize_rate_limit_window(rate_limits.get("secondary"), timezone),
    }
    if show_source:
        result["session_file"] = str(snapshot.session_file)
        result["thread_id"] = snapshot.thread_id
    return result


def normalize_rate_limit_window(value: Any, timezone: dt.tzinfo) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    reset_local, time_until_reset, _ = _format_datetime_with_remaining(value.get("resets_at"), timezone)
    return {
        "used_percent": value.get("used_percent"),
        "window_minutes": value.get("window_minutes"),
        "resets_at_local": reset_local,
        "time_until_reset": time_until_reset,
    }


def format_report(output: dict[str, Any]) -> str:
    lines: list[str] = []

    reset_summary = output.get("reset_credits")
    if isinstance(reset_summary, dict):
        lines.append("Reset credits")
        lines.append(f"  Available: {reset_summary.get('available')}")
        lines.append(f"  Total earned: {reset_summary.get('total_earned')}")
        next_expiring = reset_summary.get("next_expiring_credit")
        if isinstance(next_expiring, dict):
            lines.append(
                "  Next expiry: "
                f"{next_expiring.get('expires_at_local')} "
                f"({next_expiring.get('time_until_expiry') or 'remaining time unknown'})"
            )
        credits = reset_summary.get("credits")
        if isinstance(credits, list) and credits:
            for credit in credits:
                if not isinstance(credit, dict):
                    continue
                status = credit.get("status") or "unknown"
                expiry = credit.get("expires_at_local") or "unknown expiry"
                remaining = credit.get("time_until_expiry") or "remaining time unknown"
                lines.append(f"  #{credit.get('index')} {status}: expires {expiry} ({remaining})")
    elif output.get("reset_credits_error"):
        lines.append("Reset credits")
        lines.append(f"  Unavailable: {output['reset_credits_error']}")

    rate_limits = output.get("rate_limits")
    if lines and (isinstance(rate_limits, dict) or output.get("rate_limits_error")):
        lines.append("")

    if isinstance(rate_limits, dict):
        lines.append("Rate-limit windows")
        if rate_limits.get("snapshot_timestamp"):
            lines.append(f"  Snapshot: {rate_limits.get('snapshot_timestamp')}")
        if rate_limits.get("plan_type") != "unknown":
            lines.append(f"  Plan: {rate_limits.get('plan_type')}")
        if rate_limits.get("rate_limit_reached_type") != "unknown":
            lines.append(f"  Reached type: {rate_limits.get('rate_limit_reached_type')}")
        if rate_limits.get("session_file"):
            lines.append(f"  Source file: {rate_limits.get('session_file')}")
        if rate_limits.get("thread_id"):
            lines.append(f"  Thread ID: {rate_limits.get('thread_id')}")
        for label in ("primary", "secondary"):
            window = rate_limits.get(label)
            if not isinstance(window, dict):
                continue
            lines.append(f"  {label.title()}:")
            lines.append(f"    Used: {_display_percent(window.get('used_percent'))}")
            lines.append(f"    Window: {_display_window_minutes(window.get('window_minutes'))}")
            lines.append(f"    Resets: {window.get('resets_at_local') or 'unknown'}")
            lines.append(f"    Remaining: {window.get('time_until_reset') or 'unknown'}")
    elif output.get("rate_limits_error"):
        lines.append("Rate-limit windows")
        lines.append(f"  Unavailable: {output['rate_limits_error']}")

    if not lines:
        lines.append("No Codex reset-credit or rate-limit data found.")
    return "\n".join(lines)


def _first_string(data: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        value: Any = data
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if isinstance(value, str) and value:
            return value
    return None


def _find_first(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _find_credits(data: dict[str, Any]) -> list[dict[str, Any]]:
    for name in ("reset_credits", "resetCredits", "credits", "items"):
        value = data.get(name)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _format_datetime_with_remaining(value: Any, timezone: dt.tzinfo) -> tuple[str | None, str | None, dt.datetime | None]:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None, None, None
    local = parsed.astimezone(timezone)
    remaining = local.timestamp() - dt.datetime.now(tz=timezone).timestamp()
    return _format_datetime(local), _human_duration(remaining), parsed


def _parse_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        return _to_aware_utc(parsed)
    return None


def _format_datetime(value: dt.datetime) -> str:
    return f"{value:%Y-%m-%d %H:%M:%S %Z}".strip()


def _human_duration(seconds: float) -> str:
    remaining = max(int(round(seconds)), 0)
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _display_count(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "unknown"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _display_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _display_percent(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "unknown"
    if isinstance(value, (int, float)):
        return f"{value:g}%"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _display_window_minutes(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "unknown"
    if isinstance(value, int):
        if value % 1440 == 0:
            return f"{value // 1440}d ({value} minutes)"
        if value % 60 == 0:
            return f"{value // 60}h ({value} minutes)"
        return f"{value} minutes"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _local_timezone() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def _to_aware_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        deduped.append(path)
        seen.add(key)
    return deduped


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _redact_home(path: Path) -> str:
    try:
        return str(path).replace(str(Path.home()), "~", 1)
    except RuntimeError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
