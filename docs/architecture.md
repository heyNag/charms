# Architecture

`agent-tools` is a public agent tooling workspace for local skills, commands,
plugins, helper scripts, generated public install packages, and future MCP
servers.

The repo shape is intentionally small:

```text
packages/             local skills, commands, and package source
generated/            generated Claude/Codex/OpenCode packages, committed for public install
.claude-plugin/       generated Claude Code marketplace catalog
skillshare-hub.json   optional generated Skillshare hub index
mcp/                  deployable MCP server shapes, one folder per MCP server
scripts/              install, test, sync, and helper scripts
.github/workflows/    CI
docs/                 orientation and project memory
```

`generated/` includes Claude Code plugin packages, Claude custom-skill upload
folders, Codex skill folders, and OpenCode/generic Agent Skill folders.
Target runtime differences and action-to-tool mapping live in
`docs/target-tool-mapping.md`.

## Packages

`packages/` is the source of truth for agent-facing tools. A package can include
skills, commands, plugin metadata, helper scripts, references, agent UI metadata,
and tests.

Packages in this repo:

```text
packages/codex-reset-credit
packages/watch-video
packages/x-bookmarks
```

`packages/watch-video` owns the `watch-video` skill, commands, plugin metadata,
Python scripts, docs, and tests. Its script surface includes local preflight,
video watching, frame extraction, and transcription helpers.

`packages/codex-reset-credit` owns the `codex-reset-credit` skill, command,
plugin metadata, Python helper, docs, and tests. It is read-only and checks
Codex reset credits plus local Codex rate-limit windows without exposing auth
secrets.

`packages/x-bookmarks` owns the `x-bookmarks` skill, command, plugin metadata,
agent UI metadata, backend references, scripts, docs, and tests. It fetches,
searches, and digests X/Twitter bookmarks through Bird cookie auth or optional
X API v2 OAuth state.

Every public package declares its distribution behavior in:

```text
packages/<name>/tool.json
```

Public packages:

```text
watch-video
codex-reset-credit
x-bookmarks
```

## Public Distribution

`generated/`, `.claude-plugin/`, and `skillshare-hub.json` are generated from
`packages/`, but they are committed as public install targets or discovery
metadata so users and agents can install without understanding the source
workspace layout.

```text
.claude-plugin/marketplace.json       generated Claude Code marketplace catalog
skillshare-hub.json                   optional generated Skillshare hub index
generated/claude/plugins/<name>       Claude Code plugin package
generated/claude/custom-skills/<name> Claude Desktop / claude.ai custom skill ZIP source
generated/codex/skills/<name>         Codex skill package
generated/agent-skills/<name>         OpenCode and generic SKILL.md Agent Skills package
```

Do not manually edit generated public outputs during normal development. Edit
`packages/<name>` first, then rebuild generated outputs from source:

```sh
make rebuild-generated
make public-check
```

`make rebuild-generated` removes only the committed generated output roots
`.claude-plugin/` and `generated/`, then recreates them from `packages/`. The
same build also rewrites `skillshare-hub.json` from package manifests and
`SKILL.md` frontmatter. Use it whenever package source, generator templates,
generated notices, or public distribution paths change. Do not move generated
files into place manually.

Packages follow the same manifest pattern:

- `packages/<name>/tool.json` declares `public`, `targets`, supported surfaces,
  and whether an MCP placeholder exists.
- `generated/claude/plugins/<name>` exists when the package targets Claude Code.
- `generated/claude/custom-skills/<name>` exists when the package targets
  generic Agent Skills upload surfaces such as Claude custom skills.
- `generated/codex/skills/<name>` exists when the package targets Codex.
- `generated/agent-skills/<name>` exists when the package targets generic
  `SKILL.md` Agent Skills consumers such as OpenCode.
