# Codex host binding

This adapter changes host integration, not canonical pstack or its unchanged
Claude target. Resolve every direct or internal skill through
`runtime/pstack_runtime.py resolve` in this verified adapter directory. Read
the effective `instructions.md` including its full frontmatter; descriptions
of concise principle skills are part of their operative requirements.

## Installation, dispatch and settings

Use the installed `codex/` root or an explicit provisioned locator. Never
search Cursor caches, pick the highest installed version, read a sibling
Claude tree, or assume hidden manual skills appear in a model's catalog.
`skills/index.json` describes the complete skill set. Every resolved body
comes with `payload_root` and immutable `resource_root`. Resolve source-relative
helpers from that resource root through `runtime/pstack_runtime.py resource
<SKILL> <RELATIVE_REFERENCE>` with the same root/locator/config flags. An external
approved body's directory is not the package root. Sibling `SKILL.md` and
`instructions.md` references resolve to their effective approved bodies, not
raw base files. Keep both the effective path and resource binding in nested
worker kickoffs, and interpret a role's mode-read instruction through this
same resolver rather than rereading an unselected base.

The default model catalog may list only `setup-pstack`: the other 57 skills
are manual-only, not disabled. Native explicit invocation uses an actual user
message or a path-bound skill-picker selection. A skill name embedded in an
app-tool delegation output does not establish that this activation path ran.
For internal workflow calls, use the verified package index and resolver even
when the sibling skill is absent from the default model catalog.

The resolver automatically reads `~/.config/pstack/overrides.json` when present.
The selected profile's `override_registry` may supply another absolute external
registry; `--overrides` selects an explicitly supplied registry. An invalid or
stale selected registry fails resolution instead of silently using the base.
An explicit registry does not bypass validation of the active profile.

Cloud needs a supported host activation route plus complete runtime files and
an external locator pinning the expected manifest. The local verifier proves
file integrity, not successful native activation or installed policy transport.
Do not claim those acceptance cases ran simply because the archive was built.

Deployment settings live outside the payload at `~/.config/pstack/config.toml`.
The schema supports a named profile map with `active_profile = "default"` and
only `[profiles.default]` configured initially. Adding another supported setup
does not change this package. Unknown selections fail; switching profiles does
not move an active job, expand its authority, change Codex login or change Git
identity. A profile names locations and credential references, not secrets.

Model preferences are separate: `~/.config/pstack/models.mdc` retains upstream's
nine roles and budget. Ordinary resolution reads existing values unchanged;
older defaults receive a once-per-conversation setup reminder, not automatic
migration. Only explicitly accepted setup plans write defaults revision 3.
Codex does not natively auto-load Cursor MDC rules.
Setup uses `runtime/pstack_runtime.py models plan --file <MODELS_FILE>
--catalog <OBSERVED_CATALOG_JSON> --budget <large|medium|small>`, presents the
plan, and writes only after the operator's applicable approval using
`models write --plan <PLAN_JSON> --approved-plan <PLAN_SHA256> --file <MODELS_FILE>`.
Use the actual CLI help for supported plan inputs and output fields. Preserve
existing valid authorization instead of inventing an extra approval round.

Do not feed Cursor model slugs into Codex tools. Source names describe model
families/effort/speed requirements. Resolve only models actually offered by
the current tool or an explicitly configured provider with verified mapping.
Record requested and observed originating vendor, family, model, effort and
speed. An endpoint, account name or model self-report does not prove vendor.
Preserve all role migration and alias/cardinality rules in setup-pstack; a
deployment profile is not a global default model. Fable and Opus are one
vendor. Outside panels, Fable needs the source's explicit user choice or two
evidenced failed same-brief Opus xhigh attempts, not task difficulty alone.

An absent model-preferences file is not a universal dispatch prohibition.
Follow the calling workflow's fallback order using observed available models;
where that workflow permits omitting the model to inherit the parent, disclose
the fallback. Do not turn that permission into a waiver of another-vendor or
independent-review requirements. Those branches remain incomplete when their
required qualified reviewer is unavailable.

## Tools, workers and task authority

`Task`, `generalPurpose`, `poteto-agent`, `Project`, `AskQuestion`, `Read`,
`Shell`, and source background/browser tool names are capability terms. Use
the tools actually present with their declared schema. Role Markdown does
not register a custom Codex agent type. A generic worker must receive the
explicit role file, required mode resource and permitted inputs. Do not
invent a Task type, model override, read-only guarantee or background service.
Questions required by the workflow go through an available coordinator
question tool or a concise direct question; do not invent unsupported
multi-select fields. Workers follow their no-human-question contract.

Every ordinary worker kickoff starts with `Read <absolute>/worker.md before
anything else.`, resolved in the verified selected runtime, and propagates
that first line to nested workers. Include the task/goal and the actual mode
operative path when using the poteto role. Fresh workers are the default;
source-permitted costly checkout, uncommitted changes or running-process
state can justify resume. A fresh identity does not itself prove isolation.

Eval candidates are the narrow exception to ordinary full-role loading.
Use an explicit generic trial role, neutral standalone worker resource,
organic brief and declared treatment only. Do not expose full mode, evaluator
paths, parent history, rubric or coordinator provenance to the candidate.
The actual file/tool/context boundary must enforce this; a no-history option
alone is insufficient. Freeze the declared treatment. If that treatment
requires content forbidden by blinding, report the incompatibility and obtain
an explicit redesign of the comparison; never silently prune or rewrite the
treatment and call the result blinded. Coordinator provenance stays outside
candidate reach. This is not another registered plugin.

