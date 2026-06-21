# Decisions

Architecture decisions for `agent-tools`.

## Repository Scope

Use `agent-tools` as the repo name and scope. The repo holds skills, commands,
plugins, helper scripts, generated public install targets, and future MCP
server shapes.

## Package Incubator

Use this repo as a small package incubator. Packages live under
`packages/<name>` while their shape is shared across agent surfaces. A package
can graduate to a standalone repo later if separate release management becomes
useful.

## Package And MCP Separation

Keep local package source under `packages/<name>` and MCP server source under
`mcp/<name>`. Local skill/script packages should not be forced into server
architecture.

## No MCP Gateway

Do not build an MCP gateway, router, proxy, or shared control plane unless the
user explicitly asks for it. MCP folders should remain independently
understandable and deployable.

## Generated Public Outputs

Commit generated public install outputs under `generated/` and
`.claude-plugin/`, plus generated discovery metadata such as
`skillshare-hub.json`. Source still lives under `packages/`; generated outputs
are rebuilt from scratch with `make rebuild-generated` and checked with
`make verify-skill-metadata`, `make verify-packages`, `make audit-generated`, and
`make verify-generated-clean`.

## Optional Skillshare Discovery

Keep Skillshare discovery source-first. The root `.skillignore` hides
`generated/` during Skillshare install/discovery, while `skillshare-hub.json`
provides a curated Hub index that resolves only to canonical `packages/<name>`
source paths. The hub uses `sourcePath: heyNag/agent-tools/packages` plus
relative package names. GitHub Code Search may still show every committed
`SKILL.md`; the repo's optional Skillshare path is Hub mode or direct
`heyNag/agent-tools/packages/<name>` install for users who already use
Skillshare.

Skillshare-facing names, descriptions, and tags must be present in canonical
`packages/<name>/SKILL.md` frontmatter. `tool.json` still declares build
targets, public status, and tags for repo automation. `make
verify-skill-metadata` keeps the two source files and the generated hub index
aligned.

## Package Manifests

Use `packages/<name>/tool.json` to declare public status, install targets, and
MCP presence. This keeps build and verification scripts generic without adding a
package framework. Use `packages/<name>/SKILL.md` frontmatter for the
agent-visible name, description, argument hint, and Skillshare search tags.

## Manual Skill Releases

Ordinary pushes and pull requests verify the repo but do not release skills.
Public skill releases use the manual `Release Skill` GitHub Actions workflow.
The workflow computes a UTC date-based package version, updates
`packages/<name>/plugin/plugin.json`, rebuilds generated outputs for Claude
Code, Claude Desktop, Codex, and OpenCode, verifies them, commits, and pushes
the release commit. Local scripts may preview the next version with `--dry-run`,
but write-mode version bumps are reserved for that workflow. CI rejects package
plugin version changes from non-release commits.

The workflow also creates a skill-scoped GitHub Release with a tag named
`<skill>@<version>`, such as `watch-video@YYYY.M.D`. GitHub Packages are
intentionally unused until there is a real package artifact such as an npm
package, Docker image, binary, or MCP container to publish. GitHub may still
show the newest skill release as the repo's `Latest` release; that label is a
GitHub UI artifact, not a repo-wide version.

## Agent-Agnostic Skill Bundles

Build install targets for each supported agent surface from package source:

```text
generated/claude/plugins/<name>
generated/claude/custom-skills/<name>
generated/codex/skills/<name>
generated/agent-skills/<name>
```

`SKILL.md` and lowercase `skill.md` are generated into separate output folders
so case-insensitive filesystems do not collapse them into the same file.

## Watch Video Defaults

`watch-video` uses Groq `whisper-large-v3-turbo` as the default transcription
fallback, prefers native captions before paid transcription, uses OpenAI
`whisper-1` when `--transcriber openai` is requested, and keeps frame extraction
bounded with automatic budgeting and hard caps.

## Codex Reset Credit Safety

`codex-reset-credit` is read-only. It may inspect local Codex auth/session state
and the reset-credit endpoint, but it must not redeem credits, modify Codex
state, print secrets, or expose raw account/auth data.

## X Bookmarks Backends

`x-bookmarks` prefers Bird cookie auth because it uses the user's local browser
session and avoids paid X API credits. X API v2 remains an optional official
path for users who explicitly want API-backed bookmark fetches or folder
behavior. Both backends must keep tokens, cookies, bookmark exports, and search
indexes out of the repo and out of generated install packages.
