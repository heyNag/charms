# Explicit provider adapters

No execution provider is enabled merely by installing pstack. A trusted service registry
selects actual provider implementations and records their version, capability set and
qualification reference. These records belong to service configuration; workers cannot
register themselves or turn a configured model name into an observed vendor identity.

## Anthropic worker driver

`anthropic_worker.execute_sdk_job` implements the reviewed official Claude Agent SDK
route for candidate, judge, audit, trial and grader jobs. It uses:

- `claude-agent-sdk==0.2.182`, source commit
  `4720d367f7db9d5df8a166c74d7f36a538ac8c34`.
- `anthropic==2.8.0`, source commit
  `5139cf2e7d07aa618a6c30b7e0c712f10ccb5ad9`.
- JSON Schema result validation, pinned in `requirements.txt`.

Install those optional dependencies only in the trusted driver environment. The package
requires Python 3.11; it does not install dependencies or spend API credits during
ordinary plugin loading. No provider call was used to validate this implementation.

`run_isolated(request, credential=..., timeout_seconds=...)` starts one fresh driver under
a dedicated Linux child subreaper. The caller supplies the credential explicitly from its secret
manager. The child receives a complete environment containing only its private home,
fixed executable path, adapter module path, locale and Anthropic credential. It does not
inherit AWS, Slack, tracker, forge, proxy, global Codex or arbitrary parent credentials.
The child SDK environment is not relied upon to remove inherited secrets. Driver stdout,
input, SDK buffer, cost, turns and wall-clock lifetime are bounded; unknown outcomes are
not retried. Stderr and raw provider errors are not exported.

`python3 process_supervisor.py -- COMMAND [ARG ...]`, run from this directory, is
also a standalone helper, independent of provider SDK imports. It inherits the caller's
environment and streams; the provider runner supplies its sanitized environment and
budgets externally. The helper preserves
the command's exit status, continuously reaps adopted children, and terminates and reaps
remaining descendants before returning, including detached children after their original
leader exits. A caller should send TERM to the helper and allow three seconds for cleanup.
Unverified cleanup returns failure. This helper requires Linux; desktop clients can use a
qualified Linux worker service without making their host a provider execution environment.

The SDK session has a fresh UUID and no resume/continue, fallback model, built-in tools,
ambient settings, skills, plugins or agents. MCP configuration is strict. Model selection
uses the actual Models API response and supported effort metadata, not a guessed slug
or a `max` → `xhigh` relabeling. Actual init/assistant/result model IDs are resolved against
that catalog; effort comes from SDK hooks. Wrong session/credential provenance, ambient
tools, missing effort, unexpected models, cancellation, budget failure, denied tools or
invalid structured output produce incomplete execution. Worker text never supplies model
identity or a passing backend receipt. The service still has to verify the selected
account's entitlement and the driver's pinned CLI/image before deployment qualification.
Result schemas allow only local references; validation uses a registry with no remote
retriever, including for dynamic references.

Fast mode is not guessed. `execute_sdk_job` accepts a separately qualified settings
mapping from trusted service code and checks the actual SDK init state. A fast-required
job without that mapping fails. The simple isolated runner supplies no such mapping, so
it intentionally cannot satisfy current upstream Opus-fast selections until the deployment
provides and qualifies that configuration. This limit must remain visible to setup/model
resolution; it must not downgrade the source requirement silently.

The isolated runner handles evidence-complete, tool-free tasks. A job that requires task
execution is rejected unless a trusted service supplies `broker_tools` to
`execute_sdk_job`. `scoped_tools.make_remote_tools` constructs SDK callbacks for explicitly
selected read/exec/write/artifact operations on a separate secret-free worker. Callbacks
bind job, epoch and contract digest, and check scoped operation receipts. No callback
reads the driver environment or launches a native shell. The worker service must enforce
path/network/deadline/capability isolation; it is not implemented by the local control
store and is not assumed available. The job cannot configure its own server, callback,
settings or credential source.

The bridge must durably claim its launch token before invoking this driver, and store the
result and original SDK metadata. Closing this provider session or killing its owned
process group does not establish that a separate task VM has terminated. External VM
export, cancellation and terminal readback remain provider infrastructure responsibilities.
A valid audit can report failed work; the structured result's meaning is assessed against
the source workflow predicate, not equated with SDK transport success.

## Remaining production integrations

`ExecutionProvider` specifies launch/inspect/terminate operations with a persisted launch
token. It is an integration interface, not a fake OpenAI API implementation. The Agents
API session/schedule and AWS MicroVM deployment drivers, OIDC gateway, durable hosted
storage, private Bot UI and Slack/tracker adapters still need deployment-specific code
and qualification. The Anthropic execution module above is concrete; these other drivers
are not claimed implemented. No invented endpoint or privileged native Codex tool fills
that gap. This package's defaults report those capabilities unavailable.

Original native Cloud transcript access remains a separate unresolved producer. Neither
Anthropic output, Agents API records for a different conversation nor a decision journal
can stand in for the required original native history.

Official API evidence is pinned in the design; the implementation follows
[SDK options and messages](https://github.com/anthropics/claude-agent-sdk-python/blob/4720d367f7db9d5df8a166c74d7f36a538ac8c34/src/claude_agent_sdk/types.py),
[SDK client](https://github.com/anthropics/claude-agent-sdk-python/blob/4720d367f7db9d5df8a166c74d7f36a538ac8c34/src/claude_agent_sdk/client.py), and
[Models API](https://github.com/anthropics/anthropic-sdk-python/blob/5139cf2e7d07aa618a6c30b7e0c712f10ccb5ad9/src/anthropic/resources/models.py).
