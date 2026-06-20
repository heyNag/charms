#!/usr/bin/env python3
# BEGIN GENERATED FROM SOURCE: packages/watch-video/scripts/doctor.py
# Do not edit directly; edit the source path and run make build-packages.
# END GENERATED FROM SOURCE

"""Watch Video preflight checks."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 11)
ENV_LOCAL = ".env" + ".local"


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


def key_shape_status(value: str | None) -> dict[str, object]:
    key = (value or "").strip()
    exists = bool(key)
    starts_with_gsk = key.startswith("gsk_") if exists else False
    plausible_length = len(key) >= 20 if exists else False
    ok = exists and starts_with_gsk and plausible_length
    return {
        "exists": exists,
        "starts_with_gsk": starts_with_gsk,
        "plausible_length": plausible_length,
        "length": len(key) if exists else 0,
        "ok": ok,
    }


def check_groq_key(env: dict[str, str] | None = None) -> dict[str, object]:
    env = env if env is not None else os.environ
    shape = key_shape_status(env.get("GROQ_API_KEY"))
    if not shape["exists"]:
        message = "GROQ_API_KEY is not set; Groq fallback will be unavailable"
    elif not shape["starts_with_gsk"]:
        message = "GROQ_API_KEY is set but does not look like a Groq key"
    elif not shape["plausible_length"]:
        message = "GROQ_API_KEY is set but length looks too short"
    else:
        message = "ok"
    return {
        "name": "GROQ_API_KEY",
        "ok": bool(shape["ok"]),
        "message": message,
        "safe_shape": shape,
        "fix": f"export GROQ_API_KEY=... or add it to a gitignored {ENV_LOCAL}",
    }


def find_repo_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "packages" / "watch-video" / "SKILL.md").exists() and (
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
        check_groq_key(),
        check_env_local(),
    ]
    required_ok = all(
        bool(check["ok"])
        for check in checks
        if check["name"] in {"python", "yt-dlp", "ffmpeg", "ffprobe", ENV_LOCAL}
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
        if check["name"] == "GROQ_API_KEY":
            continue
        if not check.get("ok"):
            fix = f" fix: {check['fix']}" if check.get("fix") else ""
            return f"{check['name']} check failed: {check.get('message', '')}.{fix}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Watch Video preflight checks.")
    parser.add_argument("--check", action="store_true", help="Silent success; concise error on failure")
    parser.add_argument("--json", action="store_true", help="Print structured status JSON")
    args = parser.parse_args()

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
