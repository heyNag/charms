"""Versioned integration protocol; these are pstack operations, not Codex tools."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
SCHEMA_VERSION = 1
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class BridgeError(ValueError):
    """A typed failure whose code must not be reported as successful completion."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise BridgeError("invalid_request", "invalid opaque identifier")
    return value


def positive(value: int, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise BridgeError("invalid_request", f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class Principal:
    """Produced by a configured authenticator, never parsed from request role claims.

    A Python caller of BridgeStore is trusted service code. At the transport boundary
    the authenticated key/token maps to these fixed scopes and resource constraints.
    Native child inheritance is not an authenticated root-thread boundary.
    """

    tenant: str
    project: str
    subject: str
    scopes: frozenset[str]
    role: str = "coordinator"
    programs: frozenset[str] = frozenset()
    jobs: frozenset[str] = frozenset()

    def require(self, scope: str, program: str | None = None, job: str | None = None) -> None:
        if scope not in self.scopes:
            raise BridgeError("forbidden", f"missing operation scope: {scope}")
        if self.role == "worker" and not self.programs:
            raise BridgeError("forbidden", "worker credential has no program binding")
        if self.programs and program is not None and program not in self.programs:
            raise BridgeError("forbidden", "credential belongs to another program")
        if self.role == "worker" and job is not None and job not in self.jobs:
            raise BridgeError("forbidden", "worker credential belongs to another job")


def check_envelope(envelope: dict) -> None:
    if not isinstance(envelope, dict) or envelope.get("protocol_version") != PROTOCOL_VERSION:
        raise BridgeError("protocol_mismatch", "only protocol version 1 is supported")
    for key in ("request_id", "tenant", "project"):
        identifier(envelope.get(key))
    if not isinstance(envelope.get("operation"), str) or not isinstance(envelope.get("payload"), dict):
        raise BridgeError("invalid_request", "operation and object payload are required")
    if envelope.get("payload_sha256") != digest(envelope["payload"]):
        raise BridgeError("integrity_failure", "payload digest mismatch")
