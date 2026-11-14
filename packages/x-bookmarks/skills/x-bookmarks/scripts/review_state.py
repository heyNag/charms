"""The saved review cutoff: what "new since last time" means for both backends.

X lists bookmarks newest first by the time they were bookmarked, but neither
backend is told that time; a post carries only the time it was written. The
cutoff is therefore kept as the IDs of the newest bookmarks already reviewed,
per scope (the whole list, or one folder), in a small private JSON file.

A bookmark's ID is the post's ID in both backends, so a review made through
Bird continues through the X API and the other way round.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, NamedTuple

import private_files

# Newest reviewed bookmark IDs kept per scope, so removing the last reviewed
# bookmark does not lose the review cutoff.
STATE_ANCHORS = 50
# X documents a bookmark folder ID as 1 to 19 digits. The ID goes into the
# request path, where a value such as "../x" would leave the folders endpoint.
FOLDER_ID = re.compile(r"[0-9]{1,19}")


def default_state_file() -> Path:
    """Where review state lives unless --state-file says otherwise."""
    return Path(os.environ.get("X_BOOKMARKS_STATE_FILE", "~/.local/state/x-bookmarks/state.json")).expanduser()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def created_at(item: dict[str, Any]) -> str | None:
    """A post's creation time: ISO-8601 UTC text, as the X API writes it."""
    value = item.get("created_at")
    return str(value) if value else None


class StateError(RuntimeError):
    """The review state file cannot be read or does not have the saved shape."""


def _is_id(value: Any) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def state_problem(data: Any) -> str | None:
    """Say what is wrong with loaded review state, or return None when it is usable."""
    if not isinstance(data, dict):
        return "the top level is not a JSON object"
    scopes = data.get("scopes", {})
    if not isinstance(scopes, dict):
        return '"scopes" is not a JSON object'
    for scope, entry in scopes.items():
        if not isinstance(entry, dict):
            return f'scope "{scope}" is not a JSON object'
        if "last_seen_id" in entry and not _is_id(entry["last_seen_id"]):
            return f'"last_seen_id" of scope "{scope}" is not a bookmark ID'
        anchors = entry.get("anchor_ids", [])
        if not isinstance(anchors, list) or not all(_is_id(item) for item in anchors):
            return f'"anchor_ids" of scope "{scope}" is not a list of bookmark IDs'
        if not isinstance(entry.get("last_seen_created_at", ""), str):
            return f'"last_seen_created_at" of scope "{scope}" is not a string'
    return None


def load_state(path: Path) -> dict[str, Any]:
    """Read the review state, or return {} when none has been saved yet.

    A file that cannot be read, is not JSON, or does not have the saved shape
    raises StateError. Reading it as empty would list every bookmark as new,
    and --update-state would then replace what is left of the file.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise StateError(f"cannot read the review state file {path}: {exc.strerror or exc}") from exc
    except (ValueError, RecursionError) as exc:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        raise StateError(f"the review state file {path} is not valid JSON: {exc}") from exc
    problem = state_problem(data)
    if problem:
        raise StateError(f"the review state file {path} is damaged: {problem}")
    return data


# What to tell the user when load_state raises.
STATE_FIX = (
    "fix: restore the file from a backup, or move it aside and rerun; "
    "the next --since-last run then lists every bookmark as new"
)


def save_state(path: Path, data: dict[str, Any]) -> None:
    """Save review state so that only this account can read it; see private_files."""
    private_files.write_private_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def state_scope(folder_id: str | None) -> str:
    return f"folder:{folder_id}" if folder_id else "all"


def state_entry(state: dict[str, Any], scope: str) -> dict[str, Any]:
    scopes = state.get("scopes")
    if isinstance(scopes, dict):
        entry = scopes.get(scope)
        if isinstance(entry, dict):
            return entry
    return {}


def state_anchor_ids(state: dict[str, Any], scope: str) -> list[str]:
    """Return the saved reviewed bookmark IDs for scope, newest first.

    State written before anchors existed holds only last_seen_id, which reads
    as a single anchor.
    """
    entry = state_entry(state, scope)
    saved = entry.get("anchor_ids")
    anchors = [str(item) for item in saved if item] if isinstance(saved, list) else []
    last_seen_id = entry.get("last_seen_id")
    if last_seen_id and str(last_seen_id) not in anchors:
        anchors.insert(0, str(last_seen_id))
    return anchors


def state_last_seen_created_at(state: dict[str, Any], scope: str) -> str | None:
    value = state_entry(state, scope).get("last_seen_created_at")
    return str(value) if value else None


def update_last_seen(
    state: dict[str, Any],
    scope: str,
    fetched_ids: list[str],
    newest_created_at: str | None = None,
) -> dict[str, Any]:
    """Record the newest fetched IDs, then older saved anchors, as the cutoff."""
    updated = dict(state)
    scopes = updated.get("scopes")
    scopes = dict(scopes) if isinstance(scopes, dict) else {}
    anchors = list(dict.fromkeys([*fetched_ids, *state_anchor_ids(state, scope)]))
    anchors = anchors[:STATE_ANCHORS]
    entry: dict[str, Any] = {
        "last_seen_id": anchors[0],
        "anchor_ids": anchors,
        "updated_at": utc_now(),
    }
    if newest_created_at:
        entry["last_seen_created_at"] = newest_created_at
    scopes[scope] = entry
    updated["scopes"] = scopes
    return updated


def cutoff_index(items: list[dict[str, Any]], anchors: list[str]) -> int | None:
    """Return where the reviewed bookmarks start in a full fetch, or None.

    Reviewed bookmarks sit below every newer one, in saved anchor order with
    gaps where some were removed. A reviewed post bookmarked again moves to the
    top, so the cutoff is the run of adjacent anchors that ends at the last
    fetched anchor, not the newest anchor found.
    """
    rank = {anchor: position for position, anchor in enumerate(anchors)}
    ids = [str(item.get("id")) for item in items]
    hits = [index for index, item_id in enumerate(ids) if item_id in rank]
    if not hits:
        return None
    start = hits[-1]
    while start > 0 and rank.get(ids[start - 1], len(anchors)) < rank[ids[start]]:
        start -= 1
    return start


def since_last(
    items: list[dict[str, Any]],
    state: dict[str, Any],
    scope: str,
    reached_end: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Return items bookmarked after the saved cutoff and how it was applied.

    Modes: "no_state" (nothing saved), "anchor" (stopped where the saved IDs
    still bookmarked begin), "created_at_fallback" (every saved ID is gone, so
    post creation time was compared; this can skip or repeat bookmarks), or
    "unfiltered" (the fetch stopped before the end of the list, or no cutoff
    could be applied; every item is returned).

    Creation times are compared as text, so every backend must give a post's
    "created_at" in the X API's form, such as 2026-10-01T08:00:00.000Z.
    """
    anchors = state_anchor_ids(state, scope)
    if not anchors:
        return items, "no_state"
    if not reached_end:
        # Reviewed posts bookmarked again sit above unfetched new bookmarks and
        # look just like the cutoff, so only a full fetch can confirm it.
        return items, "unfiltered"
    index = cutoff_index(items, anchors)
    if index is not None:
        return items[:index], "anchor"
    created_cutoff = state_last_seen_created_at(state, scope)
    if not created_cutoff:
        return items, "unfiltered"
    # Bookmarks are ordered by bookmark time but X exposes only post creation
    # time, so this is a last resort the caller must flag.
    # ISO-8601 UTC strings in the API's form compare correctly as text.
    newer = [item for item in items if (created_at(item) or "") > created_cutoff]
    return newer, "created_at_fallback"


