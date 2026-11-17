"""Validate authentic producer packets without inventing a native history source."""

from __future__ import annotations

import copy
from typing import Callable

from integrity import RuntimeErrorBase, canonical, digest

NATIVE_KINDS = {"native_cloud", "native_desktop", "native_cli", "original_export"}


def unavailable_history() -> dict:
    return {
        "status": "unavailable",
        "reason": "No qualified original native-history producer is installed.",
        "affected": ["reflect", "show-me-your-work", "recall", "automate-me"],
        "not_substitutes": [
            "assistant journal",
            "model-authored reconstruction",
            "managed child conversation",
        ],
        "support_claim": "Native Cloud whole-transcript and pre-handoff history are not established.",
    }


def inspect_history(
    packet: dict,
    *,
    account_id: str,
    workspace_id: str,
    conversation_id: str,
    cutoff_id: str,
    workflow: str,
    authenticate: Callable[[dict], bool],
    required_history_scope: str | None = None,
) -> dict:
    """A trusted producer driver must authenticate the *whole original packet*.

    Calling this with a model-written file and an always-true callback does not
    establish authenticity. This function is a protocol validator for actual
    driver integration; the CLI intentionally offers no trusted-file bypass.
    """
    if workflow not in {"reflect", "show-me-your-work", "recall", "automate-me"}:
        raise RuntimeErrorBase("unknown history workflow")
    if not authenticate(copy.deepcopy(packet)):
        raise RuntimeErrorBase("original history producer authentication failed")
    if packet.get("schema_version") != 1 or packet.get("source_kind") not in NATIVE_KINDS:
        raise RuntimeErrorBase(
            "history must be original native records, not managed or reconstructed history"
        )
    for key, expected in (
        ("account_id", account_id),
        ("workspace_id", workspace_id),
        ("conversation_id", conversation_id),
        ("cutoff_id", cutoff_id),
    ):
        if packet.get(key) != expected:
            raise RuntimeErrorBase("history packet belongs to another identity or cutoff")
    if not packet.get("producer_id") or not packet.get("provenance_id"):
        raise RuntimeErrorBase("original producer provenance is missing")
    if packet.get("available_before_handoff") is not True:
        raise RuntimeErrorBase("post-final history cannot satisfy this pre-handoff review")
    if packet.get("gaps") or packet.get("truncated") is not False:
        return {
            "status": "partial",
            "reason": "required original interval is missing or truncated",
            "workflow": workflow,
        }
    records = packet.get("records")
    if not isinstance(records, list) or not records:
        raise RuntimeErrorBase("history has no original records")
    seen = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("id"), str)
            or not record["id"]
        ):
            raise RuntimeErrorBase("invalid original record identity")
        if record["id"] in seen:
            raise RuntimeErrorBase("duplicate original record identity; revisions must be explicit")
        if record.get("conversation_id") != conversation_id or not isinstance(
            record.get("original_text"), str
        ):
            raise RuntimeErrorBase("original record content or scope is missing")
        if not record.get("source_coordinate"):
            raise RuntimeErrorBase("original record has no source coordinate")
        seen[record["id"]] = record
    ancestry = []
    current = cutoff_id
    while current is not None:
        if current not in seen:
            return {
                "status": "partial",
                "reason": "missing original ancestor",
                "workflow": workflow,
            }
        if current in ancestry:
            raise RuntimeErrorBase("history ancestry contains a cycle")
        ancestry.append(current)
        current = seen[current].get("previous_id")
    if ancestry[-1] != packet.get("run_start_id"):
        return {
            "status": "partial",
            "reason": "original run prefix is not present",
            "workflow": workflow,
        }
    if packet.get("selected_branch") is None or packet.get("unresolved_revisions"):
        return {
            "status": "partial",
            "reason": "branch or revision selection is unresolved",
            "workflow": workflow,
        }
    if workflow == "reflect" and packet.get("whole_transcript") is not True:
        return {
            "status": "partial",
            "reason": "Reflect requires the whole original transcript",
            "workflow": workflow,
        }
    if workflow in {"recall", "automate-me"}:
        if not required_history_scope or required_history_scope not in packet.get(
            "complete_history_scopes", []
        ):
            return {
                "status": "partial",
                "reason": "requested historical scope is not covered",
                "workflow": workflow,
            }
    # Weak claim evidence can be a valid audit finding. This status never means
    # work passed, independent vendor review ran, or every operation succeeded.
    return {
        "status": "original_chronology_validated",
        "workflow": workflow,
        "packet_sha256": digest(canonical(packet)),
        "record_ids": list(reversed(ancestry)),
        "claim_evidence": packet.get("claim_evidence", []),
        "work_verified": False,
        "review_complete": False,
        "whole_transcript": packet.get("whole_transcript") is True,
    }
