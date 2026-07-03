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


MIN_PYTHON = (3, 11)
ENV_LOCAL = ".env" + ".local"
# Key checks are advisory: watch-video still works caption/frames-only.
ADVISORY_CHECKS = {"GROQ_API_KEY", "OPENAI_API_KEY", "whisper-config", "run-artifacts"}
RUN_ARTIFACTS_WARN_BYTES = 500 * 1024 * 1024


def install_hints() -> dict[str, list[str]]:
    return {
        "macOS": ["brew install yt-dlp ffmpeg jq"],
        "Linux": ["sudo apt install ffmpeg", "pipx install yt-dlp"],
        "Windows": ["winget install Gyan.FFmpeg", "winget install yt-dlp.yt-dlp"],
    }


def current_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    return "Linux"


def platform_hints() -> list[str]:
    hints = install_hints()
    return hints.get(current_platform(), hints["Linux"])


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
        "fix": "; ".join(platform_hints()),
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


def check_run_artifacts() -> dict[str, object]:
    """Advisory disk check: downloaded media accumulates under run dirs."""
    roots: list[Path] = []
    cwd_runs = Path.cwd() / ".watch-video" / "runs"
    if cwd_runs.is_dir():
        roots.append(cwd_runs)
    repo = find_repo_root()
    if repo is not None:
        repo_runs = repo / ".watch-video" / "runs"
        if repo_runs.is_dir() and repo_runs not in roots:
            roots.append(repo_runs)

    if not roots:
        return {
            "name": "run-artifacts",
            "ok": True,
            "size_bytes": 0,
            "message": "no local run artifacts found",
        }

    total = sum(_dir_size_bytes(root) for root in roots)
    ok = total < RUN_ARTIFACTS_WARN_BYTES
    size_mb = total / (1024 * 1024)
    return {
        "name": "run-artifacts",
        "ok": ok,
        "size_bytes": total,
        "message": (
            f"{size_mb:.0f} MB of run artifacts under .watch-video/runs"
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


def collect_status() -> dict[str, object]:
    checks = [
        check_python_version(),
        check_binary("yt-dlp"),
        check_binary("ffmpeg"),
        check_binary("ffprobe"),
        check_whisper_key("groq"),
        check_whisper_key("openai"),
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
        "checks": checks,
        "install_hints": install_hints(),
    }


def human_report(status: dict[str, object]) -> str:
    checks = status.get("checks") or []
    lines = ["Watch Video Doctor", ""]
    for check in checks:
        marker = "ok" if check.get("ok") else "warn"
        lines.append(f"- {marker}: {check['name']} - {check.get('message', '')}")
        if not check.get("ok") and check.get("fix"):
            lines.append(f"  fix: {check['fix']}")
    lines.extend(["", "Install hints:"])
    for hint in platform_hints():
        lines.append(f"- {hint}")
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


def install_missing() -> int:
    """Opt-in installer: brew on macOS, exact commands elsewhere. Never sudo."""
    missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe") if shutil.which(name) is None]
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
    for hint in platform_hints():
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
        help="Install missing binaries (brew on macOS; prints commands elsewhere; never sudo)",
    )
    args = parser.parse_args()

    if args.set_key:
        return store_key(args.set_key)
    if args.install:
        return install_missing()

    status = collect_status()
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
