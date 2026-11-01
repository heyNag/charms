"""Private, literal local-runtime configuration; no shell or secret-manager calls."""

from __future__ import annotations

import os
import stat
from pathlib import Path


CONFIG_KEYS = frozenset({
    "WATCH_VIDEO_LOCAL_BASE_URL", "WATCH_VIDEO_LOCAL_ASR_MODEL",
    "WATCH_VIDEO_LOCAL_MODEL", "WATCH_VIDEO_LOCAL_API_KEY",
})
MAX_CONFIG_BYTES = 64 * 1024
TEMPLATE = """# Local watch-video settings. Edit this file yourself; keep it out of chat and Git.
# Use the same API key configured in oMLX. Leave empty only when server auth is off.
# Values are literal: shell commands and variable substitutions are never evaluated.
WATCH_VIDEO_LOCAL_BASE_URL=http://127.0.0.1:8147/v1
WATCH_VIDEO_LOCAL_ASR_MODEL=whisper-large-v3-asr-fp16
WATCH_VIDEO_LOCAL_MODEL=mlx-community--Qwen3.6-35B-A3B-4bit
WATCH_VIDEO_LOCAL_API_KEY=
"""


class LocalConfigError(ValueError):
    """A safe configuration error that never includes a supplied value."""


def config_path(*, env=None) -> Path:
    """Return the settings path without opening or creating it."""
    environment = os.environ if env is None else env
    base = environment.get("WATCH_VIDEO_CONFIG_DIR")
    return ((Path(base).expanduser() if base else Path.home() / ".config/watch-video")
            / "local.env")


def create_config_template() -> dict:
    """Create a private blank-key template; preserve existing regular files."""
    path = config_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise LocalConfigError("Local configuration must be a regular file, not a symlink.") from None
            return {"status": "exists", "path": str(path)}
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(TEMPLATE)
        return {"status": "created", "path": str(path)}
    except LocalConfigError:
        raise
    except OSError:
        raise LocalConfigError("Could not create the local configuration template; check its directory permissions.") from None


def read_config(*, env=None) -> dict[str, str]:
    """Read a bounded private regular file, parsing only known literal settings."""
    path = config_path(env=env)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return {}
    except OSError:
        raise LocalConfigError("Could not read local configuration; use a regular file with private permissions.") from None
    try:
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise LocalConfigError("Local configuration must be a regular file, not a symlink.")
            if info.st_mode & 0o077:
                raise LocalConfigError("Local configuration is accessible to other users; set its permissions to 600 before use.")
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except LocalConfigError:
        raise
    except OSError:
        raise LocalConfigError("Could not read local configuration; check its permissions.") from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise LocalConfigError("Local configuration exceeds the 64 KiB size limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise LocalConfigError("Local configuration must use UTF-8 text.") from None
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or name not in CONFIG_KEYS or name in values:
            raise LocalConfigError(f"Invalid or repeated local setting on line {number}; use the generated template.")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise LocalConfigError(f"Unclosed quoted local setting on line {number}.")
            value = value[1:-1]
        else:
            # A separated comment is allowed; embedded '#' remains literal.
            for index, char in enumerate(value):
                if char == "#" and index > 0 and value[index - 1] in " \t":
                    value = value[:index].rstrip()
                    break
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise LocalConfigError(f"Local setting on line {number} contains a control character.")
        values[name] = value
    return values


def get_setting(name: str, default: str | None = None, *, env=None) -> str | None:
    """Environment overrides the file, including an explicitly empty value."""
    if name not in CONFIG_KEYS:
        raise LocalConfigError("Unsupported local configuration setting.")
    environment = os.environ if env is None else env
    if name in environment:
        return environment[name]
    return read_config(env=environment).get(name, default)


def resolve_api_key(explicit: str | None = None, *, env=None) -> str:
    key = (explicit if explicit is not None else get_setting("WATCH_VIDEO_LOCAL_API_KEY", "", env=env)).strip()
    if key.startswith("op://"):
        raise LocalConfigError(
            "The local API key is an unresolved secret reference. Use your chosen secret "
            "manager to inject the key into the environment, or enter the actual key in local.env."
        )
    if any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise LocalConfigError("Local API key must be a single-line ASCII value.")
    return key