- `skillshare-hub.json` lists public agent-compatible packages for optional
  Skillshare Hub search. It uses `sourcePath: heyNag/agent-tools/packages`
  plus each relative package name so Skillshare resolves entries to
  `heyNag/agent-tools/packages/<name>`.
- `mcp/<name>` exists only when the package needs an MCP server shape.

## MCP

`mcp/` is for deployable MCP server shapes. Each MCP server lives in its own
folder and should be independently buildable and deployable, ideally with its
own `Dockerfile`.

MCP placeholder:

```text
mcp/watch-video
```

It is a minimal TypeScript MCP server skeleton. It exposes a status tool only
and does not wrap video processing.

Future `watch-video` MCP work should add real tools only after the local package
surface is stable. Candidate tools include `video_info`, `video_analyze`,
`video_watch`, and `video_detail`. Keep them inside `mcp/watch-video`.

## No Gateway

There is no MCP gateway. Do not add a gateway, router, proxy, or shared MCP
control plane unless explicitly requested. Keep MCP folders independently
understandable and deployable.

There is also no session-start bootstrap or global auto-trigger layer today.
Current packages are task/domain tools invoked by users, native skill discovery,
or agent judgment. Do not add global bootstrap hooks or mutate target runtime
config unless explicitly requested.

## Source Of Truth

Repo source paths are authoritative:

- Edit packages under `packages/`.
- Regenerate public outputs under `generated/` and `.claude-plugin/` from packages.
- Regenerate `skillshare-hub.json` from package manifests and `SKILL.md`
  frontmatter.
- Edit MCP server source under `mcp/`.
- Edit install and test helpers under `scripts/`.
- Edit project memory under `docs/`.

Install scripts copy repo source into local Claude/Codex folders. Those
installed copies are runtime copies, not source of truth. Do not manually edit
installed copies or treat them as canonical. Change the repo source and rerun
the install script instead.

## Edit Map

Use this map when deciding where a change belongs. The left side is the source
to edit; the right side is generated or installed from that source.

```text
Edit: packages/watch-video/             source package
Edit: packages/codex-reset-credit/      source package
Edit: packages/x-bookmarks/             source package
Edit: mcp/watch-video/                  MCP placeholder source
Edit: scripts/                          build, install, and verification helpers
Edit: docs/                             project memory and guidance
Source: packages/watch-video/                              -> generated/claude/plugins/watch-video/
Source: packages/watch-video/                              -> generated/claude/custom-skills/watch-video/
Source: packages/watch-video/                              -> generated/codex/skills/watch-video/
Source: packages/watch-video/                              -> generated/agent-skills/watch-video/
Source: packages/codex-reset-credit/                       -> generated/claude/plugins/codex-reset-credit/
Source: packages/codex-reset-credit/                       -> generated/claude/custom-skills/codex-reset-credit/
Source: packages/codex-reset-credit/                       -> generated/codex/skills/codex-reset-credit/
Source: packages/codex-reset-credit/                       -> generated/agent-skills/codex-reset-credit/
Source: packages/x-bookmarks/                              -> generated/claude/plugins/x-bookmarks/
Source: packages/x-bookmarks/                              -> generated/claude/custom-skills/x-bookmarks/
Source: packages/x-bookmarks/                              -> generated/codex/skills/x-bookmarks/
Source: packages/x-bookmarks/                              -> generated/agent-skills/x-bookmarks/
Source: packages/*/tool.json and packages/*/plugin/        -> .claude-plugin/
Source: packages/*/SKILL.md, packages/*/tool.json, and packages/*/plugin/ -> skillshare-hub.json
```

Generated directories are committed for public installation, but they are
downstream copies. Each generated package contains a `GENERATED.md` marker.
Generated Markdown, Python, shell, and YAML files also include in-file generated
notices when comments are safe. JSON and LICENSE files are covered by the
nearest `GENERATED.md` marker when the file format should not carry extra
comments. The source package contains `SOURCE.md`. Generated markers list the
exact source paths to edit for each generated file or directory.
