"""Offline behavioral tests. Fake provider receipts never qualify a real host."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ADAPTER = Path(__file__).resolve().parents[1] / "codex"
sys.path.insert(0, str(ADAPTER))

from bridge import BridgeError, BridgeStore, Principal  # noqa: E402
from bridge.client import BridgeClient, HmacAuthenticator, HmacCredential, MAX_RESPONSE  # noqa: E402
from bridge.protocol import canonical, digest, identifier, positive  # noqa: E402
from bridge.service import BridgeService  # noqa: E402
from providers.base import ProviderRegistration, ProviderRegistry, ProviderUnavailable  # noqa: E402

SCOPES = frozenset({
    "capabilities", "grant.issue", "program.prepare", "program.activate", "program.inspect",
    "program.stop", "program.resume", "lease.renew", "job.submit", "job.inspect",
    "provider.observe", "event.ingest", "events.read", "effect.prepare", "effect.execute",
    "effect.reconcile", "outbox.dispatch", "artifact.publish", "artifact.read",
    "schedule.register", "lifecycle.reconcile",
})


class BridgeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 1000.0
        self.store = BridgeStore(self.root / "data.sqlite3", self.root / "artifacts", clock=lambda: self.now)
        self.actor = Principal("tenant", "project", "coordinator", SCOPES)
        self.operator = dataclasses.replace(self.actor, subject="human", role="operator")
        self.provider = dataclasses.replace(self.actor, subject="provider", role="provider")
        self.binding = {
            "schema_version": 1, "profile_id": "default", "profile_revision": "r1",
            "repository": "example/project", "payload_sha256": "a" * 64,
            "account_id": "account", "workspace_id": "workspace", "surface": "cloud",
            "binding_sha256": "b" * 64,
        }
        self.operations = ["program.run", "job.submit", "post_verdict", "schedule.register"]
        self.store.issue_grant(self.operator, "grant", repository="example/project",
                               operations=self.operations, expires_at=10000, detached=True,
                               targets=["source/thread"])

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def error(self, code, action, *args, **kwargs):
        with self.assertRaises(BridgeError) as context:
            action(*args, **kwargs)
        self.assertEqual(code, context.exception.code)

    def active(self, lifetime="interactive", max_attempts=20):
        preview = self.store.prepare_program(self.actor, "run", binding=self.binding,
                                             goal="prove behavior", lifetime=lifetime,
                                             max_attempts=max_attempts)
        return self.store.activate_program(self.actor, "run", grant_id="grant",
                                           expected_revision=preview["revision"])

    def job(self, key="source-1", **kwargs):
        return self.store.submit_job(self.actor, "run", epoch=1, business_key={"source": key},
                                     request={"brief": "inspect", "provider": "fake"},
                                     predicate={"revision": "head-a", "check": "regression"}, **kwargs)

    def launch(self, job):
        attempt = self.store.inspect_job(self.actor, job["id"])["attempt"]
        return self.store.record_launch(self.provider, attempt["id"],
                                        launch_token=attempt["launch_token"],
                                        provider_ids={"session": attempt["id"]},
                                        observation={"driver_version": "test-only"})

    def artifact(self, attempt):
        return self.store.publish_artifact(self.provider, attempt["id"], data=b"test evidence",
                                           source_revision="head-a", retain_until=10000)

    def termination(self, attempt, **changes):
        return {"state": "TERMINATED", "provider_ids": attempt["provider_ids"],
                "launch_token": attempt["launch_token"], **changes}

    def completion(self, job, attempt, outcome="completed"):
        receipt = {"terminal": True, "provider_ids": attempt["provider_ids"],
                   "predicate_sha256": digest(job["predicate"]),
                   "input_sha256": attempt["input_digest"]}
        return self.store.record_completion(self.provider, attempt["id"], root_turn_receipt=receipt,
                                            tested_revision="head-a", outcome=outcome)

    def effect(self):
        return self.store.prepare_effect(self.actor, "run", epoch=1, operation_id="effect1",
                                          operation="post_verdict", target="source/thread",
                                          expected_revision="message-1", intent={"text": "verdict"})

class KernelTests(BridgeFixture):
    def test_prepared_program_has_no_coordinator_stop_authority(self):
        self.store.prepare_program(self.actor, "run", binding=self.binding, goal="preview")
        self.error("forbidden", self.store.stop_program, self.actor, "run", epoch=0)
        self.assertEqual("stopping", self.store.stop_program(self.operator, "run", epoch=0)["state"])

    def test_request_idempotency_survives_restart_and_rejects_changed_content(self):
        calls = []
        def operation():
            calls.append(1)
            return self.store.prepare_program(self.actor, "run", binding=self.binding, goal="test")
        first = self.store.idempotent(self.actor, "req", {"goal": "test"}, operation)
        self.store.close()
        self.store = BridgeStore(self.root / "data.sqlite3", self.root / "artifacts", clock=lambda: self.now)
        again = self.store.idempotent(self.actor, "req", {"goal": "test"}, operation)
        self.assertEqual(first, again)
        self.assertEqual([1], calls)
        self.error("idempotency_conflict", self.store.idempotent, self.actor, "req", {}, operation)

    def test_failed_request_rolls_back_state_and_outbox(self):
        def fails():
            self.active()
            self.job()
            raise BridgeError("injected", "rollback")
        self.error("injected", self.store.idempotent, self.actor, "req", {}, fails)
        self.error("not_found", self.store.inspect_program, self.actor, "run")
        self.assertEqual([], self.store.pending_deliveries(self.actor))

    def test_concurrent_delivery_creates_one_logical_job(self):
        self.active()
        barrier = threading.Barrier(2)
        results = []
        failures = []
        def submit():
            store = BridgeStore(self.root / "data.sqlite3", self.root / "artifacts", clock=lambda: self.now)
            try:
                barrier.wait()
                results.append(store.submit_job(self.actor, "run", epoch=1, business_key={"source": "same"},
                                                request={"brief": "same"}, predicate={"revision": "head-a"}))
            except Exception as exc:
                failures.append(exc)
            finally:
                store.close()
        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual([], failures)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(1, len(self.store.pending_deliveries(self.actor)))

    def test_activation_and_grants_are_authority_not_profile_claims(self):
        preview = self.store.prepare_program(self.actor, "run", binding=self.binding, goal="test")
        self.error("stale_revision", self.store.activate_program, self.actor, "run", grant_id="grant", expected_revision=99)
        self.error("forbidden", self.store.issue_grant, self.actor, "bad", repository="example/project", operations=["program.run"], expires_at=2000)
        self.store.revoke_grant(self.operator, "grant")
        self.error("authority_expired", self.store.activate_program, self.actor, "run", grant_id="grant", expected_revision=preview["revision"])
        self.error("invalid_binding", self.store.prepare_program, self.actor, "other", binding={}, goal="test")

    def test_grant_repository_detached_scope_and_expiry(self):
        self.store.issue_grant(self.operator, "other", repository="wrong/repo", operations=self.operations, expires_at=2000)
        preview = self.store.prepare_program(self.actor, "run", binding=self.binding, goal="test")
        self.error("forbidden", self.store.activate_program, self.actor, "run", grant_id="other", expected_revision=preview["revision"])
        self.store.issue_grant(self.operator, "limited", repository="example/project", operations=["program.run"], expires_at=2000)
        p = self.store.activate_program(self.actor, "run", grant_id="limited", expected_revision=preview["revision"])
        self.error("forbidden", self.job)
        self.assertEqual(1, p["epoch"])
        self.store.prepare_program(self.actor, "detached", binding=self.binding, goal="test", lifetime="detached")
        self.error("forbidden", self.store.activate_program, self.actor, "detached", grant_id="limited", expected_revision=1)
        self.now = 2001
        self.error("authority_expired", self.store.activate_program, self.actor, "detached", grant_id="limited", expected_revision=1)

    def test_worker_cannot_borrow_coordinator_authority(self):
        self.active()
        job = self.job()
        worker = dataclasses.replace(self.actor, role="worker", subject="child",
                                     programs=frozenset({"run"}), jobs=frozenset({job["id"]}))
        self.assertEqual(job["id"], self.store.inspect_job(worker, job["id"])["job"]["id"])
        self.error("forbidden", self.store.renew_lease, worker, "run", epoch=1)
        self.error("forbidden", self.store.prepare_effect, worker, "run", epoch=1, operation_id="x", operation="post_verdict", target="source/thread", expected_revision="1", intent={"x": 1})
        self.error("forbidden", self.store.stop_program, worker, "run", epoch=1)
        self.error("forbidden", self.store.prepare_program, worker, "run", binding=self.binding, goal="test")
        self.error("forbidden", self.store.record_launch, worker, "missing", launch_token="x", provider_ids={}, observation={})
        self.error("forbidden", dataclasses.replace(worker, programs=frozenset()).require, "job.inspect", "run", job["id"])
        self.error("forbidden", worker.require, "job.inspect", "another", job["id"])
        self.error("forbidden", worker.require, "job.inspect", "run", "different-job")
        self.error("forbidden", dataclasses.replace(worker, scopes=frozenset()).require, "job.inspect")

    def test_lease_expiry_is_not_user_stop_and_resume_preserves_binding(self):
        self.active()
        self.now = 1040
        self.assertEqual(1160, self.store.renew_lease(self.actor, "run", epoch=1)["lease_until"])
        self.now = 1161
        self.error("lease_expired", self.job)
        self.assertEqual(["run"], self.store.expire_leases(self.actor))
        program = self.store.inspect_program(self.actor, "run")
        self.assertEqual("coordinator_lease_expired", program["stop_reason"])
        changed = {**self.binding, "profile_id": "work"}
        self.error("binding_mismatch", self.store.resume_program, self.actor, "run", binding=changed, expected_revision=program["revision"])
        resumed = self.store.resume_program(self.actor, "run", binding=self.binding, expected_revision=program["revision"])
        self.assertEqual(3, resumed["epoch"])
        self.error("stale_epoch", self.job)

    def test_detached_lifetime_requires_grant_and_no_heartbeat(self):
        self.active("detached")
        self.now = 5000
        self.assertEqual([], self.store.expire_leases(self.actor))
        self.error("invalid_state", self.store.renew_lease, self.actor, "run", epoch=1)
        self.job()

    def test_stop_fences_launch_and_requires_real_termination(self):
        self.active()
        job = self.job()
        delivery = self.store.pending_deliveries(self.actor)[0]
        stopped = self.store.stop_program(self.actor, "run", epoch=1)
        self.assertEqual("stopping", stopped["state"])
        self.error("stale_epoch", self.store.claim_delivery, self.actor, delivery["id"])
        late = self.launch(job)
        self.assertTrue(late["cancel_requested"])
        self.error("evidence_missing", self.store.observe_termination, self.provider, late["id"], receipt=self.termination(late))
        self.artifact(late)
        self.error("invalid_receipt", self.store.observe_termination, self.provider, late["id"], receipt={"state": "CANCEL_REQUESTED"})
        self.store.observe_termination(self.provider, late["id"], receipt=self.termination(late))
        self.assertEqual("stopped", self.store.inspect_program(self.actor, "run")["state"])
        self.error("stale_epoch", self.completion, job, late)

    def test_empty_stop_and_deadline_reconciliation(self):
        self.active("detached")
        job = self.job(lifetime_seconds=90, export_reserve_seconds=30)
        self.now = 1061
        result = self.store.reconcile_lifecycle(self.actor)
        self.assertEqual([job["current_attempt"]], result["deadline_attempts"])
        self.assertEqual([], self.store.reconcile_lifecycle(self.actor)["deadline_attempts"])
        self.error("deadline_exceeded", self.store.claim_delivery, self.actor, next(d["id"] for d in self.store.pending_deliveries(self.actor) if d["operation"] == "provider.launch"))
        self.store.prepare_program(self.actor, "empty", binding=self.binding, goal="test")
        self.store.activate_program(self.actor, "empty", grant_id="grant", expected_revision=1)
        self.store.stop_program(self.actor, "empty", epoch=1)
        self.assertEqual(["empty"], self.store.reconcile_lifecycle(self.actor)["stopped"])

    def test_business_key_excludes_config_and_changes_conflict(self):
        self.active(max_attempts=1)
        job = self.job()
        self.assertEqual(job, self.job())
        self.error("budget_exhausted", self.job, key="other")
        self.error("business_conflict", self.store.submit_job, self.actor, "run", epoch=1, business_key={"source": "source-1"}, request={"changed": True}, predicate={"revision": "head-a"})
        self.error("invalid_request", self.job, strict_vm=True, lifetime_seconds=28801)

    def test_provider_events_deduplicate_and_late_events_do_not_revive(self):
        self.active()
        job = self.job()
        args = dict(provider="fake", event_id="idle-1", payload={"status": "idle"}, program_id="run", attempt_id=job["current_attempt"])
        event = self.store.ingest_event(self.provider, **args)
        self.assertEqual("wake_hint", event["disposition"])
        self.assertEqual(event, self.store.ingest_event(self.provider, **args))
        self.error("idempotency_conflict", self.store.ingest_event, self.provider, **{**args, "payload": {"other": True}})
        self.store.stop_program(self.actor, "run", epoch=1)
        late = self.store.ingest_event(self.provider, **{**args, "event_id": "late"})
        self.assertEqual("stale_observation", late["disposition"])
        page = self.store.events(self.actor, "run", limit=1)
        self.assertTrue(page["has_more"])
        self.assertEqual(late["id"], self.store.events(self.actor, "run", after=page["next_cursor"])["events"][0]["id"])
        self.error("invalid_request", self.store.events, self.actor, "run", after="invalid")

    def test_uncertain_effect_is_never_replayed_and_blocks_resume(self):
        self.active()
        effect = self.effect()
        self.assertEqual(effect, self.effect())
        sent = self.store.begin_effect(self.actor, effect["id"], epoch=1)
        self.error("reconciliation_required", self.store.begin_effect, self.actor, effect["id"], epoch=1)
        self.store.reconcile_effect(self.provider, effect["id"], outcome="uncertain", correlation_token=sent["correlation_token"], receipt={"timeout": True, "target": "source/thread"})
        paused = self.store.stop_program(self.actor, "run", epoch=1, pause=True)
        self.error("reconciliation_required", self.store.resume_program, self.actor, "run", binding=self.binding, expected_revision=paused["revision"])
        self.store.reconcile_effect(self.provider, effect["id"], outcome="confirmed", correlation_token=sent["correlation_token"], receipt={"remote_id": "actual", "target": "source/thread"})
        resumed = self.store.resume_program(self.actor, "run", binding=self.binding, expected_revision=paused["revision"])
        self.assertEqual(3, resumed["epoch"])
        self.error("stale_epoch", self.store.begin_effect, self.actor, effect["id"], epoch=3)

    def test_effect_target_revision_key_and_readback_identity(self):
        self.active()
        self.error("forbidden", self.store.prepare_effect, self.actor, "run", epoch=1, operation_id="e", operation="post_verdict", target="wrong/thread", expected_revision="1", intent={"a": 1})
        effect = self.effect()
        self.error("idempotency_conflict", self.store.prepare_effect, self.actor, "run", epoch=1, operation_id="effect1", operation="post_verdict", target="source/thread", expected_revision="1", intent={"changed": 1})
        self.store.begin_effect(self.actor, effect["id"], epoch=1)
        self.error("invalid_receipt", self.store.reconcile_effect, self.provider, effect["id"], outcome="confirmed", correlation_token="wrong", receipt={"id": "one", "target": "source/thread"})
        args = dict(outcome="confirmed", correlation_token=effect["correlation_token"], receipt={"id": "one", "target": "source/thread"})
        first = self.store.reconcile_effect(self.provider, effect["id"], **args)
        self.assertEqual(first, self.store.reconcile_effect(self.provider, effect["id"], **args))
        self.error("invalid_state", self.store.reconcile_effect, self.provider, effect["id"], **{**args, "receipt": {"id": "two", "target": "source/thread"}})

    def test_outbox_does_not_replay_unknown_delivery(self):
        self.active()
        self.job()
        delivery = self.store.pending_deliveries(self.actor)[0]
        claimed = self.store.claim_delivery(self.actor, delivery["id"])
        self.assertEqual("claimed", claimed["state"])
        self.error("reconciliation_required", self.store.claim_delivery, self.actor, delivery["id"])
        self.store.reconcile_delivery(self.actor, delivery["id"], outcome="uncertain", receipt={"timeout": True})
        self.assertEqual([], self.store.pending_deliveries(self.actor))
        result = self.store.reconcile_delivery(self.actor, delivery["id"], outcome="confirmed", receipt={"id": "provider-operation"})
        self.assertEqual("confirmed", result["state"])
        self.error("invalid_state", self.store.reconcile_delivery, self.actor, delivery["id"], outcome="confirmed", receipt={"id": "other"})

    def test_revision_bound_completion_exports_before_termination(self):
        self.active()
        job = self.job()
        attempt = self.launch(job)
        self.error("evidence_missing", self.completion, job, attempt)
        artifact = self.artifact(attempt)
        self.assertEqual(b"test evidence", self.store.read_artifact(self.actor, artifact["id"]))
        finishing = self.completion(job, attempt, "model_violation")
        self.assertEqual("finishing", finishing["state"])
        self.assertEqual(finishing, self.completion(job, attempt, "model_violation"))
        self.error("conflict", self.completion, job, attempt, "completed")
        self.assertEqual("pending", self.store.inspect_job(self.actor, job["id"])["job"]["state"])
        completed = self.store.observe_termination(self.provider, attempt["id"], receipt=self.termination(attempt))
        self.assertEqual("model_violation", completed["state"])
        self.assertEqual("model_violation", self.store.inspect_job(self.actor, job["id"])["job"]["state"])
        self.error("invalid_state", self.artifact, attempt)

    def test_artifact_tamper_retention_and_scope(self):
        self.active()
        job = self.job()
        attempt = self.launch(job)
        artifact = self.artifact(attempt)
        self.assertEqual(artifact["sha256"], self.artifact(attempt)["sha256"])
        other = dataclasses.replace(self.actor, project="another")
        self.error("not_found", self.store.read_artifact, other, artifact["id"])
        path = self.root / "artifacts" / artifact["sha256"]
        path.write_bytes(b"tamper")
        self.error("integrity_failure", self.store.read_artifact, self.actor, artifact["id"])
        self.error("integrity_failure", self.artifact, attempt)
        self.now = 10001
        self.error("expired", self.store.read_artifact, self.actor, artifact["id"])

    def test_retry_preserves_job_identity_and_fences_old_generation(self):
        self.active()
        job = self.job()
        attempt = self.launch(job)
        self.error("reconciliation_required", self.store.retry_job, self.actor, job["id"], epoch=1, expected_generation=1, reason="retry")
        self.artifact(attempt)
        self.completion(job, attempt, "failed")
        self.store.observe_termination(self.provider, attempt["id"], receipt=self.termination(attempt))
        retried = self.store.retry_job(self.actor, job["id"], epoch=1, expected_generation=1, reason="same regression")
        self.assertEqual(job["id"], retried["id"])
        self.assertEqual(2, retried["generation"])
        self.assertNotEqual(job["current_attempt"], retried["current_attempt"])
        self.error("stale_revision", self.store.retry_job, self.actor, job["id"], epoch=1, expected_generation=1, reason="retry")
        self.error("stale_epoch", self.completion, job, attempt)

    def test_wake_registration_is_not_successful_tick_and_stop_disables(self):
        self.active("detached")
        registration = {"provider": "fake", "provider_id": "schedule", "target": "run", "timezone": "UTC", "next_at": 1100, "readback": {"state": "enabled"}}
        wake = self.store.register_wake(self.actor, "run", epoch=1, wake_id="wake", registration=registration)
        self.assertEqual("registered_unobserved", wake["state"])
        self.assertEqual("observed", self.store.observe_wake(self.provider, "wake", receipt={"tick": "event-1", "provider_id": "schedule", "target": "run"})["state"])
        self.store.stop_program(self.actor, "run", epoch=1)
        self.error("stale_epoch", self.store.observe_wake, self.provider, "wake", receipt={"tick": "late", "provider_id": "schedule", "target": "run"})
        self.assertEqual([], self.store.reconcile_lifecycle(self.actor)["stopped"])
        self.store.observe_wake(self.provider, "wake", receipt={"state": "disabled", "provider_id": "schedule", "target": "run"}, disabled=True)
        self.assertEqual(["run"], self.store.reconcile_lifecycle(self.actor)["stopped"])

    def test_corrupt_schema_and_storage_symlinks_fail(self):
        self.store.db.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
        self.error("schema_mismatch", BridgeStore, self.root / "data.sqlite3", self.root / "artifacts")
        symlink = self.root / "link"
        symlink.symlink_to(self.root / "data.sqlite3")
        self.error("invalid_storage", BridgeStore, symlink, self.root / "artifacts")


class ReceiptAndOwnershipTests(BridgeFixture):
    def test_other_resource_cannot_complete_termination_and_terminal_receipts_are_immutable(self):
        self.active()
        job = self.job()
        attempt = self.launch(job)
        self.artifact(attempt)
        self.completion(job, attempt)
        self.error("invalid_receipt", self.store.observe_termination, self.provider, attempt["id"],
                   receipt=self.termination(attempt, provider_ids={"session": "some-other-attempt"}))
        receipt = self.termination(attempt)
        terminal = self.store.observe_termination(self.provider, attempt["id"], receipt=receipt)
        self.assertEqual(terminal, self.store.observe_termination(self.provider, attempt["id"], receipt=receipt))
        self.error("conflict", self.store.observe_termination, self.provider, attempt["id"],
                   receipt={**receipt, "contradictory": True})
        self.assertEqual(terminal, self.completion(job, attempt))
        self.error("conflict", self.completion, job, attempt, "failed")
        self.assertEqual("completed", self.store.inspect_job(self.actor, job["id"])["attempt"]["state"])

    def test_observable_epoch_cannot_replace_authenticated_coordinator(self):
        self.store.issue_grant(self.operator, "transfer", repository="example/project",
                               operations=self.operations + ["program.transfer"], expires_at=10000)
        self.store.prepare_program(self.actor, "run", binding=self.binding, goal="test")
        self.store.activate_program(self.actor, "run", grant_id="transfer", expected_revision=1)
        other = dataclasses.replace(self.actor, subject="replacement-coordinator")
        self.error("forbidden", self.store.submit_job, other, "run", epoch=1,
                   business_key={"source": "key"}, request={"brief": "work"}, predicate={"revision": "head"})
        self.error("forbidden", self.store.prepare_effect, other, "run", epoch=1,
                   operation_id="effect", operation="post_verdict", target="source/thread",
                   expected_revision="head", intent={"message": "text"})
        paused = self.store.stop_program(self.actor, "run", epoch=1, pause=True)
        self.error("forbidden", self.store.resume_program, other, "run", binding=self.binding,
                   expected_revision=paused["revision"])
        resumed = self.store.resume_program(other, "run", binding=self.binding,
                                           expected_revision=paused["revision"], take_ownership=True)
        self.error("forbidden", self.store.submit_job, self.actor, "run", epoch=resumed["epoch"],
                   business_key={"source": "key"}, request={"brief": "work"}, predicate={"revision": "head"})
        for pause in (False, True):
            self.error("forbidden", self.store.stop_program, self.actor, "run",
                       epoch=resumed["epoch"], pause=pause)
        self.error("forbidden", self.store.stop_program, self.provider, "run",
                   epoch=resumed["epoch"])
        stopped = self.store.stop_program(self.operator, "run", epoch=resumed["epoch"])
        self.assertEqual(stopped["state"], "stopping")


class TransportTests(BridgeFixture):
    def setUp(self):
        super().setUp()
        self.key = HmacCredential("local", b"k" * 32)
        self.auth = HmacAuthenticator({"local": (self.key.key, self.actor)}, clock=lambda: self.now)
        self.service = BridgeService(self.store, self.auth.authenticate)
        self.calls = []
        def transport(url, body, headers, timeout):
            self.calls.append((url, body, headers, timeout))
            return self.service.handle(body, headers)
        self.client = BridgeClient("https://bridge.example", tenant="tenant", project="project",
                                    authenticate=self.key.headers, transport=transport, clock=lambda: self.now)

    def test_authenticated_client_fails_closed_on_missing_providers(self):
        result = self.client.negotiate(required_operations={"program.prepare"})
        self.assertFalse(result["native_cloud_history"])
        self.assertFalse(result["deployment_certified"])
        self.error("unavailable", self.client.negotiate, required_provider_capabilities={"execution"})
        self.error("unavailable", self.client.call, "job.submit", {})
        self.assertEqual("https://bridge.example/v1/operations", self.calls[0][0])
        self.error("unavailable", self.client.call, "native.history", {})

    def test_round_trip_replay_and_changed_payload(self):
        args = {"program_id": "run", "binding": self.binding, "goal": "test"}
        first = self.client.call("program.prepare", args, request_id="same")
        self.assertEqual(first, self.client.call("program.prepare", args, request_id="same"))
        self.error("idempotency_conflict", self.client.call, "program.prepare", {**args, "goal": "other"}, request_id="same")
        self.error("invalid_request", self.client.call, "program.prepare", {"nonsense": 1})

    def test_signed_request_tampering_and_expiry(self):
        self.client.call("capabilities", {})
        _, body, headers, _ = self.calls[-1]
        self.error("unauthenticated", self.service.handle, body + b" ", headers)
        self.now += 301
        self.error("unauthenticated", self.service.handle, body, headers)
        self.error("unauthenticated", self.auth.authenticate, {"X-Pstack-Time": "bad"}, body)
        other = json.loads(body)
        other["tenant"] = "other"
        altered = canonical(other)
        self.error("forbidden", self.service.handle, altered, self.key.headers(altered, int(self.now)))

    def test_response_mismatch_and_no_automatic_retry(self):
        count = []
        def lost(*args):
            count.append(1)
            raise BridgeError("transport_unknown", "lost ack")
        self.client.transport = lost
        self.error("transport_unknown", self.client.call, "program.prepare", {}, request_id="recover-this")
        self.assertEqual([1], count)
        self.client.transport = lambda *args: b'{"request_id":"different"}'
        self.error("integrity_failure", self.client.call, "capabilities", {})
        self.client.transport = lambda *args: b"not json"
        self.error("invalid_response", self.client.call, "capabilities", {})
        self.client.transport = lambda *args: b"x" * (MAX_RESPONSE + 1)
        self.error("response_too_large", self.client.call, "capabilities", {})

    def test_bad_endpoint_and_protocol_cannot_leak_credentials(self):
        for endpoint in ["http://example.test", "https://secret@example.test", "https://example.test/path", "https://example.test?token=secret"]:
            self.error("invalid_endpoint", BridgeClient, endpoint, tenant="t", project="p", authenticate=self.key.headers)
        self.client.authenticate = lambda *args: {"Authorization": "bad\nheader"}
        self.error("invalid_credentials", self.client.call, "capabilities", {})
        with self.assertRaises(ValueError):
            HmacCredential("key", b"short")
        with self.assertRaises(ValueError):
            HmacAuthenticator({"key": (b"short", self.actor)})
        self.error("invalid_request", identifier, "../path")
        self.error("invalid_request", positive, True, "count", 5)

    def test_registry_requires_explicit_qualification_and_no_history_claim(self):
        registry = ProviderRegistry()
        with self.assertRaises(ProviderUnavailable):
            registry.require("missing", {"execution"})
        with self.assertRaises(ValueError):
            registry.register("fake", ProviderRegistration(object(), "", frozenset(), ""))
        with self.assertRaises(ValueError):
            registry.register("fake", ProviderRegistration(object(), "1", frozenset({"native_cloud_history"}), "test-only"))
        registration = ProviderRegistration(object(), "1", frozenset({"execution"}), "offline-test-only")
        registry.register("fake", registration)
        self.assertEqual(registration, registry.require("fake", {"execution"}))
        with self.assertRaises(ValueError):
            registry.register("fake", registration)
        self.assertFalse(registry.capabilities()["native_cloud_history"])
        self.service.providers = registry
        self.assertIn("job.submit", self.client.negotiate(required_provider_capabilities={"execution"})["operations"])
        self.active()
        result = self.client.call("job.submit", {"program_id": "run", "epoch": 1,
                                                "business_key": {"source": "test"},
                                                "request": {"provider": "fake"},
                                                "predicate": {"revision": "head-a"}})
        self.assertEqual("pending", result["state"])
        self.error("unavailable", self.client.call, "job.submit", {"request": {"provider": "unknown"}})

    def test_retry_requires_original_provider_and_capabilities_before_launch(self):
        self.active()
        original = {"provider": "selected", "required_capabilities": ["audit"]}
        job = self.store.submit_job(self.actor, "run", epoch=1,
                                   business_key={"source": "retry"}, request=original,
                                   predicate={"revision": "head-a"})
        attempt = self.launch(job)
        self.artifact(attempt)
        self.completion(job, attempt, "failed")
        self.store.observe_termination(self.provider, attempt["id"], receipt=self.termination(attempt))
        before = self.store.pending_deliveries(self.actor)
        for caps in (None, {"execution"}):
            registry = ProviderRegistry()
            registry.register("other", ProviderRegistration(object(), "1", frozenset({"execution", "audit"}), "offline"))
            if caps is not None:
                registry.register("selected", ProviderRegistration(object(), "1", frozenset(caps), "offline"))
            self.service.providers = registry
            self.error("unavailable", self.client.call, "job.retry", {
                "job_id": job["id"], "epoch": 1, "expected_generation": 1, "reason": "explicit retry",
            })
            self.assertEqual(1, self.store.inspect_job(self.actor, job["id"])["job"]["generation"])
            self.assertEqual(before, self.store.pending_deliveries(self.actor))
        registry = ProviderRegistry()
        registry.register("selected", ProviderRegistration(object(), "1", frozenset({"execution", "audit"}), "offline"))
        self.service.providers = registry
        retried = self.client.call("job.retry", {
            "job_id": job["id"], "epoch": 1, "expected_generation": 1, "reason": "explicit retry",
        })
        self.assertEqual(2, retried["generation"])
        self.assertEqual(original, self.store.inspect_job(self.actor, job["id"])["attempt"]["request"])


if __name__ == "__main__":
    unittest.main()


class AnthropicDriverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from types import SimpleNamespace
        from providers import anthropic_worker
        self.module = anthropic_worker
        self.NS = SimpleNamespace
        self.options = None
        self.init_changes = {}
        self.result_changes = {}
        self.effective_effort = "high"
        self.assistant_model = "canonical-model"
        self.active = True
        self.supported = True
        self.request = {
            "role": "audit", "prompt": "Review these supplied original records.",
            "model": "model-alias", "effort": "high", "max_turns": 5,
            "max_budget_usd": 1.0, "output_schema": {"type": "object"},
        }
        owner = self
        class System:
            def __init__(self, subtype, data):
                self.subtype, self.data = subtype, data
        class Assistant:
            def __init__(self):
                self.model, self.error = owner.assistant_model, None
        class Result:
            def __init__(self):
                self.subtype = "success"
                self.is_error = False
                self.session_id = owner.options.session_id
                self.terminal_reason = "completed"
                self.permission_denials = []
                self.total_cost_usd = 0.1
                self.usage = {"output_tokens": 20}
                self.model_usage = {"canonical-model": {"outputTokens": 20}}
                self.structured_output = {"verdict": "verified"}
                self.__dict__.update(owner.result_changes)
        class Client:
            def __init__(self, options):
                owner.options = options
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def query(self, prompt):
                owner.assertEqual(owner.request["prompt"], prompt)
            async def receive_response(self):
                init = {"session_id": owner.options.session_id, "apiKeySource": "ANTHROPIC_API_KEY",
                        "model": "canonical-model", "tools": owner.options.allowed_tools,
                        "skills": [], "plugins": [], "claude_code_version": "test-cli",
                        "fast_mode_state": "on"}
                init.update(owner.init_changes)
                yield System("init", init)
                yield Assistant()
                hook = owner.options.hooks["Stop"][0].hooks[0]
                await hook({"hook_event_name": "Stop", "effort": {"level": owner.effective_effort}}, None, {})
                yield Result()
        def model_info(name):
            support = SimpleNamespace(supported=owner.supported)
            effort = SimpleNamespace(supported=True, low=support, medium=support, high=support, xhigh=support)
            return SimpleNamespace(id="wrong-model" if name == "wrong-model" else "canonical-model",
                                   lifecycle="active" if owner.active else "retired",
                                   capabilities=SimpleNamespace(effort=effort))
        self.catalog = SimpleNamespace(models=SimpleNamespace(retrieve=model_info))
        self.sdk = SimpleNamespace(ClaudeSDKClient=Client, ClaudeAgentOptions=SimpleNamespace,
                                   HookMatcher=SimpleNamespace, SystemMessage=System,
                                   AssistantMessage=Assistant, ResultMessage=Result,
                                   create_sdk_mcp_server=lambda **kwargs: kwargs)
        self.schema_calls = []

    async def run_driver(self, **kwargs):
        return await self.module.execute_sdk_job(
            self.request, sdk=self.sdk, catalog=self.catalog, cwd=Path("/trusted/empty-driver"),
            validate_result=lambda value, schema: self.schema_calls.append((value, schema)), **kwargs)

    async def test_success_records_actual_provider_metadata_and_disables_ambient_context(self):
        result = await self.run_driver()
        self.assertEqual(["canonical-model"], result["observed_models"])
        self.assertEqual("anthropic", result["originating_vendor"])
        self.assertEqual(["high"], result["observed_effort"])
        self.assertFalse(result["native_cloud_history"])
        self.assertEqual([], self.options.tools)
        self.assertEqual([], self.options.skills)
        self.assertEqual([], self.options.setting_sources)
        self.assertEqual({}, self.options.mcp_servers)
        self.assertTrue(self.options.strict_mcp_config)
        self.assertIsNone(self.options.resume)
        self.assertIsNone(self.options.fallback_model)
        self.assertEqual(1, len(self.schema_calls))
        first_session = result["session_id"]
        self.assertNotEqual(first_session, (await self.run_driver())["session_id"])

    async def test_requested_identity_does_not_override_actual_model_or_effort(self):
        self.assistant_model = "wrong-model"
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        self.assistant_model = "canonical-model"
        self.effective_effort = "medium"
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        self.effective_effort = None
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()

    async def test_catalog_retirement_unsupported_effort_and_fast_requirements(self):
        self.active = False
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        self.active, self.supported = True, False
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        self.supported = True
        self.request["require_fast"] = True
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        self.init_changes["fast_mode_state"] = "off"
        with self.assertRaises(self.module.DriverError):
            await self.run_driver(verified_fast_settings={"test-qualified-only": True})
        self.init_changes["fast_mode_state"] = "on"
        self.assertEqual("completed", (await self.run_driver(verified_fast_settings={"test-qualified-only": True}))["state"])

    async def test_ambient_tools_login_credentials_or_other_session_fail(self):
        for change in [{"tools": ["Bash"]}, {"skills": ["ambient"]},
                       {"plugins": ["ambient"]}, {"apiKeySource": "/login managed key"},
                       {"session_id": "other"}]:
            self.init_changes = change
            with self.assertRaises(self.module.DriverError):
                await self.run_driver()

    async def test_success_subtype_with_error_budget_denial_or_cancel_is_incomplete(self):
        for change in [{"is_error": True}, {"subtype": "error_max_budget_usd"},
                       {"terminal_reason": "aborted_streaming"}, {"permission_denials": ["blocked"]},
                       {"total_cost_usd": None}, {"total_cost_usd": 1.1}, {"session_id": "other"}]:
            self.result_changes = change
            with self.assertRaises(self.module.DriverError):
                await self.run_driver()

    async def test_tool_required_job_does_not_become_easier_tool_free_run(self):
        self.request["requires_task_tools"] = True
        with self.assertRaises(self.module.DriverError):
            await self.run_driver()
        result = await self.run_driver(broker_tools=[self.NS(name="read")])
        self.assertEqual("completed", result["state"])
        self.assertEqual(["mcp__task__read"], self.options.allowed_tools)
        callback = self.options.hooks["PreToolUse"][0].hooks[0]
        denied = await callback({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, None, {})
        self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])

    def test_job_cannot_override_process_authority_or_external_schema(self):
        for change in [{"role": "pr-verifier"}, {"effort": "max"}, {"env": {}},
                       {"model": ""}, {"prompt": ""}, {"max_turns": True},
                       {"max_budget_usd": float("inf")}, {"output_schema": {"$ref": "https://remote/schema"}},
                       {"output_schema": {"$dynamicRef": "https://remote/schema"}},
                       {"output_schema": {"properties": {"item": {"$recursiveRef": "remote.json"}}}},
                       {"output_schema": {"$ref": None}}]:
            with self.assertRaises(self.module.DriverError):
                self.module.validate_request({**self.request, **change})
        env = self.module.isolated_environment("provider-key", Path("/private/home"), Path("/adapter"))
        self.assertEqual({"PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "ANTHROPIC_API_KEY"}, set(env))
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        with self.assertRaises(self.module.DriverError):
            self.module.isolated_environment("bad\nkey", Path("/home"), Path("/adapter"))

    def test_result_schema_uses_only_local_references_even_without_preflight(self):
        from unittest import mock
        from jsonschema.exceptions import ValidationError
        schema = {"$defs": {"result": {"type": "integer"}}, "$ref": "#/$defs/result"}
        self.module.validate_structured_result(3, schema)
        with self.assertRaises(ValidationError):
            self.module.validate_structured_result("not an integer", schema)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network attempted")) as network:
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                schema = {"$schema": "https://json-schema.org/draft/2019-09/schema" if keyword == "$recursiveRef"
                          else "https://json-schema.org/draft/2020-12/schema",
                          keyword: "https://unconfigured.example/schema"}
                if keyword == "$recursiveRef":
                    # 2019-09 only recognizes its local recursive anchor form;
                    # request preflight rejects this nonlocal form regardless.
                    with self.assertRaises(self.module.DriverError):
                        self.module.validate_request({**self.request, "output_schema": schema})
                else:
                    with self.assertRaises(Exception) as rejected:
                        self.module.validate_structured_result({}, schema)
                    self.assertNotIsInstance(rejected.exception, AssertionError)
            network.assert_not_called()

    async def test_scoped_tools_require_bound_receipts_and_no_direct_host_access(self):
        from providers.scoped_tools import make_remote_tools
        class SDK:
            def tool(self, name, description, schema):
                def decorator(callback):
                    return self.NS(name=name, callback=callback)
                return decorator
        sdk = SDK()
        sdk.NS = self.NS
        calls = []
        def call(operation, payload):
            calls.append((operation, payload))
            return {**payload, "state": "completed", "receipt_id": "remote-original-1"}
        client = self.NS(call=call)
        tools = make_remote_tools(sdk, client=client, job_id="job", epoch=2, contract_sha256="a" * 64,
                                  schemas={"read": {"path": str}}, allowed=frozenset({"read"}))
        result = await tools[0].callback({"path": "src/file.py"})
        self.assertFalse(result["isError"])
        self.assertEqual("worker.operation", calls[0][0])
        self.assertEqual(2, calls[0][1]["epoch"])
        client.call = lambda *args: {"job_id": "another-job"}
        with self.assertRaises(self.module.DriverError):
            await tools[0].callback({"path": "file"})
        with self.assertRaises(self.module.DriverError):
            make_remote_tools(sdk, client=client, job_id="job", epoch=2, contract_sha256="x",
                              schemas={}, allowed=frozenset({"environment"}))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux subreaper qualification")
class DriverSupervisorTests(unittest.TestCase):
    def setUp(self):
        from providers import anthropic_worker
        self.module = anthropic_worker
        self.request = {"role": "audit", "prompt": "review", "model": "explicit-model",
                        "effort": "high", "max_turns": 2, "max_budget_usd": 1,
                        "output_schema": {"type": "object"}}

    def run_child(self, script, **kwargs):
        from unittest import mock
        real_popen = self.module.subprocess.Popen
        def fake_driver(command, **options):
            prefix = [sys.executable, "-m", "providers.process_supervisor", "--"]
            self.assertEqual(prefix + [sys.executable, "-m", "providers.anthropic_worker"], command)
            self.assertEqual("offline-test-key", options["env"]["ANTHROPIC_API_KEY"])
            self.assertNotIn("AWS_ACCESS_KEY_ID", options["env"])
            return real_popen(prefix + [sys.executable, "-c", script], **options)
        with mock.patch.object(self.module.subprocess, "Popen", side_effect=fake_driver):
            return self.module.run_isolated(self.request, credential="offline-test-key", **kwargs)

    def test_supervisor_bounds_owned_child_and_sanitizes_environment(self):
        result = self.run_child("import sys; sys.stdin.buffer.read(); print('{\"state\":\"completed\"}')")
        self.assertEqual("completed", result["state"])
        with self.assertRaises(self.module.DriverError):
            self.run_child("import sys; sys.stdin.buffer.read(); sys.exit(1)")
        with self.assertRaises(self.module.DriverError):
            self.run_child("import sys; sys.stdin.buffer.read(); print('{\"state\":\"incomplete\"}')")
        with self.assertRaises(self.module.DriverError):
            self.run_child("import sys; sys.stdin.buffer.read(); print('not JSON')")
        with self.assertRaises(self.module.DriverError):
            self.run_child("import time; time.sleep(3)", timeout_seconds=0.05)
        with self.assertRaises(self.module.DriverError):
            self.run_child("import sys; sys.stdin.buffer.read(); print('x' * (3 * 1024 * 1024))")
        with self.assertRaises(self.module.DriverError):
            self.module.run_isolated(self.request, credential="test", timeout_seconds=0)
        with self.assertRaises(self.module.DriverError):
            self.module.run_isolated({**self.request, "context": "x" * self.module.MAX_OUTPUT}, credential="test")


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux subreaper qualification")
class ProcessSupervisorTests(unittest.TestCase):
    def run_command(self, script, *, terminate=False):
        import os
        import signal
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = [sys.executable, str(ADAPTER / "providers" / "process_supervisor.py"), "--",
                       sys.executable, "-c", script, str(directory)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, start_new_session=True)
            try:
                if terminate:
                    deadline = time.monotonic() + 5
                    while not (directory / "ready").exists() and process.poll() is None:
                        if time.monotonic() >= deadline:
                            self.fail("test child did not become ready")
                        time.sleep(0.005)
                    process.terminate()
                output, error = process.communicate(timeout=5)
                for path in directory.glob("pid-*"):
                    pid = int(path.read_text())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                    self.assertFalse(Path(f"/proc/{pid}").exists())
                self.assertEqual("", error)
                return process.returncode, output
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for path in directory.glob("pid-*"):
                    try:
                        os.kill(int(path.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.stdout.close()
                process.stderr.close()

    def test_preserves_command_exit_status_and_output(self):
        code, output = self.run_command("print('original output', flush=True); raise SystemExit(23)")
        self.assertEqual((23, "original output\n"), (code, output))
        self.assertEqual((137, ""), self.run_command("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"))

    def test_invalid_command_has_a_bounded_generic_failure(self):
        import subprocess
        for command in ([], ["/pstack-nonexistent-command"]):
            result = subprocess.run(
                [sys.executable, str(ADAPTER / "providers" / "process_supervisor.py"), "--", *command],
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(125, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertEqual("pstack process supervision failed; cleanup is unverified\n", result.stderr)

    def test_reaps_orphans_while_root_is_alive(self):
        script = """
