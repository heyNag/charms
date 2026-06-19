# Architecture

`agent-tools` is a personal agent tooling workspace for local skills, commands,
plugins, helper scripts, and future MCP servers.

The current shape is intentionally small:

```text
packages/             local skills, commands, and Claude/Codex-facing packages
mcp/                  deployable MCP server shapes, one folder per MCP server
scripts/              install, test, sync, and helper scripts
.github/workflows/    CI
docs/                 orientation and project memory
```

## Packages

`packages/` is for local agent-facing source of truth. Packages can include
skills, commands, plugin metadata, helper scripts, and tests.

The current package is:

```text
packages/watch-video
```

`packages/watch-video` owns the local `watch-video` skill, commands, plugin
metadata, Python scripts, and tests. Edit source files there first.

## MCP

`mcp/` is for deployable MCP server shapes. Each MCP server should live in its
own folder and be independently buildable and deployable later, ideally with its
own `Dockerfile`.

The current MCP placeholder is:

```text
mcp/watch-video
```

It is a minimal TypeScript MCP server skeleton. It currently exposes a status
tool only. It does not wrap video processing yet.

## No Gateway

There is no MCP gateway for now. Do not add a gateway, router, proxy, or shared
MCP control plane unless explicitly requested. Keep MCP folders independently
understandable and deployable.

## Source Of Truth

Repo source paths are authoritative:

- Edit packages under `packages/`.
- Edit MCP server source under `mcp/`.
- Edit install and test helpers under `scripts/`.
- Edit project memory under `docs/`.

Install scripts copy repo source into local Claude/Codex folders. Those installed
copies are runtime copies, not source of truth. Do not manually edit installed
copies and treat them as canonical. Change the repo source and rerun the install
script instead.
