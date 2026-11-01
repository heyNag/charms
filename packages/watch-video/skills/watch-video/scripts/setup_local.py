#!/usr/bin/env python3
"""Check or configure the watch-video models through a running native oMLX app.

No runtime installation, server lifecycle changes, credentials storage, or direct
Hugging Face downloads. Only --configure permits mutations. Downloads remain
owned by oMLX after this bounded command exits; rerun it to finish configuration.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import time
from pathlib import Path

from local_api import LocalAPIError, LocalClient


VISION_REPO = "mlx-community/Qwen3.6-35B-A3B-4bit"
ASR_REPO = "mlx-community/whisper-large-v3-asr-fp16"
DRAFT_REPO = "incoai/Qwen3.6-35B-A3B-DFlash2"
REPOSITORIES = (ASR_REPO, VISION_REPO, DRAFT_REPO)
VISION_ALIAS = "mlx-community--Qwen3.6-35B-A3B-4bit"
ACTIVE_DOWNLOADS = {"pending", "downloading"}


class AdminClient(LocalClient):
    """Reuse the loopback/credential/error transport for oMLX's fixed admin root."""

    def __init__(self, base_url=None, *, timeout=30):
        super().__init__(base_url=base_url, timeout=timeout)
        self.inference_url = self.base_url
        self.base_url = self.base_url.removesuffix("/v1") + "/admin/api"


def _rows(reply, key):
    rows = reply.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise LocalAPIError("oMLX returned an unsupported setup response; check app compatibility.")
    return rows


def _model_files_present(path):
    """Presence check only; model loading/inference still needs a smoke test."""
    if not (path / "config.json").is_file():
        return False
    try:
        index = path / "model.safetensors.index.json"
        if index.exists():
            names = set(json.loads(index.read_text()).get("weight_map", {}).values())
            if not names or any(not isinstance(name, str) for name in names):
                return False
            files = [path / name for name in names]
        else:
            files = list(path.glob("model*.safetensors"))
        return bool(files) and all(
            file.resolve().is_relative_to(path.resolve()) and file.is_file()
            and file.stat().st_size > 0 for file in files
        )
    except (OSError, ValueError, TypeError):
        return False


def _preconditions(settings, model_dir):
    blockers = []
    host = (settings.get("server") or {}).get("host")
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except (TypeError, ValueError):
        loopback = False
    if not loopback:
        blockers.append("Set oMLX's server host to 127.0.0.1 or ::1 in its app, then restart it.")
    model_settings = settings.get("model") or {}
    directories = model_settings.get("model_dirs") or [model_settings.get("model_dir")]
    primary = directories[0] if isinstance(directories, list) and directories else None
    if not isinstance(primary, str) or Path(primary).expanduser().resolve() != model_dir:
        blockers.append(f"Set oMLX's primary model directory to {model_dir} in its app before downloading.")
    splash = (settings.get("external_engines") or {}).get("splash") or {}
    if splash.get("available") is not True:
        blockers.append("Install the Splash build for this Mac and select it in oMLX Settings → Integrations.")
    return blockers


def _inventory(client, model_dir):
    models = _rows(client.request_json("models"), "models")
    tasks = _rows(client.request_json("hf/tasks"), "tasks")
    rows, entries = [], {}
    for repo in REPOSITORIES:
        destination = model_dir / repo
        matching = [model for model in models if isinstance(model.get("model_path"), str)
                    and Path(model["model_path"]).expanduser().resolve() == destination]
        entry = matching[0] if len(matching) == 1 else None
        related = [task for task in tasks if task.get("repo_id") == repo]
        active = next((task for task in related if task.get("status") in ACTIVE_DOWNLOADS), None)
        latest = max(related, key=lambda task: task.get("created_at", 0), default=None)
        complete = entry is not None and _model_files_present(destination)
        state = "downloading" if active else "present" if complete else "missing"
        if not active and not complete and latest and latest.get("status") in {"failed", "cancelled"}:
            state = latest["status"]
        rows.append({"repo_id": repo, "path": str(destination), "state": state})
        if complete and not active:
            entries[repo] = entry
    return rows, entries