import os, pathlib, sys, time
directory = pathlib.Path(sys.argv[1])
child = os.fork()
if child == 0:
    grandchild = os.fork()
    if grandchild == 0:
        directory.joinpath('pid-orphan').write_text(str(os.getpid()))
    os._exit(0)
os.waitpid(child, 0)
deadline = time.monotonic() + 3
while not directory.joinpath('pid-orphan').exists() or not directory.joinpath('pid-orphan').read_text():
    if time.monotonic() > deadline: raise SystemExit(1)
    time.sleep(.005)
pid = int(directory.joinpath('pid-orphan').read_text())
while pathlib.Path('/proc/' + str(pid)).exists():
    if time.monotonic() > deadline: raise SystemExit(2)
    time.sleep(.005)
print('reaped while alive', flush=True)
"""
        self.assertEqual((0, "reaped while alive\n"), self.run_command(script))

    def test_terminates_detached_descendants_after_root_exit_or_signal(self):
        script = """
import os, pathlib, signal, sys, time
directory = pathlib.Path(sys.argv[1])
child = os.fork()
if child == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    directory.joinpath('pid-detached').write_text(str(os.getpid()))
    grandchild = os.fork()
    if grandchild == 0:
        directory.joinpath('pid-grandchild').write_text(str(os.getpid()))
    while True: time.sleep(1)
