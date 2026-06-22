# Agent Tools Docs

This `docs/` folder is the canonical orientation guide for future humans and AI
agents working in `agent-tools`. The root README is the front door; these files
carry the project shape, constraints, and workflows.

Before structural changes, read:

1. `architecture.md`
2. `package-shape.md`
3. `agent-guidelines.md`
4. `installing-skills.md`
5. `distribution-targets.md`
6. `target-tool-mapping.md`

## Task Map

- Install a public tool: use `installing-skills.md`.
- Understand source layout: read `architecture.md` and `package-shape.md`.
- Understand target-specific install behavior: read `distribution-targets.md`
  and `target-tool-mapping.md`.
- Add a new skill package: follow `adding-a-skill.md`.
- Update a skill: follow `updating-a-skill.md`.
- Release a public skill version: follow `releasing-a-skill.md`.
- Optional Skillshare hub installs: read `skillshare.md`.
- Security, credentials, or local auth: read `security.md`.
- Package-specific work: read `watch-video.md`, `codex-reset-credit.md`,
  `x-bookmarks.md`, or `chatgpt-pro-review.md`.

## Core Rule

Edit source under:

```text
packages/<name>/
```

Do not create committed target-copy folders. This repo is source-only for public
targets:

- Claude Code marketplace entries point directly at `packages/<name>`.
- Codex and OpenCode can copy `packages/<name>/skills/<name>`.
- Cursor, root Codex plugin metadata, and the OpenCode plugin wrapper use the
  root `skills/` symlink index.
- Claude Desktop custom-skill folders are local `.dist/` artifacts.
- Skillshare hub entries point at `packages/<name>/skills/<name>`.

After source changes:

```sh
make build-packages
make public-check
```

`make build-packages` refreshes the committed indexes and ignored local
artifacts. `make public-check` verifies the source package shape and install
dry-runs.