def setup(*, configure=False, wait_seconds=0, model_dir=None, base_url=None,
          context_window=16384, ttl_seconds=300, client=None, poll_seconds=10):
    if not isinstance(wait_seconds, (int, float)) or isinstance(wait_seconds, bool) \
            or not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 3600:
        raise ValueError("Wait must be between 0 and 3600 seconds.")
    if not configure and wait_seconds:
        raise ValueError("--wait requires --configure.")
    if not 1024 <= context_window <= 32768 or not 60 <= ttl_seconds <= 3600:
        raise ValueError("Context must be 1024–32768 tokens and model idle TTL 60–3600 seconds.")
    root = Path(model_dir or Path.home() / ".omlx/models").expanduser().resolve()
    client = client or AdminClient(base_url)
    settings = client.request_json("global-settings")
    result = {
        "status": "needs_setup", "mode": "configure" if configure else "check",
        "model_directory": str(root), "blockers": _preconditions(settings, root),
        "actions": [], "models": [],
        "environment": {"WATCH_VIDEO_LOCAL_BASE_URL": client.inference_url,
                        "WATCH_VIDEO_LOCAL_MODEL": VISION_ALIAS,
                        "WATCH_VIDEO_LOCAL_ASR_MODEL": ASR_REPO.split("/")[-1]},
        "note": "Configuration checks do not load models or prove inference quality.",
    }
    if result["blockers"]:
        return result
    deadline = time.monotonic() + wait_seconds
    # Refresh discovery only in the explicitly mutating mode. oMLX also rescans
    # when its download completes, so status polling normally needs GETs only.
    if configure:
        client.request_json("reload", {})
    while True:
        rows, entries = _inventory(client, root)
        result["models"] = rows
        failed = [row for row in rows if row["state"] in {"failed", "cancelled"}]
        if failed:
            result["status"] = "error"
            result["blockers"] = [
                f"Download {row['state']} for {row['repo_id']}; inspect it in oMLX and explicitly retry there."
                for row in failed
            ]
            return result
        missing = [row for row in rows if row["state"] == "missing"]
        if configure:
            for row in missing:
                reply = client.request_json("hf/download", {"repo_id": row["repo_id"]})
                if reply.get("success") is not True:
                    raise LocalAPIError("oMLX did not confirm the model download; inspect its task list before retrying.")
                result["actions"].append({"download_queued": row["repo_id"]})
                row["state"] = "downloading"
        if len(entries) == len(REPOSITORIES):
            target, draft = entries[VISION_REPO], entries[DRAFT_REPO]
            desired = {"model_alias": VISION_ALIAS, "external_engine": "splash",
                       "max_context_window": context_window, "ttl_seconds": ttl_seconds,
                       "dflash_draft_model": draft["id"]}
            current = target.get("settings") or {}
            changes = {key: value for key, value in desired.items() if current.get(key) != value}
            result["model_settings_needed"] = changes
            if changes:
                if configure:
                    if target.get("loaded") or target.get("is_loading"):
                        result["blockers"] = ["Unload the Qwen model in oMLX before applying setup settings, then rerun."]
                        return result
                    engines = target.get("external_engines") or []
                    if not any(engine.get("id") == "splash" and engine.get("compatible") is True
                               for engine in engines if isinstance(engine, dict)):
                        result["blockers"] = ["oMLX does not report this model as Splash-compatible; inspect its model settings."]
                        return result
                    client.request_json(f"models/{target['id']}/settings", changes, method="PUT")
                    result["actions"].append({"model_settings_updated": target["id"]})
                    # Verify persisted settings; do not equate an HTTP response with success.
                    _, verified = _inventory(client, root)
                    actual = (verified.get(VISION_REPO) or {}).get("settings") or {}
                    if any(actual.get(key) != value for key, value in desired.items()):
                        raise LocalAPIError("oMLX model settings could not be verified; inspect the app before retrying.")
                    result["model_settings_needed"] = {}
                else:
                    return result
            result["status"] = "ready"
            return result
        result["status"] = "pending" if any(row["state"] == "downloading" for row in rows) else "needs_setup"
        remaining = deadline - time.monotonic()
        if not configure or remaining <= 0:
            return result
        time.sleep(min(poll_seconds, remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", "--dry-run", action="store_true", help="Read-only setup check (default)")
    modes.add_argument("--configure", action="store_true", help="Queue missing models and apply this skill's model settings")
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDS", help="Bounded wait for oMLX downloads; default 0, max 3600")
    parser.add_argument("--base-url", help="Loopback inference URL; defaults to WATCH_VIDEO_LOCAL_BASE_URL or port 8147")
    parser.add_argument("--model-dir", type=Path, help="Expected primary oMLX model directory; default ~/.omlx/models")
    parser.add_argument("--context-window", type=int, default=16384)
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = setup(configure=args.configure, wait_seconds=args.wait, model_dir=args.model_dir,
                       base_url=args.base_url, context_window=args.context_window, ttl_seconds=args.ttl_seconds)
    except (LocalAPIError, ValueError, OSError) as exc:
        # Transport/value errors are sanitized; filesystem errors can contain
        # arbitrary paths, so do not print raw OSError messages.
        message = str(exc) if isinstance(exc, (LocalAPIError, ValueError)) else "Could not inspect local model files."
        result = {"status": "error", "blockers": [message]}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[watch-video] Local setup: {result['status']}")
        for row in result.get("models", []):
            print(f"  {row['repo_id']}: {row['state']} ({row['path']})")
        for blocker in result.get("blockers", []):
            print(f"  {blocker}")
        if result["status"] == "pending":
            print("  oMLX owns the downloads. Rerun --configure after they finish, or use --wait SECONDS.")
        if result.get("model_settings_needed"):
            print("  Model settings need configuration; run --configure with the same options.")
        print("  This command does not start/stop the server or load inference models.")
    return 0 if result["status"] == "ready" else 1 if result["status"] == "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