Keep the worker's kickoff bar as the whole bar and add no universal sign-off.
Source/operator boundaries still govern irreversible actions. Ordinary ready
PR formatting does not override Benny's explicit no-worker-publication and
coordinator draft-only kickoff. Shipping retains a non-author cloud verifier
per PR with actual parent/head proof; it does not by itself require another
vendor. Show-me's required other-vendor review cannot use Arena's skip outcome.

## History and independent evidence

Source `agent-transcripts/` paths describe a required original record, not a
Codex storage convention. Use only an actually supported and authorized
producer for the exact native conversation/workspace/window. Never guess a
Cursor path, scan unrelated account history, equate an inner managed session
with its native outer conversation, or use an assistant journal as its own
proof. This package supplies no qualified original native-history producer
for Desktop, Cloud or CLI.

Reflect requires the whole current transcript, including the original prefix;
it has no digest fallback. Show-me requires the actual run chronology and
another-vendor review before handoff. Recall and Automate-me require the
requested historical scope except their own explicitly allowed alternatives.
Report unavailable/partial intervals. Independent operation evidence may
supplement chronology; passing current tests cannot recreate earlier steering
or a failed/reverted experiment. Every raw output byte and private reasoning
are not required. A completed audit may flag unsupported work, but an absent
required original interval remains unaudited.

## Durable execution, automation and controls

Cursor Projects, `/automate`, Grok Bot `update_state`, editor handoffs and
webhook routines describe outcomes to supply through an actually configured
native capability or the authenticated bridge/provider integration. They
are not native Codex tools. Consult `bridge/` and `providers/` implementations
and their explicit capability/qualification status; do not silently replace
the native coordinator with a managed API conversation. No durable action,
provider spend, external message, credential transfer or deployment is
authorized merely by installing this plugin.

Preserve real future wake, ownership, idempotency, review/activation gates,
thread identity, output proof, stop and cleanup semantics. A shell sleep is
not a registered future wake. A local broker test is not a provider acceptance
test, and a cancel request is not observed process termination. Use stronger
VM isolation only where the surviving workflow actually needs it. Never
recreate deleted Orchestrate topology or the old ten-lane plan recipe.

Benny's pack remains dormant. Copy its generated ordinary resource bodies to
the selected committed project location under `.agents/automations/benny/`,
preserving destination-only files and reviewing conflicts; user configuration
lives outside the pack. Its generated `instructions.md` filenames stay
ordinary resources, not recursively discovered `SKILL.md`. Project-scoped
Codex activation/runtime provisioning must be supported and verified by a
fresh worker in that repository. A made-up settings JSON file cannot enable
a plugin. If that route is unavailable, stop setup before enabling automation.

Run the bundled `watch-pr` launcher for PR observations. Its
`wrapperSchemaVersion: 1` records keep the unchanged source verdict inside
`upstream`; `STATUS` exit zero is a status report, not readiness. One monotonic
attempt deadline includes dependency setup, lock waits, discovery and every
Git/gh query. `--attempt-timeout` defaults to 900 seconds; source `--timeout 0`
cannot disable it. Rearm a bounded queued attempt with the same frozen PR list.
Only Babysit's selected drive flow uses `--until-merge-ready`; that separate
wrapper outcome preserves upstream `WAITING` and never proves a merge.

The watcher validates actual head/base identity around all evidence, including
the initial facts read, and again before readiness handoff. Stale identity,
unavailable checks, deadline, output-limit or interruption stays incomplete.
The watcher never merges. Linux uses a dedicated child subreaper to kill and
reap descendants, including detached sessions; other POSIX hosts provide
process-group cleanup and require separate descendant qualification. Consult
`watch_pr/README.md` for cache validation, outcome and cleanup limits.

For UI/CLI/media verification, use actual observed browser/computer/terminal
interfaces with complete artifacts. Canonical `deslop`, `control-ui` and
`control-cli` procedures are bundled under `dependencies/cursor-team-kit/`
with their original license, not additional registered skills. Resolve those
paths directly from the verified plugin root.

## Authoring and approved changes

Source `create-skill` refers to the authoring capability, not a guaranteed
built-in Codex skill. Use an available supported authoring skill or the
bundled `poteto-mode/playbooks/authoring-a-skill.md` procedure with the actual
host schema and validation. Preserve the proposed content and test it through
the target's real invocation path. Project/user skill destinations use
`.agents/skills/` and `~/.agents/skills/`, subject to the actual host's supported
scope. A source Custom Mode UI must not be presented as an available Codex UI.

Reflect edits only after applicable approval, outside the immutable plugin
cache. Register each approved body in the active external override registry
with its pinned payload/base hashes, approved body hash/path and approval
reference. Copying an edited body alone does not activate it. Direct, internal
and nested worker calls automatically use that same registry and its immutable
resource binding. A changed description or discovery policy additionally
needs a supported host-visible local precedence/replacement path; a body
registry cannot alter metadata already loaded by the host. If that activation
path is unverified, report the limitation rather than claiming persistence.
Keep the source's no-PR/no-push rule for reflection.
