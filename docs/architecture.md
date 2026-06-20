# Architecture

`agent-tools` is a public agent tooling workspace for local skills, commands,
plugins, helper scripts, and future MCP servers.

The current shape is intentionally small:

```text
packages/             local skills, commands, and Claude/Codex-facing packages
generated/            generated Claude/Codex packages, committed for public install
.claude-plugin/       generated Claude Code marketplace catalog
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
metadata, Python scripts, docs, and tests. Its script surface includes local
preflight, video watching, frame extraction, and transcription helpers. Edit
source files there first.

Each public package should declare its distribution targets in:

```text
packages/<name>/tool.json
```

For now, the only public package is `watch-video`.

## Public Distribution

`generated/` and `.claude-plugin/` are generated from `packages/`, but they are
committed as public install targets so users and agents do not need to understand
the source workspace layout.

```text
.claude-plugin/marketplace.json       generated Claude Code marketplace catalog
generated/claude/plugins/<name>       Claude Code plugin package
generated/codex/skills/<name>         Codex/generic skill package
```

Do not manually edit generated public outputs during normal development. Edit
`packages/<name>` first, then rebuild generated outputs from source:

```sh
make rebuild-generated
make verify-packages
make audit-generated
make verify-generated-clean
```

`make rebuild-generated` removes only the committed generated output roots
`.claude-plugin/` and `generated/`, then recreates them from `packages/`. Use it
whenever package source, generator templates, generated notices, or public
distribution paths change. Do not move generated files into place manually.

Future packages should follow the same manifest pattern:

- `packages/<name>/tool.json` declares `public`, `targets`, and whether an MCP
  placeholder exists.
- `generated/claude/plugins/<name>` exists only when the package targets Claude Code.
- `generated/codex/skills/<name>` exists only when the package targets Codex or generic skills.
- `mcp/<name>` exists only when the package needs an MCP server shape.

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

Future `watch-video` MCP work should add real tools only after the local package
surface is stable. Candidate tools include `video_info`, `video_analyze`,
`video_watch`, and `video_detail`. Keep them inside `mcp/watch-video`; do not
introduce a gateway.

## No Gateway

There is no MCP gateway for now. Do not add a gateway, router, proxy, or shared
MCP control plane unless explicitly requested. Keep MCP folders independently
understandable and deployable.

## Source Of Truth

Repo source paths are authoritative:

- Edit packages under `packages/`.
- Regenerate public outputs under `generated/` and `.claude-plugin/` from packages.
- Edit MCP server source under `mcp/`.
- Edit install and test helpers under `scripts/`.
- Edit project memory under `docs/`.

Install scripts copy repo source into local Claude/Codex folders. Those installed
copies are runtime copies, not source of truth. Do not manually edit installed
copies and treat them as canonical. Change the repo source and rerun the install
script instead.

## Edit Map

Use this map when deciding where a change belongs. The left side is the source
to edit; the right side is generated or installed from that source.

```text
Edit: packages/watch-video/             source package
Edit: mcp/watch-video/                  MCP placeholder source
Edit: scripts/                          build, install, and verification helpers
Edit: docs/                             project memory and guidance
Source: packages/watch-video/                              -> generated/claude/plugins/watch-video/
Source: packages/watch-video/                              -> generated/codex/skills/watch-video/
Source: packages/*/tool.json and packages/*/plugin/        -> .claude-plugin/
```

Generated directories are committed for public installation, but they are
downstream copies. Each generated package contains a `GENERATED.md` marker.
Generated Markdown and Python files also include in-file generated notices when
comments are safe. JSON and LICENSE files cannot safely carry comments, so they
are covered by the nearest `GENERATED.md` marker. The source package contains
`SOURCE.md`. Generated markers list the exact source paths to edit for each
generated file or directory.
