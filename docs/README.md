# Agent Tools Docs

This `docs/` folder is the canonical orientation guide for future humans and AI
agents working in `agent-tools`. The root README is the front door; these files
carry the project memory, constraints, and direction.

Before making structural changes, future agents should read:

1. `docs/README.md`
2. `docs/architecture.md`
3. `docs/agent-guidelines.md`
4. `docs/agent-compatibility.md`

Recommended reading order for broader work:

1. `architecture.md`
2. `agent-compatibility.md`
3. `agent-guidelines.md`
4. `security.md`
5. `watch-video.md`
6. `codex-reset-credit.md`
7. `roadmap.md`
8. `decisions.md`

Keep these docs current when architecture, workflow, install behavior, security
practice, or package scope changes. A future agent should not need prior chat
history to understand why the repo is shaped this way.

For source/generated ownership, start with `architecture.md`. In short, edit
the package under `packages/`, then rebuild the committed public outputs under
`generated/` and `.claude-plugin/`.

When generated files need to change, use the clean rebuild path:

```sh
make rebuild-generated
make audit-generated
make verify-generated-clean
```

That removes `.claude-plugin/` and `generated/` and recreates them from
`packages/`; generated outputs should not be moved or edited by hand.
