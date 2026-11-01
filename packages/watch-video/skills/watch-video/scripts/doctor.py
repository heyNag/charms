#!/usr/bin/env python3
"""Watch Video preflight checks and one-time Whisper key storage."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from groq_transcribe import (  # noqa: E402
    KEY_NAMES,
    config_env_path,
    read_stored_key,
    set_stored_key,
)
from gemini import is_youtube_url  # noqa: E402
from watch import default_run_root, is_url  # noqa: E402


MIN_PYTHON = (3, 11)
ENV_LOCAL = ".env" + ".local"
# Key checks are advisory: watch-video still works caption/frames-only.
ADVISORY_CHECKS = {
    "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "whisper-config", "run-artifacts",
    "WATCH_VIDEO_LOCAL_API_KEY", "local-models",
}
RUN_ARTIFACTS_WARN_BYTES = 500 * 1024 * 1024
LOCAL_BINARIES = ("yt-dlp", "ffmpeg", "ffprobe")


def required_binaries(
    engine: str = "local", source: str | None = None, from_run: str | None = None,
) -> list[str]:
    """Match the runtime's source routing without downloading or opening a file."""
    if engine not in {"local", "gemini"}:
        raise ValueError("engine must be local or gemini")
    if from_run is not None:
        if engine != "local":
            raise ValueError("--from-run applies only to --engine local")
        return ["ffmpeg", "ffprobe"]
    # No source means a general toolkit check, not a claim about a specific flow.
    if source is None:
        return list(LOCAL_BINARIES)
    remote = is_url(source)
    if engine == "gemini" and (not remote or is_youtube_url(source)):
        return []
    return list(LOCAL_BINARIES if remote else ("ffmpeg", "ffprobe"))


def install_hints(binaries: list[str] | None = None) -> dict[str, list[str]]:
    packages = _brew_packages(list(LOCAL_BINARIES) if binaries is None else binaries)
    return {
        "macOS": [f"brew install {' '.join(packages)}"] if packages else [],
        "Linux": (
            (["sudo apt install ffmpeg"] if "ffmpeg" in packages else [])
            + (["pipx install yt-dlp"] if "yt-dlp" in packages else [])
        ),
    }


