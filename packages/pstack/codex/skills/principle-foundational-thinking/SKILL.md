---
name: principle-foundational-thinking
description: "Apply before writing logic: choosing core types and data structures, sequencing scaffold-vs-feature work, asking what concurrent actors share. Get the data structures right so downstream code becomes obvious."
---

# principle-foundational-thinking for Codex

This is the entry descriptor for pstack 0.15.43 at upstream commit
`2f87c854fe3e2fcda44ca86b46ede35aad3c46b7`, adapter bundle `2026.11.0`.
Its operative instructions include the original description and frontmatter.

Before following the workflow, resolve it through the installed runtime:

1. For a filesystem installation, `<CODEX_ROOT>` is the root containing this
   descriptor at `skills/principle-foundational-thinking/SKILL.md`. Use that exact installation;
   never scan for the highest cached version or use a sibling Claude root.
2. If this entry is an opaque resource, use the environment's explicit pstack
   runtime locator. A resource URI is not a filesystem path. Native Cloud
   requires the locator's expected manifest digest and `--surface cloud`.
   If a complete matching runtime is not provisioned, report that prerequisite
   rather than guessing a path or loading an unrelated installed revision.
3. Run the resolver with the root selected above. Add `--locator <LOCATOR_FILE>`
   for a provisioned environment, and `--surface cloud` on native Cloud:

   ```sh
   python3 "<CODEX_ROOT>/adapters/codex/runtime/pstack_runtime.py" resolve principle-foundational-thinking --root "<CODEX_ROOT>" --expected-upstream 2f87c854fe3e2fcda44ca86b46ede35aad3c46b7 --expected-version 2026.11.0
   ```

4. Read `<CODEX_ROOT>/adapters/codex/adapter.md`, then read the complete effective
   instruction file returned by the successful resolver, including frontmatter.
   Apply the reported external model preferences. Use the same resolver for
   internal skill calls and approved overrides. Keep its returned `payload_root`
   and `resource_root`: all relative helpers resolve from that immutable skill
   resource root even when the effective instructions live in an external
   approved override file. Use `resource principle-foundational-thinking <RELATIVE_REFERENCE>` with
   the same runtime flags to resolve helpers or sibling skill bodies; do not
   read relative to a relocated override directory. Never treat this descriptor
   alone as the operative skill, or manually edit a plugin-cache file.

The resolver checks the full manifest and file modes. An externally pinned
manifest establishes the selected artifact binding; a self-consistent unpinned
installation alone does not establish provenance. Do not infer native history,
models, tools, external permissions or durable execution from package presence.
