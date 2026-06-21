# Agent Guidelines

Rules for future AI agents working in this repo:

- Preserve the high-level repo shape unless the user explicitly asks to change
  it.
- Keep package source under `packages/<name>` as the local skill/commands/plugin
  source of truth.
- Keep `mcp/watch-video` as a minimal deployable MCP placeholder until real MCP
  tools are explicitly requested.
- Do not create MCP gateways unless explicitly requested.
- Edit `packages/` first, then run `make rebuild-generated` when generated
  public outputs need to change.
- When adding a package, declare its targets in `packages/<name>/tool.json`.
  The package builders iterate manifests and create every target automatically.
  Do not add one-off generated package copies or Skillshare hub entries by hand.
- Treat `skillshare-hub.json` as generated discovery metadata. It is built from
  `packages/*/SKILL.md`, `packages/*/tool.json`, and
  `packages/*/plugin/plugin.json`.
- Keep package `SKILL.md` frontmatter tags aligned with `tool.json` tags.
  `make verify-skill-metadata` checks Skillshare-facing metadata.
- Follow `docs/adding-a-skill.md` for the full new-skill checklist.
- Follow `docs/updating-a-skill.md` for the skill release and user update
  process.
- Do not auto-release on ordinary pushes. Public skill releases go through the
  manual `Release Skill` GitHub Actions workflow, which uses UTC date-based
  package versions and creates the skill-scoped GitHub Release.
- Do not create release commits, release tags, or GitHub Releases by hand
  during normal development. Use the `Release Skill` workflow.
- Do not manually edit `packages/<name>/plugin/plugin.json` versions. CI rejects
  package version changes from non-release commits.
- Do not manually edit `generated/` or `.claude-plugin/` outputs unless the
  user explicitly asks for a generated-output-only change.
- Do not manually edit `skillshare-hub.json`.
- Keep skill source agent-agnostic when possible. Put Claude Code marketplace
  wrapping under generated Claude plugin output, and keep reusable workflow
  guidance in `packages/<name>/SKILL.md`.
- Document runtime assumptions honestly. A skill folder can be portable even
  when a helper script needs local binaries, local auth files, or shell access.
- Treat `packages/<name>/SOURCE.md` and generated `GENERATED.md` files as the
  ownership markers.
- Use `make verify-generated-clean` to confirm committed public outputs match
  package source and manifests.
- Do not move generated files into a new location as the final step. Remove
  `.claude-plugin/` and `generated/` with `make rebuild-generated` so the
  generated markers and headers are produced by the builder scripts.
- Use `make doctor` before live `watch-video` debugging when local dependencies
  or API key shape are uncertain.
- Prefer small, testable changes.
- Do not over-engineer or add frameworks without a clear need.
- Do not commit generated `.watch-video/` artifacts.
- Do not commit secrets.
- Do not print secrets.
- For `codex-reset-credit`, never print Codex access tokens, refresh tokens,
  account IDs, raw auth contents, credit IDs, email addresses, profile image
  URLs, or unredacted auth paths.
- For `x-bookmarks`, never print X/Twitter cookies, OAuth access tokens,
  refresh tokens, client secrets, raw auth files, bookmark exports, or search
  indexes.
- Keep CI offline and no-secret.
- Add or update tests for behavior changes.
- Update docs when architecture, workflow, install behavior, or security
  practice changes.
- Keep install scripts idempotent and safe. They should not clobber unrelated
  user files.

## Before Committing

Run:

```sh
make doctor  # watch-video preflight
make test
make syntax
make mcp-build
make rebuild-generated
make build-skillshare-hub
make verify-skill-metadata
make verify-packages
make audit-generated
make verify-generated-clean
git status
```

Then verify:

- No real API keys are staged.
- `.env.local` is ignored and untracked.
- No `.watch-video/` run artifacts are staged.
- No `.x-bookmarks/` local state, X/Twitter tokens, bookmark exports, search
  indexes, SQLite databases, or Bird config copies are staged.
- No `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, or `__pycache__/`
  artifacts are staged.
- The commit message describes the change plainly.
