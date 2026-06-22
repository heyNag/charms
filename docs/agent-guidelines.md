# Agent Guidelines

Rules for future AI agents working in this repo:

- Preserve the source-only package shape unless explicitly asked to change it.
- Keep package source under `packages/<name>`.
- Keep source skills under `packages/<name>/skills/<name>/`.
- Keep each package's Claude plugin manifest at
  `packages/<name>/.claude-plugin/plugin.json`.
- Do not recreate a committed `generated/` target-copy tree.
- Use `.dist/` only for ignored local artifacts such as Claude custom-skill ZIP
  sources.
- Do not create MCP gateways unless explicitly requested.
- Do not add placeholder MCP folders. Add `mcp/<name>` only when real MCP tools
  are explicitly requested.
- When adding a package, declare targets in `packages/<name>/tool.json`; the
  scripts iterate manifests.
- Treat `.claude-plugin/marketplace.json`, `skillshare-hub.json`, `skills/`,
  and `commands/` as maintained indexes. Refresh them with `make build-packages`.
- Do not edit through root `skills/` or `commands/` symlinks. Edit
  `packages/<name>` source files instead.
- Keep skill frontmatter tags aligned with `tool.json` tags.
- Do not manually edit package versions. Public skill releases go through the
  manual GitHub Actions `Release Skill` workflow with the package name as the
  workflow input.
- Keep skills agent-agnostic when possible. Put target-specific details in
  docs or target wrappers.
- Do not commit secrets, local auth files, media, transcripts, frames, `.dist/`,
  caches, virtualenvs, or `node_modules`.
- Keep CI no-secret and no-live-network beyond normal dependency setup.
- Add or update tests for behavior changes.
- Update docs when architecture, workflow, install behavior, or security
  practice changes.
- Keep install scripts idempotent and safe.

## Before Committing

Run:

```sh
make build-packages
make public-check
make release-dry-run SKILL=<name>   # only when preparing a release
git status
```

Then verify:

- No real API keys are staged.
- `.env.local` is ignored and untracked.
- No `.watch-video/` or `.x-bookmarks/` state is staged.
- Privacy-sensitive review packets or ChatGPT responses are not staged unless
  they are intentional public fixtures.
- No `.dist/`, media, transcripts, frames, caches, `.venv/`, or `node_modules/`
  are staged.
- `.claude-plugin/marketplace.json`, `skillshare-hub.json`, `skills/`, and
  `commands/` match package source.