class Reviewed(NamedTuple):
    """What review() hands back to a fetch helper."""

    # The bookmarks to show: everything fetched, or only those past the cutoff.
    items: list[dict[str, Any]]
    # The review fields of the output's "meta".
    meta: dict[str, Any]
    # Lines for stderr, in order.
    messages: list[str]
    # True when --update-state was due but the state could not be saved.
    failed: bool


def review(
    items: list[dict[str, Any]],
    state: dict[str, Any],
    scope: str,
    state_file: Path,
    *,
    reached_end: bool,
    apply_cutoff: bool,
    save_cutoff: bool,
) -> Reviewed:
    """Apply --since-last and --update-state to a fetched list, newest first.

    Only a fetch that ran to the end of the list surely holds every bookmark
    newer than the old cutoff: in a partial window, reviewed posts bookmarked
    again look just like the cutoff. Saving after a partial fetch could mark
    bookmarks nobody saw as reviewed, so nothing is saved then.
    """
    fetched = list(items)
    shown = fetched
    messages: list[str] = []
    cutoff_mode = None
    if apply_cutoff:
        shown, cutoff_mode = since_last(fetched, state, scope, reached_end)
        if cutoff_mode == "created_at_fallback":
            messages.append(
                "warning: no saved review anchor is still bookmarked; filtered by post "
                "creation time, which can skip or repeat bookmarks"
            )

    state_updated = False
    failed = False
    if save_cutoff and fetched and reached_end:
        try:
            save_state(
                state_file,
                update_last_seen(state, scope, [str(item["id"]) for item in fetched], created_at(fetched[0])),
            )
            state_updated = True
        except OSError as exc:
            # The bookmarks are fetched, and with the API paid for, so they are still shown.
            failed = True
            messages.append(f"error: cannot save the review state file {state_file}: {exc.strerror or exc}")
            messages.append(
                "fix: make that folder writable or pass --state-file, then rerun; the review "
                "cutoff did not move, so these bookmarks are listed as new again"
            )
    if (apply_cutoff or save_cutoff) and not reached_end:
        messages.append(
            "warning: the fetch stopped before the end of the list, so the last review "
            "cutoff cannot be confirmed and some new bookmarks may not have been fetched"
            + ("; review state was not updated" if save_cutoff else "")
        )
        messages.append("fix: rerun with --all and without --max-pages")

    meta = {
        "since_last": apply_cutoff,
        "cutoff_mode": cutoff_mode,
        "cutoff_reached": reached_end,
        "state_updated": state_updated,
        "state_scope": scope,
        "state_file": str(state_file),
    }
    return Reviewed(shown, meta, messages, failed)
