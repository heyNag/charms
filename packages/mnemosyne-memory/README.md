# mnemosyne-memory

`mnemosyne-memory` teaches an agent to use an existing Mnemosyne MCP server as
a selective continuity layer across tasks and sessions. It performs focused
recall, deduplicates durable writes, corrects stale records, and maintains one
compact handoff per stable project.

The skill is deliberately not a transcript recorder. Repository files remain
authoritative, and broad or destructive Mnemosyne maintenance is outside its
automatic workflow.

## Prerequisite

Configure a Mnemosyne MCP server in the host before using this skill. The host
should expose `mnemosyne_*` recall and mutation tools. This package does not
install Mnemosyne, start a service, choose a memory bank, or bundle an MCP
server.

See the [Mnemosyne repository](https://github.com/mnemosyne-oss/mnemosyne) for
server installation and configuration.

## Install with Skillshare

```sh
skillshare install heyNag/charms/packages/mnemosyne-memory/skills/mnemosyne-memory --track
skillshare sync
```

The portable skill source is:

```text
packages/mnemosyne-memory/skills/mnemosyne-memory
```

Other target-specific install options are documented in
[docs/installing-skills.md](../../docs/installing-skills.md).

## Automatic use

The skill can be invoked explicitly or matched implicitly. For reliable
automatic continuity, add a short rule to the applicable `AGENTS.md` or host
instructions requiring `mnemosyne-memory` for substantive tasks. Keep
profile-specific bank selection, privacy rules, and retention policy in those
governing instructions rather than in this public skill.

The skill never hardcodes profile names or local paths. The configured MCP
launcher owns bank isolation.

## Safety model

Automatic behavior is limited to focused recall and selective remember,
update, or invalidate operations. The skill does not automatically run
consolidation, import/export, synchronization, shared-surface writes, hygiene
cleanup, deletion, persona changes, cross-bank transfer, or broad maintenance.

It excludes secrets, authentication material, raw transcripts, logs, command
output, and sensitive content whose persistence is not clearly authorized.

## Package files

```text
.claude-plugin/plugin.json                    Claude Code plugin metadata
skills/mnemosyne-memory/SKILL.md              portable skill instructions
skills/mnemosyne-memory/agents/openai.yaml    agent UI and MCP dependency metadata
tests/                                        offline package tests
tool.json                                     public package manifest
```

After editing source:

```sh
make build-packages
make public-check
```
