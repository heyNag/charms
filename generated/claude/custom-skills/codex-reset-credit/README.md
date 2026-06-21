<!-- BEGIN GENERATED FROM SOURCE: packages/codex-reset-credit/README.md -->
<!-- Do not edit directly; edit the source path and run make rebuild-generated. -->
<!-- END GENERATED FROM SOURCE -->

# codex-reset-credit

`codex-reset-credit` is a read-only local skill for checking Codex reset-credit
status and local Codex rate-limit reset windows.

It can:

- call the live Codex/ChatGPT reset-credit endpoint using local Codex auth
- read local Codex session snapshots for rate-limit reset windows
- print a concise text report
- emit sanitized JSON with `--json`
- run local-only with `--no-live`

It must never print tokens, account IDs, raw auth file contents, or edit local
Codex files.

The skill folder format is portable across Claude Code, Claude Desktop, Codex,
OpenCode, and generic Agent Skills consumers. The live helper is local-runtime
dependent because it needs access to local Codex auth/session state.

## Source And Generated Outputs

Source lives under:

```text
packages/codex-reset-credit
```

Public install targets are generated from that source into:

```text
generated/claude/plugins/codex-reset-credit
generated/claude/custom-skills/codex-reset-credit
generated/codex/skills/codex-reset-credit
generated/agent-skills/codex-reset-credit
```

Optional Claude Desktop no-terminal packaging: paste
`https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/codex-reset-credit`
into `https://skill-compiler.statechange.ai/`, preview the files, download the
`.skill`, and import it in Claude Desktop.

Edit source first, then run:

```sh
make rebuild-generated
make verify-generated-clean
```

## Usage

Run package-local commands from `packages/codex-reset-credit/` or from an
installed skill folder unless the command shows a repo-root path.

From the source package directory, Codex install, or agent-generic install:

```sh
python3 scripts/check_reset_credits.py
```

From the generated Claude plugin package root, use the skill subdirectory:

```sh
python3 skills/codex-reset-credit/scripts/check_reset_credits.py
```

Useful options:

```sh
python3 scripts/check_reset_credits.py --json
python3 scripts/check_reset_credits.py --no-live
python3 scripts/check_reset_credits.py --thread-id <thread-id>
python3 scripts/check_reset_credits.py --session-file <absolute-path-to-rollout.jsonl>
python3 scripts/check_reset_credits.py --timezone UTC
```

## Evidence Boundary

- Reset-credit data comes from the live Codex/ChatGPT backend endpoint.
- Rate-limit windows come from local Codex session `token_count` events.
- Local session snapshots may be stale if Codex has not emitted recent usage
  events.

## Source Files

```text
SKILL.md                         # skill instructions for agents
scripts/check_reset_credits.py   # read-only helper CLI
commands/codex-reset-credit.md   # Claude command prompt
plugin/plugin.json               # Claude plugin metadata
tests/                           # offline helper tests
```

Keep edits in this package source directory.

Generated install packages contain a subset of those files:

- Claude plugin package: `README.md`, `LICENSE`, `.claude-plugin/plugin.json`,
  commands, and `skills/codex-reset-credit/`.
- Codex skill package: `README.md`, `LICENSE`, `SKILL.md`, and
  `scripts/`.
- Claude custom-skill package: `README.md`, `LICENSE`, lowercase `skill.md`,
  and `scripts/`.
- Agent-generic skill package: `README.md`, `LICENSE`, `SKILL.md`, and
  `scripts/`.
