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

The package root is a Claude Code plugin source. The portable skill source is:

```text
packages/codex-reset-credit/skills/codex-reset-credit
```

Codex, Cursor, OpenCode, generic Agent Skills, and optional Skillshare installs
all use that same skill folder directly or through the root `skills/` symlink
index. Claude Desktop custom-skill ZIP contents are built locally under
`.dist/claude/custom-skills/codex-reset-credit`.

Install commands for each target live in
[docs/installing-skills.md](../../docs/installing-skills.md).

## Usage

From the repo root:

```sh
python3 packages/codex-reset-credit/skills/codex-reset-credit/scripts/check_reset_credits.py --no-live
```

From the skill folder:

```sh
cd packages/codex-reset-credit/skills/codex-reset-credit
python3 scripts/check_reset_credits.py
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

## Package Files

```text
.claude-plugin/plugin.json                       Claude Code plugin metadata
skills/codex-reset-credit/SKILL.md               skill instructions
skills/codex-reset-credit/scripts/               read-only helper CLI
commands/codex-reset-credit.md                   Claude Code slash command prompt
tests/                                           offline helper tests
tool.json                                        package manifest
```

After editing source:

```sh
make build-packages
make public-check
```
