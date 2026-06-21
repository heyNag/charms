# Agent Tools Docs

This `docs/` folder is the canonical orientation guide for future humans and AI
agents working in `agent-tools`. The root README is the front door; these files
carry the project memory, constraints, and direction.

Before making structural changes, future agents should read:

1. `docs/README.md`
2. `docs/architecture.md`
3. `docs/agent-guidelines.md`
4. `docs/agent-compatibility.md`
5. `docs/distribution-targets.md`

When adding a new skill package, read `docs/adding-a-skill.md` before creating
files. It is the step-by-step checklist for targeting every generated surface.

Recommended reading order for broader work:

1. `architecture.md`
2. `agent-compatibility.md`
3. `distribution-targets.md`
4. `adding-a-skill.md`
5. `agent-guidelines.md`
6. `security.md`
7. `watch-video.md`
8. `codex-reset-credit.md`
9. `x-bookmarks.md`
10. `roadmap.md`
11. `decisions.md`

Keep these docs aligned with the repo when architecture, workflow, install
behavior, security practice, or package scope changes. A future agent should be
able to understand the repo from files alone.

For source/generated ownership, start with `architecture.md` and
`distribution-targets.md`. In short, edit the package under `packages/`, then
rebuild the committed public outputs under `generated/` and `.claude-plugin/`.

When generated files need to change, use the clean rebuild path:

```sh
make rebuild-generated
make audit-generated
make verify-generated-clean
```

That removes `.claude-plugin/` and `generated/` and recreates them from
`packages/`; generated outputs should not be moved or edited by hand.
