---
name: principle-type-system-discipline
description: "Apply when designing types, reviewing a function signature, or writing code in any statically-typed language. Make illegal states unrepresentable, brand semantic primitives, parse external data at boundaries, exhaust variants, derive from authoritative schemas."
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

# Type System Discipline

Make the compiler reject impossible states, mismatched primitives, and unhandled variants.

- **Brand semantic primitives.** If two arguments share a primitive type but mean different things, give each its own type. Validate once at creation.
- **External data is untyped until parsed.** JSON, RPC payloads, CLI args, config, environment variables, and database rows go through a parse function at the boundary that returns the typed model.
- **Derive types from authoritative schemas.** When a schema file owns a shape, derive the type from it instead of hand-rolling a parallel one.

For TypeScript syntax, see the **typescript-best-practices** skill.
