"""HTTPS client for the explicitly configured pstack integration endpoint.

It does not discover credentials, follow redirects, retry uncertain operations,
start a heartbeat, or imply that a returned capability is host certification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable

from .protocol import BridgeError, Principal, PROTOCOL_VERSION, canonical, check_envelope, digest

MAX_RESPONSE = 2 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, body, headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            result = response.read(MAX_RESPONSE + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # A timeout after POST might have applied the operation. Never retry here.
        raise BridgeError("transport_unknown", "request outcome unknown; reconcile its request ID") from exc
    if len(result) > MAX_RESPONSE:
        raise BridgeError("response_too_large", "bridge response exceeds the configured bound")
    return result


@dataclass(frozen=True)
class HmacCredential:
    key_id: str
    key: bytes

    def __post_init__(self):
        if not self.key_id or len(self.key) < 32:
            raise ValueError("HMAC requires a named key with at least 256 bits")

    def headers(self, body: bytes, timestamp: int) -> dict[str, str]:
        signed = str(timestamp).encode() + b"\n" + body
        return {
            "X-Pstack-Key": self.key_id,
            "X-Pstack-Time": str(timestamp),
            "X-Pstack-Signature": hmac.new(self.key, signed, hashlib.sha256).hexdigest(),
        }


class HmacAuthenticator:
    """Local-reference auth: fixed credential → scope, never caller role claims.

    Production OIDC is a separate deployment adapter which must verify signature,
    issuer, audience, expiry and project role mapping. This class does not implement
    or claim OIDC, root-thread isolation, key management or TLS termination.
    """

    def __init__(self, credentials: dict[str, tuple[bytes, Principal]], *, clock=time.time,
                 tolerance_seconds: int = 300):
        if tolerance_seconds <= 0:
            raise ValueError("positive clock tolerance required")
        for key, _ in credentials.values():
            if len(key) < 32:
                raise ValueError("authentication keys need at least 256 bits")
        self.credentials = credentials
        self.clock = clock
        self.tolerance = tolerance_seconds

    def authenticate(self, headers: dict, body: bytes) -> Principal:
        credential = self.credentials.get(headers.get("X-Pstack-Key"))
        try:
            timestamp = int(headers.get("X-Pstack-Time", ""))
        except (TypeError, ValueError) as exc:
            raise BridgeError("unauthenticated", "invalid authentication timestamp") from exc
        if credential is None or abs(self.clock() - timestamp) > self.tolerance:
            raise BridgeError("unauthenticated", "unknown credential or expired request")
        key, principal = credential
        expected = hmac.new(key, str(timestamp).encode() + b"\n" + body, hashlib.sha256).hexdigest()
        signature = headers.get("X-Pstack-Signature", "")
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise BridgeError("unauthenticated", "request signature mismatch")
        return principal


class BridgeClient:
    def __init__(self, endpoint: str, *, tenant: str, project: str,
                 authenticate: Callable[[bytes, int], dict[str, str]],
                 transport: Callable = https_transport, timeout: float = 30,
                 clock: Callable = time.time):
        parts = urllib.parse.urlsplit(endpoint)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path not in {"", "/"}):
            raise BridgeError("invalid_endpoint", "explicit HTTPS origin required, without credentials")
        if not 0 < timeout <= 60:
            raise ValueError("timeout must be positive and at most 60 seconds")
        self.endpoint = endpoint.rstrip("/") + "/v1/operations"
        self.tenant = tenant
        self.project = project
        self.authenticate = authenticate
        self.transport = transport
        self.timeout = timeout
        self.clock = clock

    def call(self, operation: str, payload: dict, *, request_id: str | None = None) -> dict:
        request = {
            "protocol_version": PROTOCOL_VERSION, "request_id": request_id or uuid.uuid4().hex,
            "tenant": self.tenant, "project": self.project, "operation": operation,
            "payload": payload, "payload_sha256": digest(payload),
        }
        check_envelope(request)
        body = canonical(request)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        supplied = self.authenticate(body, int(self.clock()))
        for name, value in supplied.items():
            if name.lower() in {"host", "content-length", "content-type"} or "\n" in value or "\r" in value:
                raise BridgeError("invalid_credentials", "invalid authentication header")
        headers.update(supplied)
        raw = self.transport(self.endpoint, body, headers, self.timeout)
        if len(raw) > MAX_RESPONSE:
            raise BridgeError("response_too_large", "bridge response exceeds configured bound")
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise BridgeError("invalid_response", "bridge did not return JSON") from exc
        if (not isinstance(response, dict) or response.get("protocol_version") != PROTOCOL_VERSION
                or response.get("request_id") != request["request_id"]
                or response.get("request_sha256") != digest(request)):
            raise BridgeError("integrity_failure", "response does not match the submitted operation")
        if response.get("state") == "error":
            error = response.get("error", {})
            raise BridgeError(error.get("code", "bridge_error"), error.get("message", "bridge rejected operation"))
        if response.get("state") != "recorded" or not isinstance(response.get("result"), dict):
            raise BridgeError("invalid_response", "operation did not return an explicit recorded result")
        return response["result"]

    def negotiate(self, *, required_operations: set[str] | None = None,
                  required_provider_capabilities: set[str] | None = None) -> dict:
        capabilities = self.call("capabilities", {})
        if (PROTOCOL_VERSION not in capabilities.get("protocol_versions", [])
                or 1 not in capabilities.get("schema_versions", [])):
            raise BridgeError("protocol_mismatch", "no compatible bridge protocol/schema")
        if not (required_operations or set()) <= set(capabilities.get("operations", [])):
            raise BridgeError("unavailable", "required bridge operation is not configured")
        available = set(capabilities.get("qualified_provider_capabilities", []))
        if not (required_provider_capabilities or set()) <= available:
            raise BridgeError("unavailable", "required provider capability is not qualified")
        return capabilities
