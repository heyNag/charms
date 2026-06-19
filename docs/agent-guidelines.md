# Agent Guidelines

Rules for future AI agents working in this repo:

- Preserve the high-level repo shape unless the user explicitly asks to change
  it.
- Keep `packages/watch-video` as the local skill/commands/plugin source of
  truth.
- Keep `mcp/watch-video` as a minimal deployable MCP placeholder until real MCP
  tools are explicitly requested.
- Do not create MCP gateways unless explicitly requested.
- Edit `packages/` first, then run `make build-packages`.
- Do not manually edit `plugins/` or `codex/` outputs unless the user explicitly
  asks for a generated-output-only change.
- Use `make verify-generated-clean` to confirm committed public outputs match
  package source and manifests.
- Use `make doctor` before live `watch-video` debugging when local dependencies
  or API key shape are uncertain.
- Prefer small, testable changes.
- Do not over-engineer or add frameworks without a clear need.
- Do not commit generated `.watch-video/` artifacts.
- Do not commit secrets.
- Do not print secrets.
- Keep CI offline and no-secret.
- Add or update tests for behavior changes.
- Update docs when architecture, workflow, install behavior, or security
  practice changes.
- Keep install scripts idempotent and safe. They should not clobber unrelated
  user files.

## Before Committing

Run:

```sh
make doctor
make test
make syntax
make mcp-build
make build-packages
make verify-packages
make verify-generated-clean
git status
```

Then verify:

- No real API keys are staged.
- `.env.local` is ignored and untracked.
- No `.watch-video/` run artifacts are staged.
- No `node_modules/`, `dist/`, `.venv/`, `.pytest_cache/`, or `__pycache__/`
  artifacts are staged.
- The commit message describes the change plainly.