deadline = time.monotonic() + 3
while not directory.joinpath('pid-grandchild').exists():
    if time.monotonic() > deadline: raise SystemExit(1)
    time.sleep(.005)
directory.joinpath('ready').touch()
"""
        self.assertEqual((7, ""), self.run_command(script + "\nraise SystemExit(7)"))
        self.assertEqual((143, ""), self.run_command(script + "\nwhile True: time.sleep(1)", terminate=True))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux subreaper qualification")
class DriverGroupTests(unittest.TestCase):
    def test_dead_leader_cannot_leave_a_live_descendant(self):
        import os
        import signal
        import subprocess
        from unittest import mock
        from providers import anthropic_worker as driver
        request = {"role": "audit", "prompt": "review", "model": "model", "effort": "high",
                   "max_turns": 2, "max_budget_usd": 1, "output_schema": {"type": "object"}}
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "child-pid"
            script = (
                "import subprocess,os,pathlib; "
                "child=subprocess.Popen(['/bin/sleep','20']); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); os._exit(1)"
            )
            actual = subprocess.Popen
            def launch(command, **options):
                return actual(command[:4] + [sys.executable, "-c", script], **options)
            child_pid = None
            try:
                with mock.patch.object(driver.subprocess, "Popen", side_effect=launch):
                    with self.assertRaises(driver.DriverError):
                        driver.run_isolated(request, credential="offline-key", timeout_seconds=2)
                child_pid = int(pid_file.read_text())
                # The dedicated subreaper must remove the orphan completely,
                # even when this container's PID1 would leave it as a zombie.
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
                self.assertFalse(Path(f"/proc/{child_pid}").exists())
            finally:
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
