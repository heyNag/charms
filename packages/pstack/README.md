# pstack for Claude Code and Codex

Bundle 2026.11.1, based on canonical [pstack 0.15.43](https://github.com/cursor/plugins/tree/2f87c854fe3e2fcda44ca86b46ede35aad3c46b7/pstack).

Select `claude-code/` for Claude Code or `codex/` for Codex. The bundle root is not a plugin. Desktop, Cloud and CLI share the Codex payload; each host needs separate activation and capability validation.

The complete Claude tree is copied unchanged from this upstream commit, including its native version, dependencies and instructions referring to `pstack@cursor-plugins`. That upstream channel is separate from a Charms release; do not enable duplicate pstack installations. Codex is generated directly from canonical pstack through the maintained adapter.

Original native-history access on Desktop, Cloud and CLI, and provider-dependent workflows, are not certified by this adapter implementation. Installation alone does not establish those capabilities. Read the Codex adapter and run its capability checks before promising an outcome.

`bundle.json` records both target identities; `codex/UPSTREAM.json` records the adapter inputs. Generated files are replaced by `scripts/sync-pstack.py`; edit maintained integration sources instead. Publication is separate.
