# Shared Codex bridge implementation

This directory implements the protocol client, authenticated local dispatcher and durable
reference state kernel used by the one Codex payload. It does not deploy a service or
claim a native Codex capability. Canonical pstack and the upstream Claude target are
unmodified.

`BridgeStore` uses Python 3.11 and SQLite with full synchronization, conditional record
revisions and immediate write transactions. It is a single-machine reference backend.
The reviewed AWS reference deployment still needs an implementation of the same
transaction/epoch invariants in DynamoDB, authenticated ingress, durable worker delivery,
S3 exports and provider supervision. A local database is not durable off-host storage or
a second proposed production control plane.

## Implemented behavior

- Concrete operator grants bind repository, operations, external targets, expiry and
  detached authority. An authentication scope and an operator grant are both required.
- Program preparation and activation are separate. Programs pin the complete runtime
  binding, goal, profile/account/payload identity and attempt budget. An unknown or edited
  binding cannot silently resume an old run.
- Coordinator identity and ownership epoch both fence new work. A replacement coordinator
  needs explicit transfer intent and `program.transfer` authority. An observable epoch
  alone never authenticates its caller. Stop requires the current coordinator or an
  operator with explicit stop scope; the prior owner cannot stop its replacement. A
  prepared program has no coordinator owner, so only an operator can stop that preview.
- Stable business keys deduplicate jobs independently of configuration changes. Attempts
  have monotonic generations, immutable inputs, launch tokens persisted before dispatch,
  export and hard deadlines, provider observations and semantic result state.
- Transactional outbox records are committed with their originating state changes.
  Claimed or uncertain deliveries are not automatically requeued. Retry after provider
  readback is an explicit service operation. A delivery notification is only an inspect
  hint, never proof that a job finished.
- External effects record exact intent, target and expected revision before sending.
  Uncertain acknowledgements require provider readback. A stopped program may record a
  real in-flight effect's later outcome, but that observation restores no authority.
- Artifact content is digest addressed in a private store. Receipts bind producer, attempt,
  revision and retention. Completion checks input/predicate/provider identity and exported
  evidence. Cleanup needs the actual provider IDs and launch token in a terminal receipt.
  Contradictory post-terminal observations cannot reopen completed work.
- Explicit stop, interactive lease expiry and detached lifetime remain distinct. Expiry
  fences work but does not claim the user pressed Stop. A deadline requests cancellation;
  it does not certify provider termination. No background coordinator heartbeat is started.
- Scheduled registration remains `registered_unobserved` until a provider tick is observed.
  Stop requests disable registrations and waits for associated readback. The kernel does
  not create a native schedule or infer that an idle event completed work.
- Scoped provider event ingestion rejects changed duplicate payloads, preserves originals,
  and records stale observations without reviving obsolete ownership.

A service calls `reconcile_lifecycle` to record lease/deadline transitions and requests
provider cancellation through the outbox. That method does not run continuously itself.
The provider must enforce its own hard compute lifetime. This reference requires old
compute termination before retry because it has no deployed external credential-fencing
proxy. A backend proving that proxy may implement the source-permitted earlier replacement.

## Transport and authentication

`BridgeClient` uses an explicitly configured HTTPS origin and the **pstack-owned**
`/v1/operations` protocol. This is not an OpenAI endpoint or an existing MCP tool.
It follows no redirects, bounds response size and wait time, verifies response/request
association and never automatically retries an unknown POST outcome. Its credential
callback is supplied by trusted setup; it does not search environment variables or files.

`BridgeService.handle` is a dispatcher, not a public web server. The host supplies TLS,
request limits and authentication. The included HMAC authenticator is a local reference
credential-to-principal mapping with signed body/timestamp and a bounded replay window.
Idempotency is stored durably by tenant, project, request ID, subject and payload. The
production OIDC verifier, issuer/audience checks, key rotation, role mapping and deployment
are prerequisites; this code does not label HMAC as OIDC.

The authenticated principal is created by the configured authenticator. Request fields
cannot set its role, tenant, project or scopes. Workers must have explicit program/job
bindings and cannot prepare external effects. Neither this principal type nor an MCP
connection proves a native child cannot inherit its parent's credential. The default
capability response explicitly reports that root-only host access and UI-stop propagation
are uncertified.

The HTTP dispatcher supports capability negotiation, program prepare/activate/inspect/
stop/resume, lease renewal, job inspection, event reads and effect preparation. It exposes
job submission/retry only when a trusted provider registry is configured. Internal provider
observation, effect dispatch, artifact publication and reconciliation are service APIs,
not unrestricted model-callable HTTP endpoints. `worker.operation` requires a separately
configured isolated task-worker service; the local dispatcher does not advertise it.
Retry rechecks the original attempt's pinned provider and required capabilities within
the state transaction before recording a replacement; another available provider cannot
silently substitute for the selected one.

## Integration and verification

Runtime profiles are supplied by `runtime/`; the store pins the whole binding and does
not treat a profile's declared capabilities as provider qualification. The default
provider registry is empty. Native Cloud history is always unavailable through this
execution bridge; managed worker traces cannot substitute for the native conversation.

The tests under `integrations/pstack/tests/test_bridge.py` cover durable retry/replay,
concurrent job ingestion, rollback, grant/target/owner fencing, expiry versus stop,
wrong-resource terminal receipts, stale callbacks, uncertain effects, artifact integrity,
retention, schema mismatch and transport authentication. Fake SDK and provider receipts
exercise the boundary without claiming an actual deployment passed qualification.
