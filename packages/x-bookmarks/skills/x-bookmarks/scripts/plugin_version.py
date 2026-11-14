"""The version of this plugin, read once from its plugin.json.

A release writes the version in one place, the manifest at the plugin root.
Everything that reports a version reads it from here: --version and the
User-Agent on requests. A copy of the skill without the rest of the plugin
has no manifest, and the version is then "unknown".
"""

from __future__ import annotations

import json
import re
from pathlib import Path


PLUGIN = "x-bookmarks"
UNKNOWN = "unknown"
# This file is <plugin root>/skills/<skill>/scripts/plugin_version.py.
MANIFEST = Path(__file__).resolve().parent.parent.parent.parent / "plugin.json"
MAX_MANIFEST_BYTES = 1024 * 1024
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def read_version(manifest: Path = MANIFEST) -> str:
    """The version in this plugin's manifest, or "unknown" when there is none."""
    try:
        if manifest.stat().st_size > MAX_MANIFEST_BYTES:
            return UNKNOWN
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNKNOWN
    # A plugin.json for something else is not this plugin's manifest.
    if not isinstance(data, dict) or data.get("name") != PLUGIN:
        return UNKNOWN
    version = data.get("version")
    return version if isinstance(version, str) and _VERSION.fullmatch(version) else UNKNOWN


VERSION = read_version()
# What --version prints.
VERSION_LINE = f"{PLUGIN} {VERSION}"
USER_AGENT = f"charms-{PLUGIN}/{VERSION}"
