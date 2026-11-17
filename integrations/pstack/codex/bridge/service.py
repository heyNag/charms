"""Authenticated local dispatcher for the proposed /v1/operations contract.

Not an HTTP listener or a deployment. A service host supplies TLS, authentication,
request bounds and a configured provider driver. Default execution stays disabled.
"""

from __future__ import annotations

import json
from typing import Callable

from .protocol import BridgeError, PROTOCOL_VERSION, SCHEMA_VERSION, canonical, check_envelope, digest
from .state import BridgeStore


class BridgeService:
    def __init__(self, store: BridgeStore, authenticate: Callable, *, providers=None):
        self.store = store
        self.authenticate = authenticate
        self.providers = providers
        self.operations = {
            "program.prepare": store.prepare_program,
            "program.activate": store.activate_program,
            "program.inspect": store.inspect_program,
            "program.stop": store.stop_program,
            "program.resume": store.resume_program,
            "lease.renew": store.renew_lease,
            "job.inspect": store.inspect_job,
            "events.read": store.events,
            "effect.prepare": store.prepare_effect,
        }

    def capabilities(self) -> dict:
        provider_caps = self.providers.capabilities() if self.providers is not None else {"providers": {}}
        qualified = sorted({cap for p in provider_caps["providers"].values() for cap in p["capabilities"]})
        operations = ["capabilities", *self.operations]
        if provider_caps["providers"]:
            operations += ["job.submit", "job.retry"]
        return {
            "protocol_versions": [PROTOCOL_VERSION], "schema_versions": [SCHEMA_VERSION],
            "implementation": "pstack-local-reference-v1", "deployment_certified": False,
            "operations": sorted(operations), "qualified_provider_capabilities": qualified,
            "providers": provider_caps["providers"], "native_cloud_history": False,
            "root_only_native_access_certified": False, "ui_stop_propagation_certified": False,
            "storage": "sqlite-local", "artifact_storage": "local-private-files",
        }

    def _require_provider(self, request: dict) -> None:
        if not isinstance(request, dict):
            raise BridgeError("invalid_request", "provider request must be an object")
        requested = request.get("required_capabilities", [])
        if not isinstance(requested, list) or any(not isinstance(cap, str) for cap in requested):
            raise BridgeError("invalid_request", "provider capabilities must be a list of strings")
        provider = request.get("provider")
        if not isinstance(provider, str):
            raise BridgeError("unavailable", "required execution provider is unavailable")
        try:
            self.providers.require(provider, {"execution", *requested})
        except RuntimeError as exc:
            raise BridgeError("unavailable", "required execution provider is unavailable") from exc

    def handle(self, body: bytes, headers: dict) -> bytes:
        if len(body) > 2 * 1024 * 1024:
            raise BridgeError("request_too_large", "bounded control request required")
        actor = self.authenticate(headers, body)
        try:
            request = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise BridgeError("invalid_request", "request must be JSON") from exc
        check_envelope(request)
        if request["tenant"] != actor.tenant or request["project"] != actor.project:
            raise BridgeError("forbidden", "request tenant/project differs from credential binding")
        response = {"protocol_version": PROTOCOL_VERSION, "request_id": request["request_id"],
                    "request_sha256": digest(request)}
        operation = request["operation"]
        payload = request["payload"]

        def invoke():
            if operation == "capabilities":
                actor.require("capabilities")
                return self.capabilities()
            if operation in {"job.submit", "job.retry"}:
                if self.providers is None or not self.providers.capabilities()["providers"]:
                    raise BridgeError("unavailable", "no execution provider is configured")
                if operation == "job.submit":
                    self._require_provider(payload.get("request", {}))
                    return self.store.submit_job(actor, **payload)
                if "_check_provider" in payload:
                    raise BridgeError("invalid_request", "provider validation is service-owned")
                return self.store.retry_job(actor, _check_provider=self._require_provider, **payload)
            method = self.operations.get(operation)
            if method is None:
                raise BridgeError("unavailable", "operation has no configured implementation")
            try:
                return method(actor, **payload)
            except TypeError as exc:
                raise BridgeError("invalid_request", "operation arguments do not match its contract") from exc

        try:
            # Read operations see current state rather than replaying an obsolete inspection.
            if operation in {"capabilities", "program.inspect", "job.inspect", "events.read"}:
                result = invoke()
            else:
                result = self.store.idempotent(actor, request["request_id"], request, invoke)
            response.update(state="recorded", result=result)
        except BridgeError as exc:
            response.update(state="error", error={"code": exc.code, "message": str(exc)})
        return canonical(response)
