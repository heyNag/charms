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

## Task Map

Use this map when you are new to the repo:

- Installing a public tool: use the root `README.md` install sections.
- Optional Skillshare hub installs or duplicate Skillshare search results: read
  `skillshare.md`.
- Understanding what to edit: read `architecture.md`, then
  `distribution-targets.md`.
- Adding `packages/awesome-skill`: follow `adding-a-skill.md`.
- Updating or releasing a skill: follow `updating-a-skill.md`.
- Checking target compatibility across Claude Code, Claude Desktop, Codex, and
  OpenCode: read `agent-compatibility.md`.
- Changing auth, API keys, local state, or generated artifacts: read
  `security.md` first.
- Changing `watch-video`, `codex-reset-credit`, or `x-bookmarks`: read that
  package's docs page before editing its source package.

When adding a new skill package, read `docs/adding-a-skill.md` before creating
files. It is the step-by-step checklist for targeting every generated surface.
When updating an existing skill package or explaining how users refresh
installed skills, read `docs/updating-a-skill.md`.

Recommended reading order for broader work:

1. `architecture.md`
2. `agent-compatibility.md`
3. `distribution-targets.md`
4. `target-tool-mapping.md`
5. `skillshare.md`
6. `adding-a-skill.md`
7. `updating-a-skill.md`
8. `agent-guidelines.md`
9. `security.md`
10. `watch-video.md`
11. `codex-reset-credit.md`
12. `x-bookmarks.md`
13. `roadmap.md`
14. `decisions.md`

Keep these docs aligned with the repo when architecture, workflow, install
behavior, security practice, or package scope changes. A future agent should be
able to understand the repo from files alone.

For source/generated ownership, start with `architecture.md`,
`distribution-targets.md`, `target-tool-mapping.md`, and `skillshare.md`. In
short, edit the package under `packages/`, then rebuild the committed public
outputs under
`generated/`, `.claude-plugin/`, and `skillshare-hub.json`.

When generated files need to change, use the clean rebuild path:

```sh
make rebuild-generated
make public-check
```

That removes `.claude-plugin/` and `generated/`, recreates them from
`packages/`, and rewrites `skillshare-hub.json`; generated outputs should not
be moved or edited by hand.

Before pushing public-facing changes, run the full sequential check:

```sh
make public-check
```
