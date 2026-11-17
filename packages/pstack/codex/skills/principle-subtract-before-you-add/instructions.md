---
name: principle-subtract-before-you-add
description: "Apply when sequencing an addition, refactor, or rewrite. Remove dead code, redundant validators, and stub references first, then build on the simpler base."
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

# Subtract Before You Add

When evolving a system, remove complexity first, then build. Default to subtraction.

Make simplification a continual investment. Leave the design slightly simpler and more capable behind the same or smaller surface than you found it.

- Sequence removal before construction
- Cut before you polish (get to the minimum before investing in quality)
- Design for observed usage, not speculative edge cases
- No speculative validators, parsers, or guards beyond what the spec demands
- Simplify prompts (remove redundant instructions, excessive templates)
- When a reference has no novel content, delete it rather than leaving a stub
