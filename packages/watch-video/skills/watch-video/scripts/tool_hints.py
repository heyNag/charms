"""How to install the tools watch-video runs, by platform.

Doctor lists these commands, and an error about a missing tool names the one
for this computer, so nobody on Linux is told to use Homebrew.
"""

from __future__ import annotations

import platform


UNSUPPORTED = "watch-video supports macOS and Linux only"


def current_platform(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Linux":
        return "Linux"
    return "Unsupported"


def brew_packages(binaries: list[str]) -> list[str]:
    """The Homebrew formulas for these binaries; ffprobe comes with ffmpeg."""
    packages: list[str] = []
    for name in binaries:
        package = "ffmpeg" if name in {"ffmpeg", "ffprobe"} else name
        if package not in packages:
            packages.append(package)
    return packages


def install_hints(binaries: list[str]) -> dict[str, list[str]]:
    """The install commands for these binaries on each supported platform."""
    packages = brew_packages(binaries)
    return {
        "macOS": [f"brew install {' '.join(packages)}"] if packages else [],
        "Linux": (
            (["sudo apt install ffmpeg"] if "ffmpeg" in packages else [])
            # The extras bring what YouTube needs: the challenge solver
            # scripts, and a Deno that yt-dlp finds inside its own environment.
            + (['pipx install "yt-dlp[default,deno]"'] if "yt-dlp" in packages else [])
        ),
    }


def platform_hints(binaries: list[str], system: str | None = None) -> list[str]:
    """The install commands for these binaries on this computer."""
    return install_hints(binaries).get(current_platform(system), [UNSUPPORTED])


def missing_tool(name: str, system: str | None = None) -> str:
    """The error for a tool that is not installed, with this computer's fix."""
    hints = platform_hints([name], system) or [f"install {name}"]
    return f"{name} is not installed. fix: {'; '.join(hints)}"
