"""Read-only first-time checks for the native oMLX/Splash setup.

This module inspects a small set of local hardware facts and file/binary
locations. It does not open apps, inspect credential contents, contact a server,
or install anything. Runtime configuration and inference remain separate checks.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from local_api import DEFAULT_BASE_URL, validate_base_url
from local_config import config_path


MIN_PYTHON = (3, 11)
MIN_SPLASH_MACOS = (26, 4)
COMMAND_TIMEOUT = 3
OMLX_RELEASES = "https://github.com/jundot/omlx/releases"
SPLASH_M1_RELEASES = "https://github.com/paperniuk/splash/releases"
SPLASH_DOCUMENTATION = "https://github.com/incoai/splash"


def _sysctl(name):
    """Query one fixed non-identifying hardware fact, with bounded execution."""
    if name not in {"machdep.cpu.brand_string", "hw.memsize", "sysctl.proc_translated"}:
        raise ValueError("Unsupported hardware query.")
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True,
            check=False, timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0][:160]


def detect_hardware():
    system = platform.system()
    architecture = platform.machine()
    hardware = {
        "system": system, "architecture": architecture, "macos_version": None,
        "chip": None, "apple_m_generation": None, "memory_bytes": None,
        "memory_gib": None, "rosetta": False, "support": "unsupported",
        "reason": "The native oMLX/Splash setup requires an Apple Silicon Mac.",
        "preferred_splash": None,
    }
    if system != "Darwin":
        return hardware
    hardware["macos_version"] = platform.mac_ver()[0] or None
    brand = _sysctl("machdep.cpu.brand_string")
    hardware["chip"] = brand
    generation = re.match(r"^Apple M([1-9][0-9]*)(?:\s|$)", brand or "")
    memory = _sysctl("hw.memsize")
    if memory and memory.isdecimal() and int(memory) > 0:
        hardware["memory_bytes"] = int(memory)
        hardware["memory_gib"] = round(int(memory) / 1024**3, 2)
    translated = _sysctl("sysctl.proc_translated")
    hardware["rosetta"] = translated == "1" or bool(
        generation and architecture.lower() in {"x86_64", "amd64"}
    )
    if generation:
        number = int(generation.group(1))
        hardware["apple_m_generation"] = number
        hardware["preferred_splash"] = "splash-m1" if number <= 2 else "splash"
    elif brand and ("intel" in brand.lower() or "amd" in brand.lower()):
        return hardware
    else:
        hardware["support"] = "unknown"
        hardware["reason"] = (
            "Could not identify the Apple chip generation; check About This Mac "
            "before choosing a Splash build."
        )
        return hardware
    version = re.match(r"^(\d+)\.(\d+)(?:\.|$)", hardware["macos_version"] or "")
    if not version:
        hardware["support"] = "unknown"
        hardware["reason"] = "Could not determine macOS compatibility; check the Splash requirements."
    elif tuple(map(int, version.groups())) < MIN_SPLASH_MACOS:
        hardware["reason"] = "The documented Splash builds require macOS 26.4 or newer."
    else:
        hardware["support"] = "supported"
        hardware["reason"] = "Hardware and macOS match the documented setup prerequisites."
    return hardware


def _find_launcher(name, home):
    found = shutil.which(name)
    if found:
        return str(Path(found).absolute())
    for directory in (Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / ".local/bin"):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _find_app(home):
    applications = (Path("/Applications/oMLX.app"), home / "Applications/oMLX.app")
    return next((str(path) for path in applications if path.is_dir()), None)


def _disk_space(model_dir):
    """Inspect the existing filesystem without creating a model directory."""
    for ancestor in (model_dir, *model_dir.parents):
        if ancestor.is_dir():
            try:
                return shutil.disk_usage(ancestor).free
            except OSError:
                return None
    return None


def preflight(*, base_url=None, model_dir=None):
    home = Path.home()
    # Preflight never resolves settings through a credential file. An explicit
    # value also keeps that boundary if the runtime validator later evolves.
    env_endpoint = os.environ.get("WATCH_VIDEO_LOCAL_BASE_URL")
    endpoint = validate_base_url(base_url or env_endpoint or DEFAULT_BASE_URL)
    endpoint_source = "argument" if base_url else "environment" if env_endpoint else "default"
    root = Path(model_dir or home / ".omlx/models").expanduser().resolve()
    hardware = detect_hardware()
    app = _find_app(home)
    shim = home / ".omlx/bin/omlx"
    cli = str(shim) if shim.is_file() and os.access(shim, os.X_OK) else shutil.which("omlx")
    preferred = hardware["preferred_splash"]
    launchers = {name: _find_launcher(name, home) for name in ("splash-m1", "splash")}
    binaries = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "yt-dlp", "brew", "op")}
    python_ok = sys.version_info[:2] >= MIN_PYTHON
    blockers = []
    next_steps = []
    warnings = []
    if hardware["support"] != "supported":
        blockers.append(hardware["reason"])
        next_steps.append({"id": "hardware", "instruction": hardware["reason"]})
    if not python_ok:
        blockers.append("Python 3.11 or newer is required.")
        next_steps.append({"id": "python", "instruction": "Install Python 3.11 or newer, then rerun preflight."})
    missing_tools = [name for name in ("ffmpeg", "ffprobe") if not binaries[name]]
    if missing_tools:
        blockers.append("Missing local video tools: " + ", ".join(missing_tools) + ".")
        next_steps.append({"id": "ffmpeg", "instruction": "Install FFmpeg, which includes ffprobe (brew install ffmpeg on macOS)."})
    if hardware["support"] == "supported":
        if not app:
            blockers.append("The native oMLX app was not found in /Applications or ~/Applications.")
            next_steps.append({"id": "omlx", "instruction": "Install the native oMLX DMG, move the app to Applications, and open it once.", "url": OMLX_RELEASES})
        elif not cli:
            warnings.append("The oMLX CLI shim was not found; open the app once or use its UI controls.")
        if not launchers[preferred]:
            blockers.append(f"The preferred Splash launcher ({preferred}) was not found.")
            next_steps.append({"id": "splash", "instruction": (
                "Install Splash-M1 using the release's install-m1.sh instructions, then select splash-m1 in oMLX Integrations."
                if preferred == "splash-m1" else
                "Install official Splash with brew install incoai/tap/splash, then select splash in oMLX Integrations."
            ), "url": SPLASH_M1_RELEASES if preferred == "splash-m1" else SPLASH_DOCUMENTATION})
        next_steps.extend([
            {"id": "connection", "instruction": "Inspect and reuse the user's server settings, or configure the suggested loopback endpoint and common model directory below. Run python3 scripts/setup_local.py --init-config to create a private template, then enter the matching server key in that file using an editor. Existing files are preserved; a secret manager is optional."},
            {"id": "server", "instruction": "Use the oMLX app or the host's server-management workflow to start the server if needed. Server state was not checked by this offline preflight."},
            {"id": "runtime_check", "instruction": "From the installed skill directory, run python3 scripts/setup_local.py --check with the configured credential environment. This verifies runtime configuration and model availability."},
            {"id": "models", "instruction": "If setup is requested and the runtime check reports missing models or settings, run python3 scripts/setup_local.py --configure --wait 600 with the same environment. oMLX owns model downloads; keep the vision model unloaded while changing its settings."},
            {"id": "smoke_test", "instruction": "Once runtime setup reports ready, run a short original-audio and frames test with matching TXT/SRT if available. Review local_analysis.json and its evidence before processing a full recording."},
        ])
    if hardware["rosetta"]:
        warnings.append("This process appears to run under Rosetta. Use native Apple Silicon tools for the local runtime.")
    if hardware["system"] == "Darwin" and hardware["memory_bytes"] is None:
        warnings.append("Installed memory could not be detected; check About This Mac before choosing model and memory settings.")
    free_bytes = _disk_space(root)
    env_file = config_path()
    env_file_present = env_file.is_file()
    if env_file_present and endpoint_source == "default":
        warnings.append("Existing local.env contents were not read; its endpoint may differ from the suggested default. The runtime check loads its saved connection settings.")
    return {
        "mode": "preflight",
        "status": ("unsupported" if hardware["support"] == "unsupported" else
                   "needs_setup" if blockers else "requires_runtime_check"),
        "hardware": hardware,
        "python": {"version": ".".join(str(part) for part in sys.version_info[:3]), "ok": python_ok},
        "binaries": binaries,
        "runtime": {"omlx_app": app, "omlx_cli": cli,
                    "preferred_splash": preferred, "splash_launchers": launchers,
                    "server_state": "not_checked", "models": "not_checked"},
        "connection": {"base_url": endpoint, "base_url_source": endpoint_source,
                       "model_directory": str(root),
                       "api_key_in_environment": bool(os.environ.get("WATCH_VIDEO_LOCAL_API_KEY", "")),
                       "local_env_file": str(env_file), "local_env_file_present": env_file_present,
                       "authentication": "not_checked", "config_contents": "not_read"},
        "storage": {"available_bytes": free_bytes,
                    "available_gib": round(free_bytes / 1024**3, 2) if free_bytes is not None else None},
        "blockers": blockers, "warnings": warnings, "next_steps": next_steps,
        "note": "Read-only preflight: no apps started, network calls, installs, model downloads, credential contents read, or settings changed. RAM, free space, and binary presence do not prove model fit, runtime compatibility, or inference quality. yt-dlp is only needed for URL downloads; secret-manager tools are optional.",
    }


def print_preflight(result):
    print(f"[watch-video] Local preflight: {result['status']}")
    hardware = result.get("hardware", {})
    if hardware:
        memory = hardware.get("memory_gib")
        memory_text = f"{memory:g} GiB" if memory is not None else "unknown"
        print(f"  Host: {hardware['system']}; {hardware.get('chip') or hardware['architecture']}; "
              f"RAM: {memory_text}")
        if hardware.get("macos_version"):
            print(f"  macOS: {hardware['macos_version']}")
        if hardware.get("preferred_splash"):
            print(f"  Splash build: {hardware['preferred_splash']}")
    for message in result.get("blockers", []):
        print(f"  Needs attention: {message}")
    for message in result.get("warnings", []):
        print(f"  Note: {message}")
    connection = result.get("connection", {})
    if connection:
        endpoint_label = "Suggested endpoint" if connection["base_url_source"] == "default" else "Client endpoint"
        print(f"  {endpoint_label}: {connection['base_url']}")
        print(f"  Expected model directory: {connection['model_directory']}")
        print(f"  Client config: {connection['local_env_file']} "
              f"({'present; contents not read' if connection['local_env_file_present'] else 'not created'})")
        print("  API key environment: " + ("present (not validated)" if connection["api_key_in_environment"] else "not present; no key contents inspected"))
    if result.get("next_steps"):
        print("  Next steps:")
        for number, step in enumerate(result["next_steps"], 1):
            print(f"    {number}. {step['instruction']}")
            if step.get("url"):
                print(f"       {step['url']}")
    print("  " + result.get("note", "No runtime or inference readiness has been established."))
