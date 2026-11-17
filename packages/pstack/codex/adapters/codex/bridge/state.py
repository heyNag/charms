"""Durable local bridge reference kernel, not a distributed deployment.

All logical transitions and delivery intents commit in one SQLite transaction.
External effects occur after that commit; lost acknowledgements stay uncertain.
A managed backend must preserve these conditional-write/transaction invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from typing import Callable

from .protocol import BridgeError, Principal, SCHEMA_VERSION, canonical, digest, identifier, positive

TERMINAL = {"completed", "failed", "cancelled"}


class BridgeStore:
    def __init__(self, database: str | Path, artifacts: str | Path, *, clock: Callable = time.time):
        self.database = Path(database)
        self.artifacts = Path(artifacts)
        self.clock = clock
        self._depth = 0
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.database.is_symlink() or self.artifacts.is_symlink():
            raise BridgeError("invalid_storage", "storage roots must not be symlinks")
        self.db = sqlite3.connect(self.database, isolation_level=None, timeout=10)
        os.chmod(self.database, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, tenant TEXT NOT NULL,
                project TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
                PRIMARY KEY(kind, id, tenant, project)
            );
            CREATE INDEX IF NOT EXISTS record_scope ON records(tenant, project, kind);
            CREATE TABLE IF NOT EXISTS requests (
                tenant TEXT NOT NULL, project TEXT NOT NULL, request_id TEXT NOT NULL,
                digest TEXT NOT NULL, response TEXT NOT NULL,
                PRIMARY KEY(tenant, project, request_id)
            );
        """)
        row = self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row is not None and row[0] != str(SCHEMA_VERSION):
            self.db.close()
            raise BridgeError("schema_mismatch", "state needs an explicit migration")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),))

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _atomic(self):
        # SAVEPOINT supports the idempotent request transaction containing operations.
        root = self._depth == 0
        if root:
            self.db.execute("BEGIN IMMEDIATE")
        name = f"pstack_{self._depth}"
        self._depth += 1
        self.db.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self.db.execute(f"ROLLBACK TO {name}")
            self.db.execute(f"RELEASE {name}")
            if root:
                self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute(f"RELEASE {name}")
            if root:
                self.db.execute("COMMIT")
        finally:
            self._depth -= 1

    def _get(self, actor: Principal, kind: str, record_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM records WHERE kind=? AND id=? AND tenant=? AND project=?",
            (kind, record_id, actor.tenant, actor.project),
        ).fetchone()
        if row is None:
            raise BridgeError("not_found", f"{kind} not found in credential scope")
        return {**json.loads(row["document"]), "revision": row["revision"]}

    def _put(self, actor: Principal, kind: str, value: dict, *, new: bool = False) -> dict:
        value = dict(value)
        old_revision = value.pop("revision", 0)
        value.setdefault("created_at", self.clock())
        value["updated_at"] = self.clock()
        if new:
            try:
                self.db.execute("INSERT INTO records VALUES (?,?,?,?,?,?)", (
                    kind, value["id"], actor.tenant, actor.project, 1, canonical(value).decode(),
                ))
            except sqlite3.IntegrityError as exc:
                raise BridgeError("conflict", "record already exists") from exc
            return {**value, "revision": 1}
        result = self.db.execute(
            "UPDATE records SET revision=?, document=? WHERE kind=? AND id=? "
            "AND tenant=? AND project=? AND revision=?",
            (old_revision + 1, canonical(value).decode(), kind, value["id"],
             actor.tenant, actor.project, old_revision),
        )
        if result.rowcount != 1:
            raise BridgeError("stale_revision", "record changed during transition")
        return {**value, "revision": old_revision + 1}

    def _list(self, actor: Principal, kind: str, program: str | None = None) -> list[dict]:
        rows = self.db.execute(
            "SELECT document,revision FROM records WHERE kind=? AND tenant=? AND project=? "
            "ORDER BY id", (kind, actor.tenant, actor.project),
        ).fetchall()
        values = [{**json.loads(r[0]), "revision": r[1]} for r in rows]
        return [r for r in values if program is None or r.get("program_id") == program]

    def _outbox(self, actor: Principal, operation: str, program: str, payload: dict) -> dict:
        return self._put(actor, "outbox", {
            "id": uuid.uuid4().hex, "program_id": program, "operation": operation,
            "payload": payload, "payload_sha256": digest(payload), "state": "pending",
        }, new=True)

    def idempotent(self, actor: Principal, request_id: str, request: dict, operation: Callable) -> dict:
        """Commit a state transition and its replay response together.

        operation must contain local transactions only. Remote effects use outbox or
        begin_effect outside this request transaction, never a synchronous retry loop.
        """
        identifier(request_id)
        request_digest = digest({"subject": actor.subject, "request": request})
        with self._atomic():
            row = self.db.execute(
                "SELECT digest,response FROM requests WHERE tenant=? AND project=? AND request_id=?",
                (actor.tenant, actor.project, request_id),
            ).fetchone()
            if row:
                if row[0] != request_digest:
                    raise BridgeError("idempotency_conflict", "request key was used for other content")
                return json.loads(row[1])
            response = operation()
            self.db.execute("INSERT INTO requests VALUES (?,?,?,?,?)", (
                actor.tenant, actor.project, request_id, request_digest, canonical(response).decode(),
            ))
            return response

    def issue_grant(self, actor: Principal, grant_id: str, *, repository: str,
                    operations: list[str], expires_at: float, detached: bool = False,
                    targets: list[str] | None = None) -> dict:
        actor.require("grant.issue")
        if actor.role != "operator":
            raise BridgeError("forbidden", "only an authenticated operator can record a grant")
        identifier(grant_id)
        if not repository or not operations or expires_at <= self.clock():
            raise BridgeError("invalid_grant", "repository, operations and future expiry required")
        if not all(isinstance(op, str) and op for op in operations):
            raise BridgeError("invalid_grant", "grant operations must be explicit strings")
        with self._atomic():
            return self._put(actor, "grant", {
                "id": grant_id, "repository": repository, "operations": sorted(set(operations)),
                "expires_at": expires_at, "detached": bool(detached), "targets": targets or [],
                "operator": actor.subject, "revoked": False,
            }, new=True)

    def revoke_grant(self, actor: Principal, grant_id: str) -> dict:
        actor.require("grant.issue")
        if actor.role != "operator":
            raise BridgeError("forbidden", "only an operator revokes grants")
        with self._atomic():
            grant = self._get(actor, "grant", grant_id)
            grant["revoked"] = True
            return self._put(actor, "grant", grant)

    def _grant(self, actor: Principal, program: dict, operation: str, target: str | None = None) -> dict:
        grant = self._get(actor, "grant", program["grant_id"])
        if grant["revoked"] or grant["expires_at"] <= self.clock():
            raise BridgeError("authority_expired", "operator grant is revoked or expired")
        if grant["repository"] != program["binding"]["repository"]:
            raise BridgeError("forbidden", "grant is bound to another repository")
        if operation not in grant["operations"]:
            raise BridgeError("forbidden", "operator grant does not include this operation")
        if target is not None and target not in grant["targets"]:
            raise BridgeError("forbidden", "target was not included in the operator grant")
        if program["lifetime"] == "detached" and not grant["detached"]:
            raise BridgeError("forbidden", "detached execution is not authorized")
        return grant

    def prepare_program(self, actor: Principal, program_id: str, *, binding: dict, goal: str,
                        lifetime: str = "interactive", max_attempts: int = 20) -> dict:
        actor.require("program.prepare", program_id)
        if actor.role == "worker":
            raise BridgeError("forbidden", "workers cannot prepare programs")
        identifier(program_id)
        positive(max_attempts, "max_attempts", 10000)
        required = ("profile_id", "profile_revision", "repository", "payload_sha256",
                    "account_id", "workspace_id", "surface", "binding_sha256")
        if not isinstance(binding, dict) or any(not binding.get(k) for k in required):
            raise BridgeError("invalid_binding", "complete runtime binding required")
        if lifetime not in {"interactive", "detached"} or not isinstance(goal, str) or not goal:
            raise BridgeError("invalid_request", "goal and valid lifetime required")
        with self._atomic():
            return self._put(actor, "program", {
                "id": program_id, "program_id": program_id, "binding": binding,
                "binding_digest": digest(binding), "goal": goal, "lifetime": lifetime,
                "max_attempts": max_attempts, "state": "prepared", "epoch": 0,
                "lease_until": None, "grant_id": None, "stop_reason": None,
            }, new=True)

    def inspect_program(self, actor: Principal, program_id: str) -> dict:
        actor.require("program.inspect", program_id)
        return self._get(actor, "program", program_id)

    def activate_program(self, actor: Principal, program_id: str, *, grant_id: str,
                         expected_revision: int, lease_seconds: int = 120) -> dict:
        actor.require("program.activate", program_id)
        if actor.role == "worker":
            raise BridgeError("forbidden", "workers cannot activate programs")
        positive(lease_seconds, "lease_seconds", 3600)
        with self._atomic():
            program = self._get(actor, "program", program_id)
            if program["state"] != "prepared" or program["revision"] != expected_revision:
                raise BridgeError("stale_revision", "activation preview changed")
            program["grant_id"] = grant_id
            self._grant(actor, program, "program.run")
            program.update(state="active", epoch=1, coordinator=actor.subject,
                           lease_until=self.clock() + lease_seconds
                           if program["lifetime"] == "interactive" else None)
            return self._put(actor, "program", program)

    def _active(self, actor: Principal, program_id: str, epoch: int, operation: str) -> dict:
        program = self._get(actor, "program", program_id)
        if program["state"] != "active" or program["epoch"] != epoch:
            raise BridgeError("stale_epoch", "program is inactive or ownership changed")
        if actor.role == "coordinator" and actor.subject != program["coordinator"]:
            raise BridgeError("forbidden", "credential is not the current coordinator owner")
        if program["lease_until"] is not None and program["lease_until"] <= self.clock():
            # This check fences synchronously even before a reconciler records expiry.
            raise BridgeError("lease_expired", "coordinator lease expired, not user cancellation")
        self._grant(actor, program, operation)
        return program

    def renew_lease(self, actor: Principal, program_id: str, *, epoch: int,
                    lease_seconds: int = 120) -> dict:
        actor.require("lease.renew", program_id)
        positive(lease_seconds, "lease_seconds", 3600)
        with self._atomic():
            program = self._active(actor, program_id, epoch, "program.run")
            if actor.role != "coordinator" or program["coordinator"] != actor.subject:
                raise BridgeError("forbidden", "only the bound live coordinator may renew")
            if program["lifetime"] != "interactive":
                raise BridgeError("invalid_state", "detached grants do not use interactive leases")
            program["lease_until"] = self.clock() + lease_seconds
            return self._put(actor, "program", program)

    def _fence(self, actor: Principal, program: dict, state: str, reason: str) -> dict:
        program.update(state=state, epoch=program["epoch"] + 1, stop_reason=reason, lease_until=None)
        for attempt in self._list(actor, "attempt", program["id"]):
            if attempt["cleanup_state"] != "terminated":
                attempt["cancel_requested"] = True
                self._put(actor, "attempt", attempt)
                self._outbox(actor, "provider.cancel", program["id"], {
                    "attempt_id": attempt["id"], "launch_token": attempt["launch_token"],
                    "provider_ids": attempt.get("provider_ids", {}), "reason": reason,
                })
        for wake in self._list(actor, "wake", program["id"]):
            if wake["state"] != "disabled":
                wake["state"] = "disable_pending"
                self._put(actor, "wake", wake)
                self._outbox(actor, "schedule.disable", program["id"], {"wake_id": wake["id"]})
        return self._put(actor, "program", program)

    def stop_program(self, actor: Principal, program_id: str, *, epoch: int,
                     pause: bool = False) -> dict:
        actor.require("program.stop", program_id)
        if actor.role not in {"operator", "coordinator"}:
            raise BridgeError("forbidden", "only the operator or current coordinator can stop a program")
        with self._atomic():
            program = self._get(actor, "program", program_id)
            if program["epoch"] != epoch:
                raise BridgeError("stale_epoch", "ownership changed")
            if actor.role == "coordinator" and actor.subject != program.get("coordinator"):
                raise BridgeError("forbidden", "credential is not the current coordinator owner")
            if program["state"] in {"stopped", "stopping"}:
                return program
            return self._fence(actor, program, "paused" if pause else "stopping",
                               "operator_pause" if pause else "operator_stop")

    def expire_leases(self, actor: Principal) -> list[str]:
        actor.require("lifecycle.reconcile")
        expired = []
        with self._atomic():
            for program in self._list(actor, "program"):
                if (program["state"] == "active" and program["lease_until"] is not None
                        and program["lease_until"] <= self.clock()):
                    self._fence(actor, program, "lease_expired", "coordinator_lease_expired")
                    expired.append(program["id"])
        return expired

    def resume_program(self, actor: Principal, program_id: str, *, binding: dict,
                       expected_revision: int, lease_seconds: int = 120,
                       take_ownership: bool = False) -> dict:
        actor.require("program.resume", program_id)
        if actor.role != "coordinator":
            raise BridgeError("forbidden", "only coordinator resumes programs")
        positive(lease_seconds, "lease_seconds", 3600)
        with self._atomic():
            program = self._get(actor, "program", program_id)
            if program["revision"] != expected_revision or program["state"] not in {
                "paused", "lease_expired",
            }:
                raise BridgeError("stale_revision", "program is not the reviewed resumable state")
            if digest(binding) != program["binding_digest"]:
                raise BridgeError("binding_mismatch", "profile/account/payload cannot migrate a live run")
            self._grant(actor, program, "program.run")
            if actor.subject != program["coordinator"]:
                if not take_ownership:
                    raise BridgeError("forbidden", "explicit coordinator ownership transfer required")
                self._grant(actor, program, "program.transfer")
            pending = [a for a in self._list(actor, "effect", program_id)
                       if a["state"] in {"sent", "uncertain"}]
            if pending:
                raise BridgeError("reconciliation_required", "external effects need readback first")
            program.update(state="active", epoch=program["epoch"] + 1, coordinator=actor.subject,
                           lease_until=self.clock() + lease_seconds
                           if program["lifetime"] == "interactive" else None, stop_reason=None)
            return self._put(actor, "program", program)

    def submit_job(self, actor: Principal, program_id: str, *, epoch: int, business_key: dict,
                   request: dict, predicate: dict, lifetime_seconds: int = 3600,
                   export_reserve_seconds: int = 60, strict_vm: bool = False) -> dict:
        actor.require("job.submit", program_id)
        if actor.role != "coordinator":
            raise BridgeError("forbidden", "worker launch requires an explicit coordinator broker")
        positive(lifetime_seconds, "lifetime_seconds", 28800 if strict_vm else 86400)
        positive(export_reserve_seconds, "export_reserve_seconds", lifetime_seconds - 1)
        if not business_key or not predicate.get("revision") or not request:
            raise BridgeError("invalid_request", "business identity, request and predicate required")
        job_id = digest([actor.tenant, actor.project, program_id, business_key])
        with self._atomic():
            program = self._active(actor, program_id, epoch, "job.submit")
            try:
                old = self._get(actor, "job", job_id)
            except BridgeError as exc:
                if exc.code != "not_found":
                    raise
            else:
                if old["request_digest"] != digest(request) or old["predicate"] != predicate:
                    raise BridgeError("business_conflict", "same logical job has different inputs")
                return old
            attempts = self._list(actor, "attempt", program_id)
            if len(attempts) >= program["max_attempts"]:
                raise BridgeError("budget_exhausted", "program attempt budget exhausted")
            attempt_id = uuid.uuid4().hex
            attempt = {
                "id": attempt_id, "program_id": program_id, "job_id": job_id,
                "generation": 1, "owner_epoch": epoch, "request": request,
                "input_digest": digest(request), "launch_token": uuid.uuid4().hex,
                "state": "prepared", "cancel_requested": False, "strict_vm": strict_vm,
                "cleanup_state": "pending", "provider_ids": {}, "artifacts": [],
                "hard_deadline": self.clock() + lifetime_seconds,
                "export_deadline": self.clock() + lifetime_seconds - export_reserve_seconds,
            }
            self._put(actor, "attempt", attempt, new=True)
            job = self._put(actor, "job", {
                "id": job_id, "program_id": program_id, "business_key": business_key,
                "request_digest": digest(request), "predicate": predicate,
                "current_attempt": attempt_id, "generation": 1, "state": "pending",
            }, new=True)
            self._outbox(actor, "provider.launch", program_id, {
                "attempt_id": attempt_id, "launch_token": attempt["launch_token"],
                "input_digest": attempt["input_digest"], "owner_epoch": epoch,
            })
            return job

    def inspect_job(self, actor: Principal, job_id: str) -> dict:
        job = self._get(actor, "job", job_id)
        actor.require("job.inspect", job["program_id"], job_id)
        attempt = self._get(actor, "attempt", job["current_attempt"])
        return {"job": job, "attempt": attempt}

    def record_launch(self, actor: Principal, attempt_id: str, *, launch_token: str,
                      provider_ids: dict, observation: dict) -> dict:
        actor.require("provider.observe")
        if actor.role != "provider":
            raise BridgeError("forbidden", "launch facts require authenticated provider adapter")
        if not provider_ids or not observation.get("driver_version"):
            raise BridgeError("invalid_receipt", "provider identity and driver version required")
        with self._atomic():
            attempt = self._get(actor, "attempt", attempt_id)
            actor.require("provider.observe", attempt["program_id"], attempt["job_id"])
            if attempt["launch_token"] != launch_token:
                raise BridgeError("invalid_receipt", "provider receipt belongs to another launch")
            if attempt["provider_ids"]:
                if attempt["provider_ids"] != provider_ids or attempt.get("observation") != observation:
                    raise BridgeError("conflict", "provider launch identity is immutable")
                return attempt
            if attempt["cleanup_state"] == "terminated":
                raise BridgeError("conflict", "terminated attempt cannot accept a new launch")
            attempt.update(provider_ids=provider_ids, observation=observation, state="running")
            program = self._get(actor, "program", attempt["program_id"])
            if program["epoch"] != attempt["owner_epoch"] or program["state"] != "active":
                attempt["cancel_requested"] = True
                self._outbox(actor, "provider.cancel", attempt["program_id"], {
                    "attempt_id": attempt_id, "provider_ids": provider_ids, "reason": "late_launch",
                })
            return self._put(actor, "attempt", attempt)

    def ingest_event(self, actor: Principal, *, provider: str, event_id: str,
                     payload: dict, program_id: str, attempt_id: str | None = None) -> dict:
        actor.require("event.ingest", program_id)
        if actor.role != "provider":
            raise BridgeError("forbidden", "original events require authenticated provider intake")
        identifier(provider)
        identifier(event_id)
        record_id = digest([actor.tenant, actor.project, provider, event_id])
        body = {"provider": provider, "event_id": event_id, "payload": payload,
                "program_id": program_id, "attempt_id": attempt_id}
        with self._atomic():
            try:
                old = self._get(actor, "event", record_id)
            except BridgeError as exc:
                if exc.code != "not_found":
                    raise
            else:
                if old["content_digest"] != digest(body):
                    raise BridgeError("idempotency_conflict", "provider event content changed")
                return old
            program = self._get(actor, "program", program_id)
            disposition = "wake_hint"
            if attempt_id:
                attempt = self._get(actor, "attempt", attempt_id)
                if attempt["program_id"] != program_id:
                    raise BridgeError("invalid_receipt", "event attempt belongs to another program")
                job = self._get(actor, "job", attempt["job_id"])
                if (job["current_attempt"] != attempt_id
                        or program["epoch"] != attempt["owner_epoch"]
                        or program["state"] != "active"):
                    disposition = "stale_observation"
            event = self._put(actor, "event", {
                **body, "id": record_id, "content_digest": digest(body),
                "disposition": disposition,
            }, new=True)
            if disposition == "wake_hint":
                self._outbox(actor, "coordinator.inspect", program_id, {"event_id": record_id})
            return event

    def events(self, actor: Principal, program_id: str, *, after: str | None = None,
               limit: int = 100) -> dict:
        actor.require("events.read", program_id)
        positive(limit, "limit", 1000)
        values = self._list(actor, "event", program_id)
        # Opaque IDs are not chronological; the persisted rowid is the cursor.
        rows = self.db.execute(
            "SELECT rowid,id FROM records WHERE kind='event' AND tenant=? AND project=? ORDER BY rowid",
            (actor.tenant, actor.project),
        ).fetchall()
        indexed = {v["id"]: v for v in values}
        try:
            cursor = 0 if after is None else int(after)
        except (ValueError, TypeError) as exc:
            raise BridgeError("invalid_request", "invalid event cursor") from exc
        selected = [(r[0], indexed[r[1]]) for r in rows if r[0] > cursor and r[1] in indexed]
        page = selected[:limit]
        return {"events": [r[1] for r in page],
                "next_cursor": str(page[-1][0]) if page else str(cursor),
                "has_more": len(selected) > limit}

    def prepare_effect(self, actor: Principal, program_id: str, *, epoch: int,
                       operation_id: str, operation: str, target: str, expected_revision: str,
                       intent: dict) -> dict:
        actor.require("effect.prepare", program_id)
        if actor.role != "coordinator":
            raise BridgeError("forbidden", "only the coordinator has external-effect authority")
        identifier(operation_id)
        if not target or not expected_revision or not intent:
            raise BridgeError("invalid_request", "exact target, expected revision and intent required")
        with self._atomic():
            program = self._active(actor, program_id, epoch, operation)
            self._grant(actor, program, operation, target)
            body = {"program_id": program_id, "operation": operation, "target": target,
                    "expected_revision": expected_revision, "intent": intent}
            record_id = digest([actor.tenant, actor.project, program_id, operation_id])
            try:
                old = self._get(actor, "effect", record_id)
            except BridgeError as exc:
                if exc.code != "not_found":
                    raise
            else:
                if old["intent_digest"] != digest(body):
                    raise BridgeError("idempotency_conflict", "effect key has different intent")
                return old
            return self._put(actor, "effect", {
                **body, "id": record_id, "operation_id": operation_id,
                "intent_digest": digest(body), "owner_epoch": epoch,
                "grant_id": program["grant_id"], "state": "prepared", "receipt": None,
                "correlation_token": uuid.uuid4().hex,
            }, new=True)

    def begin_effect(self, actor: Principal, effect_id: str, *, epoch: int) -> dict:
        """Persist sent before the trusted adapter calls an external system once."""
        with self._atomic():
            effect = self._get(actor, "effect", effect_id)
            actor.require("effect.execute", effect["program_id"])
            if actor.role != "coordinator":
                raise BridgeError("forbidden", "only the coordinator has external-effect authority")
            program = self._active(actor, effect["program_id"], epoch, effect["operation"])
            self._grant(actor, program, effect["operation"], effect["target"])
            if effect["owner_epoch"] != epoch:
                raise BridgeError("stale_epoch", "prepared effect belongs to old ownership")
            if effect["state"] != "prepared":
                raise BridgeError("reconciliation_required", "sent/uncertain effects must not retry")
            effect["state"] = "sent"
            return self._put(actor, "effect", effect)

    def reconcile_effect(self, actor: Principal, effect_id: str, *, outcome: str,
                         correlation_token: str, receipt: dict) -> dict:
        """Readback may arrive after stop: record it without restoring write authority."""
        actor.require("effect.reconcile")
        if actor.role != "provider":
            raise BridgeError("forbidden", "reconciliation requires authenticated provider readback")
        if outcome not in {"confirmed", "not_applied", "uncertain", "compensation_failed"}:
            raise BridgeError("invalid_request", "invalid effect outcome")
        if not receipt:
            raise BridgeError("invalid_receipt", "readback evidence required")
        with self._atomic():
            effect = self._get(actor, "effect", effect_id)
            actor.require("effect.reconcile", effect["program_id"])
            if (correlation_token != effect["correlation_token"]
                    or receipt.get("target") != effect["target"]):
                raise BridgeError("invalid_receipt", "receipt belongs to another external operation")
            if effect["state"] not in {"sent", "uncertain"}:
                if effect["state"] == outcome and effect["receipt"] == receipt:
                    return effect
                raise BridgeError("invalid_state", "effect has no outstanding external outcome")
            effect.update(state=outcome, receipt=receipt)
            return self._put(actor, "effect", effect)

    def claim_delivery(self, actor: Principal, delivery_id: str) -> dict:
        actor.require("outbox.dispatch")
        with self._atomic():
            delivery = self._get(actor, "outbox", delivery_id)
            if delivery["state"] != "pending":
                raise BridgeError("reconciliation_required", "delivery already claimed; inspect before retry")
            if delivery["operation"] == "provider.launch":
                attempt = self._get(actor, "attempt", delivery["payload"]["attempt_id"])
                self._active(actor, attempt["program_id"], attempt["owner_epoch"], "job.submit")
                if attempt["cancel_requested"] or attempt["export_deadline"] <= self.clock():
                    raise BridgeError("deadline_exceeded", "launch is cancelled or its budget expired")
            delivery.update(state="claimed", dispatcher=actor.subject)
            return self._put(actor, "outbox", delivery)

    def pending_deliveries(self, actor: Principal) -> list[dict]:
        actor.require("outbox.dispatch")
        return [v for v in self._list(actor, "outbox") if v["state"] == "pending"]

    def reconcile_delivery(self, actor: Principal, delivery_id: str, *, outcome: str,
                           receipt: dict) -> dict:
        actor.require("outbox.dispatch")
        if outcome not in {"confirmed", "uncertain", "not_delivered"} or not receipt:
            raise BridgeError("invalid_receipt", "delivery readback required")
        with self._atomic():
            delivery = self._get(actor, "outbox", delivery_id)
            if delivery["state"] not in {"claimed", "uncertain"}:
                raise BridgeError("invalid_state", "delivery is not outstanding")
            delivery.update(state=outcome, receipt=receipt)
            return self._put(actor, "outbox", delivery)

    def publish_artifact(self, actor: Principal, attempt_id: str, *, data: bytes,
                         source_revision: str, retain_until: float) -> dict:
        actor.require("artifact.publish")
        if len(data) > 32 * 1024 * 1024 or retain_until <= self.clock() or not source_revision:
            raise BridgeError("invalid_artifact", "bounded bytes, revision and future retention required")
        sha = hashlib.sha256(data).hexdigest()
        path = self.artifacts / sha
        with self._atomic():
            attempt = self._get(actor, "attempt", attempt_id)
            actor.require("artifact.publish", attempt["program_id"], attempt["job_id"])
            if attempt["cleanup_state"] == "terminated":
                raise BridgeError("invalid_state", "attempt has already been cleaned up")
            if path.exists() or path.is_symlink():
                if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise BridgeError("integrity_failure", "existing artifact is not the expected regular blob")
            else:
                fd, name = tempfile.mkstemp(dir=self.artifacts, prefix=".staging-")
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(name, path)
                finally:
                    if os.path.exists(name):
                        os.unlink(name)
            artifact = self._put(actor, "artifact", {
                "id": uuid.uuid4().hex, "program_id": attempt["program_id"],
                "job_id": attempt["job_id"], "attempt_id": attempt_id,
                "sha256": sha, "size": len(data), "producer": actor.subject,
                "source_revision": source_revision, "retain_until": retain_until,
            }, new=True)
            attempt["artifacts"].append(artifact["id"])
            self._put(actor, "attempt", attempt)
            return artifact

    def read_artifact(self, actor: Principal, artifact_id: str) -> bytes:
        artifact = self._get(actor, "artifact", artifact_id)
        actor.require("artifact.read", artifact["program_id"], artifact["job_id"])
        if artifact["retain_until"] <= self.clock():
            raise BridgeError("expired", "artifact retention window expired")
        path = self.artifacts / artifact["sha256"]
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise BridgeError("integrity_failure", "artifact is not a regular file")
        data = path.read_bytes()
        if len(data) != artifact["size"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise BridgeError("integrity_failure", "artifact digest mismatch")
        return data

    def record_completion(self, actor: Principal, attempt_id: str, *, root_turn_receipt: dict,
                          tested_revision: str, outcome: str) -> dict:
        actor.require("provider.observe")
        if actor.role != "provider" or root_turn_receipt.get("terminal") is not True:
            raise BridgeError("invalid_receipt", "authoritative terminal root-turn receipt required")
        if outcome not in {"completed", "failed", "cancelled", "model_violation"}:
            raise BridgeError("invalid_receipt", "unsupported semantic result")
        with self._atomic():
            attempt = self._get(actor, "attempt", attempt_id)
            actor.require("provider.observe", attempt["program_id"], attempt["job_id"])
            job = self._get(actor, "job", attempt["job_id"])
            program = self._get(actor, "program", attempt["program_id"])
            if (job["current_attempt"] != attempt_id or program["epoch"] != attempt["owner_epoch"]
                    or program["state"] != "active"):
                raise BridgeError("stale_epoch", "old result cannot complete current job")
            if attempt["cleanup_state"] == "terminated":
                if (attempt.get("root_turn_receipt") == root_turn_receipt
                        and attempt.get("outcome") == outcome
                        and attempt.get("tested_revision") == tested_revision):
                    return attempt
                raise BridgeError("conflict", "terminal attempt result is immutable")
            self._active(actor, attempt["program_id"], attempt["owner_epoch"], "job.submit")
            if (root_turn_receipt.get("predicate_sha256") != digest(job["predicate"])
                    or root_turn_receipt.get("input_sha256") != attempt["input_digest"]
                    or root_turn_receipt.get("provider_ids") != attempt["provider_ids"]):
                raise BridgeError("invalid_receipt", "completion does not bind inputs/predicate/provider")
            if not attempt["provider_ids"] or not attempt["artifacts"]:
                raise BridgeError("evidence_missing", "provider identity and exported result required")
            if tested_revision != job["predicate"].get("revision"):
                raise BridgeError("stale_revision", "result does not prove the requested revision")
            if attempt["state"] == "finishing":
                if attempt.get("root_turn_receipt") == root_turn_receipt and attempt.get("outcome") == outcome:
                    return attempt
                raise BridgeError("conflict", "terminal result is immutable")
            attempt.update(state="finishing", outcome=outcome, root_turn_receipt=root_turn_receipt,
                           tested_revision=tested_revision)
            result = self._put(actor, "attempt", attempt)
            self._outbox(actor, "provider.terminate", attempt["program_id"], {
                "attempt_id": attempt_id, "provider_ids": attempt["provider_ids"],
            })
            return result

    def observe_termination(self, actor: Principal, attempt_id: str, *, receipt: dict) -> dict:
        actor.require("provider.observe")
        if actor.role != "provider" or receipt.get("state") != "TERMINATED":
            raise BridgeError("invalid_receipt", "confirmed provider termination required")
        with self._atomic():
            attempt = self._get(actor, "attempt", attempt_id)
            actor.require("provider.observe", attempt["program_id"], attempt["job_id"])
            if (receipt.get("provider_ids") != attempt["provider_ids"]
                    or receipt.get("launch_token") != attempt["launch_token"]):
                raise BridgeError("invalid_receipt", "termination belongs to another provider resource")
            if attempt["cleanup_state"] == "terminated":
                if attempt.get("termination_receipt") == receipt:
                    return attempt
                raise BridgeError("conflict", "terminal cleanup receipt is immutable")
            if not attempt["artifacts"]:
                raise BridgeError("evidence_missing", "export/checkpoint required before cleanup acceptance")
            if attempt["state"] != "finishing" and not attempt["cancel_requested"]:
                raise BridgeError("invalid_state", "neither complete nor cancellation requested")
            attempt.update(cleanup_state="terminated", termination_receipt=receipt,
                           state=attempt.get("outcome", "cancelled"))
            result = self._put(actor, "attempt", attempt)
            job = self._get(actor, "job", attempt["job_id"])
            program = self._get(actor, "program", attempt["program_id"])
            if job["current_attempt"] == attempt_id:
                job["state"] = attempt["state"] if program["epoch"] == attempt["owner_epoch"] else "cancelled"
                self._put(actor, "job", job)
            remaining = [a for a in self._list(actor, "attempt", attempt["program_id"])
                         if a["cleanup_state"] != "terminated"]
            wakes = [w for w in self._list(actor, "wake", attempt["program_id"])
                     if w["state"] != "disabled"]
            unresolved = [a for a in self._list(actor, "effect", attempt["program_id"])
                          if a["state"] in {"sent", "uncertain", "compensation_failed"}]
            if program["state"] == "stopping" and not remaining and not wakes and not unresolved:
                program["state"] = "stopped"
                self._put(actor, "program", program)
            return result

    def register_wake(self, actor: Principal, program_id: str, *, epoch: int,
                      wake_id: str, registration: dict) -> dict:
        actor.require("schedule.register", program_id)
        required = ("provider", "provider_id", "target", "timezone", "next_at", "readback")
        if any(not registration.get(key) for key in required):
            raise BridgeError("invalid_receipt", "actual registration identity and readback required")
        with self._atomic():
            program = self._active(actor, program_id, epoch, "schedule.register")
            if program["lifetime"] != "detached":
                raise BridgeError("forbidden", "durable wakes need an existing detached grant")
            return self._put(actor, "wake", {
                "id": identifier(wake_id), "program_id": program_id, "registration": registration,
                "state": "registered_unobserved", "tick_receipt": None,
            }, new=True)

    def observe_wake(self, actor: Principal, wake_id: str, *, receipt: dict,
                     disabled: bool = False) -> dict:
        actor.require("provider.observe")
        if actor.role != "provider" or not receipt:
            raise BridgeError("invalid_receipt", "authenticated wake readback required")
        with self._atomic():
            wake = self._get(actor, "wake", wake_id)
            actor.require("provider.observe", wake["program_id"])
            program = self._get(actor, "program", wake["program_id"])
            if (receipt.get("provider_id") != wake["registration"]["provider_id"]
                    or receipt.get("target") != wake["registration"]["target"]):
                raise BridgeError("invalid_receipt", "wake receipt belongs to another registration")
            if disabled:
                if wake["state"] != "disable_pending":
                    raise BridgeError("invalid_state", "wake disable was not requested")
                wake.update(state="disabled", disable_receipt=receipt)
            elif program["state"] == "active" and wake["state"] != "disable_pending":
                wake.update(state="observed", tick_receipt=receipt)
            else:
                raise BridgeError("stale_epoch", "late tick cannot revive stopped wake")
            return self._put(actor, "wake", wake)

    def retry_job(self, actor: Principal, job_id: str, *, epoch: int,
                  expected_generation: int, reason: str, lifetime_seconds: int = 3600,
                  _check_provider: Callable | None = None) -> dict:
        actor.require("job.submit")
        if actor.role != "coordinator" or not reason:
            raise BridgeError("forbidden", "explicit coordinator retry reason required")
        with self._atomic():
            job = self._get(actor, "job", job_id)
            actor.require("job.submit", job["program_id"])
            program = self._active(actor, job["program_id"], epoch, "job.submit")
            old = self._get(actor, "attempt", job["current_attempt"])
            positive(lifetime_seconds, "lifetime_seconds", 28800 if old["strict_vm"] else 86400)
            if job["generation"] != expected_generation:
                raise BridgeError("stale_revision", "retry generation changed")
            # This reference has no external credential fencing implementation.
            if old["cleanup_state"] != "terminated":
                raise BridgeError("reconciliation_required", "prior compute must be terminated")
            if len(self._list(actor, "attempt", job["program_id"])) >= program["max_attempts"]:
                raise BridgeError("budget_exhausted", "program attempt budget exhausted")
            if _check_provider is not None:
                # A trusted service checks the immutable original requirements
                # inside this transaction, before any new attempt or launch intent.
                _check_provider(old["request"])
            attempt = {
                "id": uuid.uuid4().hex, "program_id": job["program_id"], "job_id": job_id,
                "generation": old["generation"] + 1, "owner_epoch": epoch,
                "request": old["request"], "input_digest": old["input_digest"],
                "launch_token": uuid.uuid4().hex, "state": "prepared", "retry_reason": reason,
                "cancel_requested": False, "strict_vm": old["strict_vm"],
                "cleanup_state": "pending", "provider_ids": {}, "artifacts": [],
                "hard_deadline": self.clock() + lifetime_seconds,
                "export_deadline": self.clock() + max(1, lifetime_seconds - 60),
            }
            self._put(actor, "attempt", attempt, new=True)
            job.update(current_attempt=attempt["id"], generation=attempt["generation"], state="pending")
            result = self._put(actor, "job", job)
            self._outbox(actor, "provider.launch", job["program_id"], {
                "attempt_id": attempt["id"], "launch_token": attempt["launch_token"],
                "input_digest": attempt["input_digest"], "owner_epoch": epoch,
            })
            return result

    def reconcile_lifecycle(self, actor: Principal) -> dict:
        actor.require("lifecycle.reconcile")
        expired = self.expire_leases(actor)
        deadline_attempts = []
        stopped = []
        with self._atomic():
            for attempt in self._list(actor, "attempt"):
                if (attempt["cleanup_state"] != "terminated" and not attempt["cancel_requested"]
                        and attempt["export_deadline"] <= self.clock()):
                    attempt.update(cancel_requested=True, deadline_reason="export_deadline_reached")
                    self._put(actor, "attempt", attempt)
                    self._outbox(actor, "provider.cancel", attempt["program_id"], {
                        "attempt_id": attempt["id"], "provider_ids": attempt["provider_ids"],
                        "launch_token": attempt["launch_token"], "reason": "export_deadline",
                    })
                    deadline_attempts.append(attempt["id"])
            for program in self._list(actor, "program"):
                if program["state"] != "stopping":
                    continue
                attempts = self._list(actor, "attempt", program["id"])
                effects = self._list(actor, "effect", program["id"])
                wakes = self._list(actor, "wake", program["id"])
                if (all(a["cleanup_state"] == "terminated" for a in attempts)
                        and all(a["state"] not in {"sent", "uncertain", "compensation_failed"}
                                for a in effects)
                        and all(w["state"] == "disabled" for w in wakes)):
                    program["state"] = "stopped"
                    self._put(actor, "program", program)
                    stopped.append(program["id"])
        return {"expired_leases": expired, "deadline_attempts": deadline_attempts, "stopped": stopped}
