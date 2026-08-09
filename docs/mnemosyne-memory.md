# mnemosyne-memory

`mnemosyne-memory` turns an already configured Mnemosyne MCP server into a
selective, project-aware continuity layer for coding agents.

It provides a disciplined lifecycle for:

- focused recall at the start of substantive work
- one stable project key and `[project:<key>]` attribution
- one concise handoff record per project, updated in place
- deduplicated durable preferences, decisions, constraints, and lessons
- correction or invalidation when current evidence supersedes memory
- sparse use of canonical slots and temporal triples

## Prerequisite

The target host must already expose Mnemosyne MCP tools. This skill does not
install Mnemosyne, bundle an MCP server, start a background service, select a
bank, or configure a model.

Upstream project:
[mnemosyne-oss/mnemosyne](https://github.com/mnemosyne-oss/mnemosyne)

## Source paths

```text
packages/mnemosyne-memory
packages/mnemosyne-memory/skills/mnemosyne-memory
```

## Install targets

- Claude Code: `/plugin install mnemosyne-memory@charms`
- Agent Skills hosts: `npx skills add heyNag/charms --skill mnemosyne-memory`
- Codex/OpenCode: copy the portable skill folder or use a supported installer
- Cursor: root `skills/mnemosyne-memory` symlink through the plugin wrapper
- Claude Desktop: build or download the custom-skill artifact
- Skillshare: install the canonical source path with `--track`

Skillshare command:

```sh
skillshare install heyNag/charms/packages/mnemosyne-memory/skills/mnemosyne-memory --track
skillshare sync
```

## Automatic use

Implicit matching can activate the skill, but deterministic lifecycle behavior
belongs in the applicable `AGENTS.md` or host instructions. Those instructions
should require `mnemosyne-memory` for substantive tasks and define the local
bank, privacy, and retention policy. The public skill intentionally contains no
profile names or machine-specific paths.

## Safety boundary

The automatic workflow is limited to focused recall and selective remember,
update, and invalidate operations. It never automatically runs consolidation,
import/export, synchronization, shared-surface writes, cleanup, deletion,
persona changes, cross-bank transfer, or broad maintenance.

Memory is a continuity aid, not an authority. Current repository files,
documentation, instructions, and verified live state win conflicts.

## Local development

```sh
make build-packages
make public-check
```
