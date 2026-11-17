# pstack integration

Pstack is one versioned bundle with two installation roots. Claude Code is
copied exactly from upstream; Codex is generated directly from the canonical
pstack source. Desktop, native Cloud and CLI share the same Codex payload.
A marketplace installation becomes available only after a bundle release is
published, verified, and added to the host catalogs. Generated files in a
checkout do not establish publication; `published.json` records the verified
release separately from the working bundle.

```text
integrations/pstack/
├── upstream.lock.json          # Full commit, version, input trees and dependencies
├── source-manifests/           # Every input path, hash and executable mode
├── projection.json            # Pending bundle version and named transforms
├── published.json             # Verified release; null before first publication
├── requirements.json          # Source-to-behavior and acceptance records
└── codex/                     # Maintained adapter inputs

packages/pstack/               # Generated release container, not a plugin
├── bundle.json
├── claude-code/               # Exact upstream native target
└── codex/                     # One Codex target for every surface
```

## Baseline and ownership

The baseline is **0.15.43** at
[`cursor/plugins@2f87c854fe3e2fcda44ca86b46ede35aad3c46b7`](https://github.com/cursor/plugins/tree/2f87c854fe3e2fcda44ca86b46ede35aad3c46b7/pstack).
The canonical input has 551 files; the upstream-generated Claude tree has 537.
All 58 skill names are retained. Codex registers 57 as manual-only;
`setup-pstack` retains implicit availability. Benny's three internal skills
are dormant resources. The new `worker.md` is a required resource, not another skill.

Never edit the generated bundle or either upstream snapshot. Edit maintained
Codex adapter inputs, then regenerate. Both snapshots are replaced completely,
so upstream deletions and renames leave no old files behind. Canonical source
and Claude always use the same commit. At this baseline, Claude's version is
`0.15.43`; the independent bundle and Codex version is `2026.11.0`.

The community pstack-claude repository is a reference only. No fork code or
second synchronization source is used. Original authorship and licenses are
preserved; downstream changes are recorded by the Codex projection.

## Generate and inspect

Repository tooling and the Codex adapter require Python 3.11+. Generation's
upstream harness check needs Node. From the repository root:

```sh
# First acquisition: fetch exactly the full commit in upstream.lock.json.
python3 scripts/sync-pstack.py --fetch

# Subsequent runs use the retained external cache without network access.
python3 scripts/sync-pstack.py --check
python3 scripts/validate_plugins.py

# One combined archive and optional host-specific transport archives.
python3 scripts/build-plugin-archive.py pstack
python3 scripts/build-plugin-archive.py pstack --target codex
python3 scripts/build-plugin-archive.py pstack --target claude-code
```

An existing exact source snapshot can be selected with `--source PATH`; an
existing Git object store can be used with `--git-dir PATH`. `--cache-dir PATH`
selects retained storage outside the checkout. `--report PATH` saves the full
generation or candidate diff. Missing or mismatched input identity fails before
replacement. `--check` compares deterministic output without updating it.

Each transport archive contains one `pstack/` folder holding the selected
plugin manifest and complete subtree, matching the inspected Agents API loader.
It has its own checksum, distinct from the combined bundle checksum. Install
only the selected child through the host's supported mechanism; do not register
the aggregate container or both children in Codex. Actual native Cloud
instruction activation and complete runtime provisioning are separate steps.

For a local Desktop trial of a reviewed checkout, follow the
[Desktop validation steps](pstack-desktop-validation.md). They create an isolated
test marketplace and distinguish file integrity from actual host activation.

## Runtime and configuration

For an extracted Codex root, the executable entry is
`adapters/codex/runtime/pstack_runtime.py`. It verifies resource identity before
resolving a skill's operative body. For example, from the repository root:

```sh
python3 packages/pstack/codex/adapters/codex/runtime/pstack_runtime.py verify \
  --root packages/pstack/codex
python3 packages/pstack/codex/adapters/codex/runtime/pstack_runtime.py resolve architect \
  --root packages/pstack/codex
```

Hashes inside a package establish consistency; a trusted installation or an
externally pinned manifest digest establishes origin. Cloud resolution requires
an external installation locator bound to the actual root and manifest digest.
An opaque skill URI is not a filesystem locator, and a metadata import alone
does not provision helpers.

Deployment settings live outside the generated package. The initial schema is:

```toml
schema_version = 1
active_profile = "default"

[profiles.default]
```

Every named profile uses the same resolver. Add another supported setup by
configuration, without rebuilding the package. Unknown selections fail;
active jobs retain their original profile/account/authority binding. Settings
contain credential references, never private keys or provider tokens. A profile
name is not an email or Codex login and does not change Git identity.

Upstream model preferences are separate: nine roles, defaults revision 3,
source-defined budgets and migration. The adapter reads those preferences
explicitly; Codex is not assumed to load a Cursor MDC rule automatically.
Provider mappings require actual catalog evidence. Another endpoint or model
family does not establish another originating vendor. Fable and Opus share
Anthropic; Shipping's non-author verifier does not acquire a universal vendor gate.

See the maintained [runtime guide](../integrations/pstack/codex/runtime/README.md)
for exact commands, locator/profile schemas, approved overrides, model setup,
worker projection and original-history validation.

## Update upstream

Prepare a candidate without changing the active pin or executing newly fetched
upstream code:

```sh
python3 scripts/sync-pstack.py --prepare-update FULL_UPSTREAM_COMMIT_SHA \
  --candidate-dir /absolute/new/candidate-directory --fetch
```

Read the candidate's `report.json` and every changed source contract. In
`review.json`, classify each canonical/support change with its reason and
affected requirement IDs. Rebase the candidate's requirements and projection
pins; update maintained transforms and their focused tests where necessary.
Claude changes are exact copies, never patches or manual content merges.

Then apply the reviewed candidate:

```sh
python3 scripts/sync-pstack.py --apply-candidate /absolute/candidate-directory
```

Application rejects stale bases, altered candidate inputs, unreviewed changes,
missing requirement mappings and failed generation/validation. Both host roots,
the lock and reviewed records advance together; failures retain the previous
complete inputs and output. Source archives remain external and immutable.
If a process is interrupted during promotion, `python3 scripts/sync-pstack.py
--recover` uses the local transaction journal. Recovery rejects intervening
operator edits instead of overwriting them; retain the journal for explicit
reconciliation in that case.
See [releasing](releasing.md) for bumping the separate bundle version and actual
publication. Sync does not publish, create tags, change catalogs or update a
running job's instructions.

## Tests

`make check` covers repository and offline adapter behavior, including malformed
resources, unknown profiles, stale bindings, model migration, unsafe trial
projection, missing history, action replay and bundle integrity. Tests assert
that unavailable evidence cannot turn into successful verification.

```sh
make check
make coverage
make test-pstack-upstream
```

The last command installs the locked test toolchain in temporary storage and
runs Statechart and upstream watcher tests in disposable copies, followed by
the Codex watcher's real-Bun/fake-GitHub integration tests. It clears
`STATECHART_UPDATE`, preserves fixture identities and checks the original
bundle afterward. Statechart's real TLC cases require the upstream-pinned
1.7.4 jar and Java; pass `--tlc PATH` to `scripts/test-pstack-upstream.py`
alongside `--install`. Missing TLC means those cases are skipped, not certified.
Native plugins retain their Python 3.9 floor and existing validation rules.

## Support boundary

The bundle, adapter and local integration tests are implemented here. They do
not establish that native Desktop or Cloud has activated every policy/resource,
that a provider is deployed, or that an external workflow has run successfully.

- Native Cloud original current and historical conversation access remains
  unestablished. Reflect needs its whole transcript; Show-me, Recall,
  Automate-me and composed workflows retain their own original-evidence needs.
  A managed child trace or assistant-written journal cannot replace that history.
- The local bridge kernel tests durable ownership, authority, replay, uncertain
  outcomes, artifact retention and stop semantics. Production provider and
  identity adapters need real deployment qualification. A local SQLite test
  does not certify distributed scheduling, AWS isolation or native UI-stop delivery.
- Actual browser/media surfaces, independent vendor execution, fresh-session
  resource access and host-specific activation/update behavior require their
  real integration acceptance. Configuring a location cannot create a capability.

Missing required capability is reported as unavailable or incomplete. Only a
fallback expressly allowed by the calling upstream workflow can finish that
branch. Neither package installation nor an offline test pass claims full
native desktop/Cloud parity.
