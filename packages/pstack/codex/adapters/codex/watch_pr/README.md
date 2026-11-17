# Bounded GitHub watcher

The generated `skills/poteto-mode/scripts/watch-pr/watch-pr` entry invokes
`supervisor.py`. It starts one monotonic attempt budget before Bun discovery,
cache locking and dependency installation. `--attempt-timeout` defaults to
900 seconds; an upstream `--timeout` greater than zero further bounds the
whole attempt. `--timeout 0` does not disable the supervisor. A configured
long-running workflow rearms bounded attempts with its original frozen queue.

Dependency installation runs with the upstream lockfile in an external,
content-addressed cache, under one exclusive lock. Only production dependencies
are installed, with lifecycle scripts disabled. The cache identity binds all
helper inputs, install options, runtime identity and platform. A receipt records
the installed dependency files, hashes, modes and contained relative file links;
reuse verifies that inventory and rejects extra files or directory/external
symlinks. The ready marker binds the receipt digest within the private user-owned
cache. It becomes ready only after the frozen install and input verification
succeed. The consumer repository remains the execution working directory. The
installed plugin is not written, and cannot be selected as the cache location.

Every Git/gh operation uses a generated bounded transport. One remaining
monotonic deadline covers the entire command sequence and pagination; captured
command output and supervisor output each have an 8 MiB attempt cap, tunable
with `--output-limit` up to 64 MiB. Linux commands run under the shared dedicated
subreaper, which kills and reaps owned descendants, including detached sessions
and grandchildren whose leader exited. Timeout and interruption permit up to
three seconds of cleanup grace beyond the attempt budget. Other POSIX hosts use
process-group termination and require host-specific descendant qualification.
Success is withheld when the supervised exit disagrees with the final record.

The upstream verdict policy, types and rendering remain the baseline. Guarded
snapshot edits bracket each real evidence read with actual head/base OID,
ref and state observations, then recheck all bound PRs before a readiness or
completed-queue handoff. A changed or missing identity produces incomplete
`STALE_SNAPSHOT` or `SNAPSHOT_UNAVAILABLE`, never accepted mixed-head readiness.
These are as-of observations, not a lock on GitHub; an authorized merger still
revalidates the target head/base immediately before its side effect.

Output records use `wrapperSchemaVersion: 1`. The original source verdict
stays unchanged inside `upstream`, with revision bindings alongside it.
Transient `PROGRESS` records stream separately from terminal results. Deadline,
output-limit, query failure and interruption are incomplete wrapper outcomes. `STATUS` exit
zero remains only a status report; empty check sources retain the upstream
unavailable verdict. This helper never requests a merge.

Queued mode preserves frozen membership and never invents upstream `READY`.
For Babysit's explicitly selected drive behavior, `--until-merge-ready` stops
at a current blocker-free `WAITING`/`merge-queue` observation after revision
revalidation and returns wrapper `MERGE_READY`. Its raw upstream record remains
WAITING; it is not proof of a merge. Without that option, queued watching
continues to upstream `COMPLETE` or an incomplete/bounded outcome. Shipping
must retain the same bottom-to-top `--stack-prs` list on every rearm.

The guarded edits are maintained in the integration's transform rules. No
community implementation is imported. The real fake-gh integration tests
exercise hung child trees, dependency startup, output floods, changing heads
and bases, final-handoff changes, infinite pagination, conservative no-checks,
status-only and queued-versus-merged outcomes. Set `PSTACK_TEST_BUN` to the
pinned Bun executable when running `tests/test_pstack_watch_pr.py`; ordinary
process-supervision tests use only the Python standard library.