def current_platform(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Linux":
        return "Linux"
    return "Unsupported"


def platform_hints(binaries: list[str] | None = None) -> list[str]:
    hints = install_hints(binaries)
    return hints.get(current_platform(), ["watch-video supports macOS and Linux only"])


def check_platform(system: str | None = None) -> dict[str, object]:
    name = current_platform(system)
    ok = name != "Unsupported"
    return {
        "name": "platform",
        "ok": ok,
        "platform": name,
        "message": "ok" if ok else "unsupported operating system",
        "fix": "Use watch-video on macOS or Linux.",
    }


def check_python_version(version_info: tuple[int, int, int] | None = None) -> dict[str, object]:
    version = version_info or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    ok = (version[0], version[1]) >= MIN_PYTHON
    return {
        "name": "python",
        "ok": ok,
        "version": ".".join(str(part) for part in version),
        "message": "ok" if ok else f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required",
        "fix": "Use Python 3.11 or newer.",
    }


def check_binary(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {
        "name": name,
        "ok": path is not None,
        "path": path,
        "message": "ok" if path else f"{name} is not installed",
        "fix": "; ".join(platform_hints([name])),
    }


def key_shape_status(value: str | None, prefix: str = "gsk_") -> dict[str, object]:
    key = (value or "").strip()
    exists = bool(key)
    starts_with_prefix = key.startswith(prefix) if exists else False
    plausible_length = len(key) >= 20 if exists else False
    ok = exists and starts_with_prefix and plausible_length
    return {
        "exists": exists,
        "starts_with_prefix": starts_with_prefix,
        "plausible_length": plausible_length,
        "length": len(key) if exists else 0,
        "ok": ok,
    }


def _effective_key(name: str, env: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """Return (key, source) where source is environment | config | None."""
    environment = env if env is not None else os.environ
    value = (environment.get(name) or "").strip()
    if value:
        return value, "environment"
    stored = read_stored_key(name)
    if stored:
        return stored, "config"
    return None, None


def check_whisper_key(
    provider: str,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    name = KEY_NAMES[provider]
    prefix = "gsk_" if provider == "groq" else "sk-"
    value, source = _effective_key(name, env)
    shape = key_shape_status(value, prefix=prefix)
    if not shape["exists"]:
        message = f"{name} is not set; {provider} transcription fallback will be unavailable"
    elif not shape["starts_with_prefix"]:
        message = f"{name} is set but does not look like a {provider} key"
    elif not shape["plausible_length"]:
        message = f"{name} is set but length looks too short"
    else:
        message = f"ok ({source})"
    return {
        "name": name,
        "ok": bool(shape["ok"]),
        "message": message,
        "source": source,
        "safe_shape": shape,
        "fix": (
            f"export {name}=... or store it once with "
            f"scripts/doctor.py --set-key {provider}"
        ),
    }


def check_groq_key(env: dict[str, str] | None = None) -> dict[str, object]:
    return check_whisper_key("groq", env)


def check_gemini_key(env: dict[str, str] | None = None) -> dict[str, object]:
    environment = env if env is not None else os.environ
    present = bool((environment.get("GEMINI_API_KEY") or "").strip())
    return {
        "name": "GEMINI_API_KEY", "ok": present,
        "message": "present in environment (not validated)" if present else "not set; optional Gemini engine unavailable",
        "fix": "Provide GEMINI_API_KEY through your secret manager's environment injection.",
    }


def check_local_runtime(
    transcriber: str | None = None, analyzer: str = "none",
    env: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Check selected local configuration without connecting or loading models."""
    if transcriber != "local" and analyzer != "local":
        return []
    from local_api import validate_base_url

    environment = env if env is not None else os.environ
    try:
        endpoint = validate_base_url(
            environment.get("WATCH_VIDEO_LOCAL_BASE_URL") or "http://127.0.0.1:8147/v1"
        )
        endpoint_check = {
            "name": "local-endpoint", "ok": True,
            "message": f"{endpoint} (configuration only; server access not tested)",
        }
    except ValueError:
        # An invalid URL may contain credentials; never include its value.
        endpoint_check = {
            "name": "local-endpoint", "ok": False,
            "message": "local inference requires an HTTP(S) loopback /v1 endpoint",
            "fix": "Set WATCH_VIDEO_LOCAL_BASE_URL to the local server, for example http://127.0.0.1:8147/v1.",
        }
    key_present = bool((environment.get("WATCH_VIDEO_LOCAL_API_KEY") or "").strip())
    roles = []
    if transcriber == "local":
        roles.append("speech-to-text model")
    if analyzer == "local":
        roles.append("vision-language model")
    return [
        endpoint_check,
        {
            "name": "WATCH_VIDEO_LOCAL_API_KEY", "ok": key_present,
            "message": (
                "present in environment (not validated)" if key_present else
                "not set; required only if the local server enables authentication"
            ),
            "fix": "Inject WATCH_VIDEO_LOCAL_API_KEY through your secret manager when authentication is enabled.",
        },
        {
            "name": "local-models", "ok": True,
            "message": f"Requires a loaded or loadable {' and '.join(roles)}; model availability not tested",
        },
    ]


def validate_local_options(engine: str, transcriber: str | None, analyzer: str) -> None:
    if engine != "local" and (transcriber is not None or analyzer != "none"):
        raise ValueError("--transcriber and --analyzer apply only to --engine local")


def check_config_file() -> dict[str, object]:
    path = config_env_path()
    if not path.is_file():
        return {
            "name": "whisper-config",
            "ok": True,
            "exists": False,
            "message": f"no stored keys ({path} not created yet)",
        }
    if os.name != "posix":
        return {
            "name": "whisper-config",
            "ok": True,
            "exists": True,
            "message": "ok (permission bits are not enforced on this platform)",
        }
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = None
    private = mode is not None and mode & 0o077 == 0
    return {
        "name": "whisper-config",
        "ok": private,
        "exists": True,
        "mode": f"{mode:o}" if mode is not None else None,
        "message": "ok" if private else f"{path} is readable by other users",
        "fix": f"chmod 600 {path}",
    }


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def check_run_artifacts(run_root: Path | None = None) -> dict[str, object]:
    """Advisory disk check: downloaded media accumulates under run dirs."""
    root = (run_root or default_run_root()).expanduser()

    if not root.is_dir():
        return {
            "name": "run-artifacts",
            "ok": True,
            "size_bytes": 0,
            "message": "no local run artifacts found",
        }

    total = _dir_size_bytes(root)
    ok = total < RUN_ARTIFACTS_WARN_BYTES
    size_mb = total / (1024 * 1024)
    return {
        "name": "run-artifacts",
        "ok": ok,
        "size_bytes": total,
        "message": (
            f"{size_mb:.0f} MB of run artifacts under {root}"
            + ("" if ok else " - old runs are piling up")
        ),
        "fix": "delete old run directories, or use --cleanup on one-shot analyses",
    }


def find_repo_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "packages" / "watch-video" / "skills" / "watch-video" / "SKILL.md").exists() and (
            candidate / ".gitignore"
        ).exists():
            return candidate
    return None


def is_gitignored(repo_root: Path, path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "check-ignore", str(path.relative_to(repo_root))],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, ValueError):
        return None
    return result.returncode == 0


def check_env_local(repo_root: Path | None = None) -> dict[str, object]:
    repo = repo_root or find_repo_root()
    if repo is None:
        return {
            "name": ENV_LOCAL,
            "ok": True,
            "exists": False,
            "gitignored": None,
            "message": f"repo root not detected; skipped {ENV_LOCAL} check",
        }
    path = repo / ENV_LOCAL
    exists = path.exists()
    ignored = is_gitignored(repo, path)
    ok = not exists or ignored is True
    return {
        "name": ENV_LOCAL,
        "ok": ok,
        "exists": exists,
        "gitignored": ignored,
        "message": "ok" if ok else f"{ENV_LOCAL} exists but is not gitignored",
        "fix": f"add {ENV_LOCAL} to .gitignore",
    }


def collect_status(
    engine: str = "local", source: str | None = None, from_run: str | None = None,
    transcriber: str | None = None, analyzer: str = "none",
) -> dict[str, object]:
    validate_local_options(engine, transcriber, analyzer)
    if analyzer == "local" and transcriber is None:
        transcriber = "local"
    binaries = required_binaries(engine, source, from_run)
    source_kind = (
        "unspecified" if source is None else
        "YouTube URL" if is_url(source) and is_youtube_url(source) else
        "other URL" if is_url(source) else "local file"
    )
    checks = [
        check_platform(),
        check_python_version(),
        *(check_binary(name) for name in binaries),
        check_whisper_key("groq"),
        check_whisper_key("openai"),
        check_gemini_key(),
        *check_local_runtime(transcriber, analyzer),
        check_config_file(),
        check_run_artifacts(),
        check_env_local(),
    ]
    required_ok = all(
        bool(check["ok"])
        for check in checks
        if check["name"] not in ADVISORY_CHECKS
    )
    return {
        "ok": required_ok,
        "engine": engine,
        "transcriber": transcriber,
        "analyzer": analyzer,
        "scope": (
            "local: cached run" if from_run is not None else
            "full local toolkit (no source supplied)" if source is None else
            f"{engine}: {source_kind}"
        ),
        "required_binaries": binaries,
        "checks": checks,
        "install_hints": install_hints(binaries),
    }


def human_report(status: dict[str, object]) -> str:
    checks = status.get("checks") or []
    lines = ["Watch Video Doctor", ""]
    if status.get("scope"):
        lines.extend([f"Checking: {status['scope']}", ""])
    for check in checks:
        marker = "ok" if check.get("ok") else "warn"
        lines.append(f"- {marker}: {check['name']} - {check.get('message', '')}")
        if not check.get("ok") and check.get("fix"):
            lines.append(f"  fix: {check['fix']}")
    hints = status.get("install_hints", {}).get(current_platform(), [])
    if hints:
        lines.extend(["", "Install hints:"])
        lines.extend(f"- {hint}" for hint in hints)
    elif status.get("required_binaries") == []:
        lines.extend(["", "No local media binaries are required for this flow."])
    return "\n".join(lines) + "\n"


def check_mode_error(status: dict[str, object]) -> str | None:
    for check in status.get("checks") or []:
        if check["name"] in ADVISORY_CHECKS:
            continue
        if not check.get("ok"):
            fix = f" fix: {check['fix']}" if check.get("fix") else ""
            return f"{check['name']} check failed: {check.get('message', '')}.{fix}"
    return None


def _brew_packages(missing: list[str]) -> list[str]:
    packages: list[str] = []
    for name in missing:
        package = "ffmpeg" if name in {"ffmpeg", "ffprobe"} else name
        if package not in packages:
            packages.append(package)
    return packages


def install_missing(
    engine: str = "local", source: str | None = None, from_run: str | None = None,
) -> int:
    """Opt-in installer: brew on macOS, exact Linux commands. Never sudo."""
    binaries = required_binaries(engine, source, from_run)
    if not binaries:
        print("no local media binaries are required for this flow")
        return 0
    missing = [
        name for name in binaries
        if shutil.which(name) is None
    ]
    if not missing:
        print("all required binaries are already installed")
        return 0

    if current_platform() == "macOS" and shutil.which("brew"):
        packages = _brew_packages(missing)
        print(f"[doctor] running: brew install {' '.join(packages)}", file=sys.stderr)
        result = subprocess.run(["brew", "install", *packages], check=False)
        still_missing = [name for name in missing if shutil.which(name) is None]
        if result.returncode != 0 or still_missing:
            print(
                f"error: still missing after install: {', '.join(still_missing) or 'unknown'}",
                file=sys.stderr,
            )
            return 2
        print(f"installed via brew: {', '.join(packages)}")
        return 0

    print(f"missing: {', '.join(missing)}. Install manually (this script never uses sudo):")
    for hint in platform_hints(missing):
        print(f"  {hint}")
    return 2


def store_key(provider: str) -> int:
    """Read a key from stdin and store it privately; never echo it back."""
    key = sys.stdin.readline().strip()
    if not key:
        print("error: no key received on stdin", file=sys.stderr)
        print(f"fix: printf '%s\\n' \"$KEY\" | python3 scripts/doctor.py --set-key {provider}", file=sys.stderr)
        return 2
    name = KEY_NAMES[provider]
    try:
        path = set_stored_key(name, key)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    shape = key_shape_status(key, prefix="gsk_" if provider == "groq" else "sk-")
    verdict = "ok" if shape["ok"] else "unexpected (stored anyway)"
    print(f"stored {name} in {path} (mode 600); key shape: {verdict}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Watch Video preflight checks or store a Whisper API key."
    )
    parser.add_argument(
        "source", nargs="?",
        help="Video URL or local path; omit both source and --from-run to check the full local toolkit",
    )
    parser.add_argument(
        "--engine", choices=["local", "gemini"], default="local",
        help="Engine used with the source (default: local); no network requests or uploads are made",
    )
    parser.add_argument(
        "--from-run", metavar="RUN_DIR",
        help="Check dependencies for reusing a local run; does not inspect or validate the cache",
    )
    parser.add_argument(
        "--transcriber", choices=["none", "local", "groq", "openai"],
        help="Match the selected local-engine transcription route; checks configuration only",
    )
    parser.add_argument(
        "--analyzer", choices=["none", "local"], default="none",
        help="Match the selected local-engine model analysis route (default: none)",
    )
    parser.add_argument("--check", action="store_true", help="Silent success; concise error on failure")
    parser.add_argument("--json", action="store_true", help="Print structured status JSON")
    parser.add_argument(
        "--set-key",
        choices=sorted(KEY_NAMES),
        help="Read an API key from stdin and store it in the watch-video config file",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install this flow's missing binaries (brew on macOS; prints Linux commands; never sudo)",
    )
    args = parser.parse_args()

    if args.set_key:
        return store_key(args.set_key)
    try:
        validate_local_options(args.engine, args.transcriber, args.analyzer)
        required_binaries(args.engine, args.source, args.from_run)
    except ValueError as exc:
        parser.error(str(exc))
    if args.install:
        return install_missing(args.engine, args.source, args.from_run)

    status = collect_status(
        args.engine, args.source, args.from_run, args.transcriber, args.analyzer,
    )
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0 if status["ok"] else 1
    if args.check:
        error = check_mode_error(status)
        if error:
            print(error, file=sys.stderr)
            return 1
        return 0
    print(human_report(status), end="")
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
