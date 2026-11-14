#!/usr/bin/env python3
"""Watch Video preflight checks and one-time Whisper key storage."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Stops here with one clear line when this Python is older than the floor.
import python_floor  # noqa: E402
import plugin_version  # noqa: E402
import prune_runs  # noqa: E402
import tool_hints  # noqa: E402
from tool_hints import brew_packages as _brew_packages, current_platform  # noqa: E402
from groq_transcribe import (  # noqa: E402
    KEY_NAMES,
    config_env_path,
    read_stored_key,
    set_stored_key,
)
from gemini import is_youtube_url  # noqa: E402
from watch import (  # noqa: E402
    JS_RUNTIME_ENV,
    OPT_IN_JS_RUNTIMES,
    default_js_runtime,
    default_run_root,
    is_url,
    js_runtime_args,
)


ENV_LOCAL = ".env" + ".local"
# Key checks are advisory: watch-video still works caption/frames-only.
ADVISORY_CHECKS = {
    "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "whisper-config", "run-artifacts",
    "run-privacy", "WATCH_VIDEO_LOCAL_API_KEY", "local-models", "js-runtime",
}
RUN_ARTIFACTS_WARN_BYTES = 500 * 1024 * 1024
# Limits for doctor's own helper commands, in seconds.
COMMAND_TIMEOUT = 10
YT_DLP_REPORT_TIMEOUT = 20
INSTALL_TIMEOUT = 1800
LOCAL_BINARIES = ("yt-dlp", "ffmpeg", "ffprobe")
# The yt-dlp extractor for these hosts runs the site's player JavaScript.
YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
# The names yt-dlp uses for the runtimes it leaves off, and their programs.
JS_RUNTIME_PROGRAMS = {"node": "node", "quickjs": "qjs", "bun": "bun"}
DENO_INSTALL_PAGE = "https://docs.deno.com/runtime/getting_started/installation/"


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


def needs_js_runtime(
    engine: str = "local", source: str | None = None, from_run: str | None = None,
) -> bool:
    """True when this flow has yt-dlp read YouTube, or names no source at all."""
    if "yt-dlp" not in required_binaries(engine, source, from_run):
        return False
    if source is None:
        return True
    try:
        host = (urlsplit(source).hostname or "").lower()
    except ValueError:
        return False
    return any(host == name or host.endswith(f".{name}") for name in YOUTUBE_HOSTS)


def install_hints(binaries: list[str] | None = None) -> dict[str, list[str]]:
    return tool_hints.install_hints(list(LOCAL_BINARIES) if binaries is None else binaries)


def platform_hints(binaries: list[str] | None = None) -> list[str]:
    hints = install_hints(binaries)
    return hints.get(current_platform(), [tool_hints.UNSUPPORTED])


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
    version = tuple((version_info or sys.version_info)[:3])
    floor = python_floor.version_text()
    ok = python_floor.problem(version) is None
    return {
        "name": "python",
        "ok": ok,
        "version": python_floor.version_text(version),
        "message": "ok" if ok else f"Python {floor}+ required",
        "fix": f"Use Python {floor} or newer.",
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


def yt_dlp_self_report(js_runtime: str | None = None) -> dict[str, str] | None:
    """Ask the installed yt-dlp what it can run YouTube's JavaScript with.

    No URL is given, so yt-dlp prints its debug header and stops without
    making a request. None means it could not be asked.
    """
    cmd = ["yt-dlp", "--ignore-config", "--verbose", *js_runtime_args(js_runtime)]
    try:
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=YT_DLP_REPORT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    labels = {"runtimes": "[debug] JS runtimes:", "libraries": "[debug] Optional libraries:"}
    report: dict[str, str] = {}
    for line in f"{result.stdout}\n{result.stderr}".splitlines():
        for key, label in labels.items():
            if line.startswith(label):
                report[key] = line[len(label):].strip()
    return report


def _deno_fix() -> str:
    if current_platform() == "macOS":
        return "brew install deno"
    return f"pipx inject yt-dlp deno (when yt-dlp came from pipx), or install Deno: {DENO_INSTALL_PAGE}"


def check_js_runtime(js_runtime: str | None = None) -> dict[str, object]:
    """Advisory: can yt-dlp run YouTube's player JavaScript?

    yt-dlp needs an external JavaScript runtime and its solver scripts for
    full YouTube support, and returns fewer formats without them. Only yt-dlp
    knows what it will accept: it finds a Deno inside its own environment,
    rejects old versions, and enables nothing but Deno unless told to. So the
    answer comes from yt-dlp, and `problem` says which part is missing.
    """
    check: dict[str, object] = {"name": "js-runtime", "ok": True, "problem": None}
    if shutil.which("yt-dlp") is None:
        check["message"] = "not checked until yt-dlp is installed"
        return check
    report = yt_dlp_self_report(js_runtime)
    listed = None if report is None else report.get("runtimes")
    if listed is None:
        check["message"] = "not checked: this yt-dlp did not report its JavaScript runtimes"
        return check

    consequence = "YouTube formats may be missing or downloads may fail"
    entries = [entry.strip() for entry in listed.split(",") if entry.strip()]
    # "none", "none (disabled)", "node-18.0.0 (unsupported)", "foo (unknown)".
    usable = [entry for entry in entries if not entry.startswith("none") and "(" not in entry]
    if usable:
        if "yt_dlp_ejs" in (report.get("libraries") or ""):
            check["message"] = f"{usable[0]} (reported by yt-dlp)"
            return check
        check.update(
            ok=False,
            problem="scripts",
            message=(
                f"yt-dlp can use {usable[0]} but is installed without its challenge solver "
                f"scripts (yt-dlp-ejs), so {consequence}"
            ),
            fix=(
                'install yt-dlp with its default extras (pipx install --force "yt-dlp[default,deno]"), '
                "or use the Homebrew formula or an official yt-dlp build, which include them"
            ),
        )
        return check

    rejected = [entry for entry in entries if "(" in entry and not entry.startswith("none")]
    idle = [
        name for name, program in JS_RUNTIME_PROGRAMS.items()
        if name != js_runtime and shutil.which(program)
    ]
    if js_runtime:
        found = f"; yt-dlp reported {', '.join(rejected)}" if rejected else ""
        message = f"yt-dlp could not use the selected runtime {js_runtime}{found}, so {consequence}"
    elif rejected:
        message = f"yt-dlp cannot use {', '.join(rejected)}, so {consequence}"
    elif idle:
        message = (
            f"yt-dlp has no JavaScript runtime it may use: it enables only Deno by itself, and "
            f"leaves {', '.join(idle)} off for security reasons. {consequence[0].upper()}{consequence[1:]}"
        )
    else:
        message = f"yt-dlp found no JavaScript runtime, so {consequence}"
    fix = _deno_fix()
    if idle:
        fix += (
            f"; or, when the user agrees, let yt-dlp use one it found: --js-runtime {idle[0]} "
            f"(or {JS_RUNTIME_ENV}={idle[0]})"
        )
    check.update(ok=False, problem="runtime", message=message, fix=fix)
    return check


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
    from local_config import LocalConfigError, get_setting, resolve_api_key

    environment = env if env is not None else os.environ
    config_errors = []
    try:
        endpoint = validate_base_url(
            get_setting("WATCH_VIDEO_LOCAL_BASE_URL", env=environment) or "http://127.0.0.1:8147/v1"
        )
        endpoint_check = {
            "name": "local-endpoint", "ok": True,
            "message": f"{endpoint} (configuration only; server access not tested)",
        }
    except LocalConfigError as exc:
        endpoint_check = {"name": "local-endpoint", "ok": False, "message": str(exc),
                          "fix": "Check local.env syntax and private permissions."}
    except ValueError:
        # An invalid URL may contain credentials; never include its value.
        endpoint_check = {
            "name": "local-endpoint", "ok": False,
            "message": "local inference requires an HTTP(S) loopback /v1 endpoint",
            "fix": "Set WATCH_VIDEO_LOCAL_BASE_URL to the local server, for example http://127.0.0.1:8147/v1.",
        }
    try:
        key_present = bool(resolve_api_key(env=environment))
    except LocalConfigError as exc:
        key_present = False
        config_errors.append({"name": "local-config", "ok": False, "message": str(exc)})
    key_source = "environment" if "WATCH_VIDEO_LOCAL_API_KEY" in environment else "local.env"
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
                f"present in {key_source} (not validated)" if key_present else
                "not set; required only if the local server enables authentication"
            ),
            "fix": "Enter WATCH_VIDEO_LOCAL_API_KEY in the private local.env file, or supply it through your chosen environment/secret manager when authentication is enabled.",
        },
        {
            "name": "local-models", "ok": True,
            "message": f"Requires a loaded or loadable {' and '.join(roles)}; model availability not tested",
        },
    ] + config_errors


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
        "fix": (
            "list old runs with scripts/doctor.py --prune and add --delete to remove them, "
            "or use --cleanup on one-shot analyses"
        ),
    }


def check_run_privacy(run_root: Path | None = None) -> dict[str, object]:
    """Advisory: run folders made by older versions can be open to other accounts.

    New run folders are created for the current user only. This looks at the
    run root and the folders directly inside it, and never changes a mode.
    """
    root = (run_root or default_run_root()).expanduser()
    check: dict[str, object] = {"name": "run-privacy", "ok": True, "exposed": 0}
    if os.name != "posix" or not root.is_dir():
        check["message"] = "no local run artifacts found"
        return check
    try:
        if root.stat().st_mode & 0o077 == 0:
            check["message"] = "run folders are private to this account"
            return check
        exposed = sum(
            1 for entry in root.iterdir()
            if entry.is_dir() and not entry.is_symlink() and entry.stat().st_mode & 0o077
        )
    except OSError:
        check["message"] = f"could not inspect {root}"
        return check
    if not exposed:
        check["message"] = "run folders are private to this account"
        return check
    check.update(
        ok=False,
        exposed=exposed,
        message=f"{exposed} run folder(s) under {root} can be opened by other accounts on this computer",
        fix=f"chmod -R go-rwx {shlex.quote(str(root))}",
    )
    return check


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
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return result.returncode == 0


def check_env_local(repo_root: Path | None = None) -> dict[str, object]:
    """Development check: a .env.local in a Charms checkout must be gitignored."""
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
    transcriber: str | None = None, analyzer: str = "none", js_runtime: str | None = None,
) -> dict[str, object]:
    validate_local_options(engine, transcriber, analyzer)
    if analyzer == "local" and transcriber is None:
        transcriber = "local"
    binaries = required_binaries(engine, source, from_run)
    repo_root = find_repo_root()
    source_kind = (
        "unspecified" if source is None else
        "YouTube URL" if is_url(source) and is_youtube_url(source) else
        "other URL" if is_url(source) else "local file"
    )
    checks = [
        check_platform(),
        check_python_version(),
        *(check_binary(name) for name in binaries),
        *([check_js_runtime(js_runtime)] if needs_js_runtime(engine, source, from_run) else []),
        check_whisper_key("groq"),
        check_whisper_key("openai"),
        check_gemini_key(),
        *check_local_runtime(transcriber, analyzer),
        check_config_file(),
        check_run_artifacts(),
        check_run_privacy(),
        # Only a Charms checkout has a .env.local to check. An installed
        # plugin is not in one, and the check would only say it was skipped.
        *([check_env_local(repo_root)] if repo_root is not None else []),
    ]
    required_ok = all(
        bool(check["ok"])
        for check in checks
        if check["name"] not in ADVISORY_CHECKS
    )
    return {
        "ok": required_ok,
        "plugin_version": plugin_version.VERSION,
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
    lines = [f"Watch Video Doctor ({plugin_version.VERSION_LINE})", ""]
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


def _js_runtime_gap(
    engine: str, source: str | None, from_run: str | None, js_runtime: str | None,
) -> dict[str, object] | None:
    """The failed js-runtime check for this flow, or None when there is nothing to fix."""
    if shutil.which("yt-dlp") is None or not needs_js_runtime(engine, source, from_run):
        return None
    check = check_js_runtime(js_runtime)
    return None if check["ok"] else check


def install_missing(
    engine: str = "local", source: str | None = None, from_run: str | None = None,
    js_runtime: str | None = None,
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
    # A YouTube flow also needs a JavaScript runtime that yt-dlp can use.
    runtime = _js_runtime_gap(engine, source, from_run, js_runtime)
    if not missing and runtime is None:
        print("all required binaries are already installed")
        return 0

    packages: list[str] = []
    if current_platform() == "macOS" and shutil.which("brew"):
        packages = _brew_packages(missing)
        # Homebrew's own yt-dlp brings Deno; another yt-dlp needs it added.
        if runtime is not None and runtime["problem"] == "runtime":
            packages.append("deno")
    if packages:
        print(f"[doctor] running: brew install {' '.join(packages)}", file=sys.stderr)
        try:
            result = subprocess.run(
                ["brew", "install", *packages], check=False, timeout=INSTALL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            print(
                f"error: brew install did not finish within {INSTALL_TIMEOUT // 60} minutes "
                "and was stopped; run it yourself to see what it is waiting for",
                file=sys.stderr,
            )
            return 2
        still_missing = [name for name in missing if shutil.which(name) is None]
        if result.returncode != 0 or still_missing:
            print(
                f"error: still missing after install: {', '.join(still_missing) or 'unknown'}",
                file=sys.stderr,
            )
            return 2
        print(f"installed via brew: {', '.join(packages)}")
        missing = []
        # Ask the yt-dlp that is installed now.
        runtime = _js_runtime_gap(engine, source, from_run, js_runtime)

    if missing:
        print(f"missing: {', '.join(missing)}. Install manually (this script never uses sudo):")
        for hint in platform_hints(missing):
            print(f"  {hint}")
    if runtime is not None:
        print(f"{runtime['message']}.")
        print(f"  fix: {runtime['fix']}")
    return 2 if missing or runtime is not None else 0


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


def prune_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """List old run folders, and delete them only when --delete is given."""
    other_modes = [
        label for label, given in (
            ("a source", args.source), ("--from-run", args.from_run), ("--install", args.install),
            ("--set-key", args.set_key), ("--check", args.check),
        ) if given
    ]
    if other_modes:
        parser.error(f"--prune cannot be combined with {', '.join(other_modes)}")
    try:
        older_than = prune_runs.parse_age(args.older_than or prune_runs.DEFAULT_AGE)
    except ValueError as exc:
        parser.error(str(exc))
    root = Path(args.out_dir).expanduser().resolve() if args.out_dir else default_run_root()
    result = prune_runs.prune(root, older_than, delete=args.delete)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(prune_runs.report(result), end="")
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Watch Video preflight checks, store a Whisper API key, or prune old runs."
    )
    parser.add_argument("--version", action="version", version=plugin_version.VERSION_LINE)
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
    parser.add_argument(
        "--js-runtime", choices=OPT_IN_JS_RUNTIMES,
        help=(
            "Match watch.py's --js-runtime (default: $WATCH_VIDEO_JS_RUNTIME); checks whether "
            "yt-dlp can use that runtime for YouTube"
        ),
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
    parser.add_argument(
        "--prune", action="store_true",
        help="List run folders unchanged for --older-than; deletes nothing without --delete",
    )
    parser.add_argument(
        "--older-than", metavar="AGE",
        help=f"With --prune: 12h, 7d or 2w (default: {prune_runs.DEFAULT_AGE}; at least 1h)",
    )
    parser.add_argument(
        "--delete", action="store_true", help="With --prune, delete the listed run folders",
    )
    parser.add_argument(
        "--out-dir", metavar="DIR",
        help=(
            "With --prune, the run root to look in (default: $WATCH_VIDEO_RUNS_DIR, "
            "else the watch-video state directory)"
        ),
    )
    args = parser.parse_args()

    if args.prune:
        return prune_command(parser, args)
    prune_only = [
        flag for flag, given in (
            ("--older-than", args.older_than), ("--delete", args.delete), ("--out-dir", args.out_dir),
        ) if given
    ]
    if prune_only:
        parser.error(f"{', '.join(prune_only)} only applies with --prune")
    if args.set_key:
        return store_key(args.set_key)
    try:
        validate_local_options(args.engine, args.transcriber, args.analyzer)
        required_binaries(args.engine, args.source, args.from_run)
        js_runtime = args.js_runtime or default_js_runtime()
    except ValueError as exc:
        parser.error(str(exc))
    if args.install:
        return install_missing(args.engine, args.source, args.from_run, js_runtime)

    status = collect_status(
        args.engine, args.source, args.from_run, args.transcriber, args.analyzer, js_runtime,
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
