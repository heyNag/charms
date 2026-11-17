---
name: principle-sequence-verifiable-units
description: "Apply to multi-step work (sweeps, migrations, runs of similar edits) and to how you stack commits and PRs. Break work into small units that each end in a verifiable state, check each before the next, and order delivery so the sequence proves itself to a reviewer."
disable-model-invocation: true
---

## Codex execution binding

The entry resolver has selected this operative file. Read the verified root's
`adapters/codex/adapter.md` before following host-specific steps below. It maps
source tool, model, transcript, authoring and automation terms to actual Codex
capabilities; those source terms do not create native APIs or permissions.
Use this same resolver for direct and internal calls. Interpret relative
skill/helper references from the resolver's immutable `resource_root`, not
from a relocated override file. Its `resource` command routes sibling skill
bodies through the same approved registry. Preserve the workflow's
required result and source-specific fallback. Missing capabilities leave the
affected step incomplete, not successfully emulated. User instructions and
host policy govern the actual task. Ordinary workers read the bound worker
contract first; blind Eval trials use the explicit isolated trial exception.

# Sequence work into verifiable units

Order work as small units that each end in a state you can check, and do not advance until the current one is green.

In a sweep, migration, or run of similar edits, each unit is a bracket: known-good state, one change, run the check, proceed. Run the per-unit check even when a tool does the edits.

Deliver in the order that proves the work: the failing test first, then the fix. The subtraction before the reshape. The baseline before the treatment. Each commit lands on its own.
