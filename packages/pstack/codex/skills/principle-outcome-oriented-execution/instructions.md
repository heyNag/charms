---
name: principle-outcome-oriented-execution
description: "Apply during planned rewrites and migrations with explicit phase boundaries. Converge on the target architecture; don't preserve smooth intermediate states with throwaway compatibility code."
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

# Outcome-Oriented Execution

Optimize for the intended, verifiable end state rather than preserving smooth intermediate states.

**Why:** Keeping every intermediate step fully stable often creates temporary compatibility code that becomes long-lived debt. Converge on the target architecture and prove correctness at explicit verification boundaries.

**Core rule:**
- Prioritize end-state integrity over transitional stability
- Intermediate breakage is acceptable when it is planned, scoped, and reversible

**Guardrails:**
- Use this for planned rewrites and migrations with explicit phase boundaries
- Declare where temporary breakage is acceptable
- Keep high-signal checks for actively touched areas while migrating
- Require full static and runtime verification at plan completion
