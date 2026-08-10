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

This directory is an [Agent Plugins v1](https://agent-plugins.org/specification)
plugin root. A compatible client with Agent Skills support loads `plugin.json`
here and discovers the skill from the standard fixed location:

```text
skills/codex-reset-credit
```

The plugin is independently versioned. Installation and update behavior is
defined by the client loading this package.

## Usage

From the plugin root:

```sh
python3 skills/codex-reset-credit/scripts/check_reset_credits.py --no-live
```

From the skill folder:

```sh
cd skills/codex-reset-credit
python3 scripts/check_reset_credits.py
```

Useful options:

```sh
python3 scripts/check_reset_credits.py --json
python3 scripts/check_reset_credits.py --no-live
python3 scripts/check_reset_credits.py --thread-id THREAD_ID
python3 scripts/check_reset_credits.py --session-file /absolute/path/to/rollout.jsonl
python3 scripts/check_reset_credits.py --timezone UTC
```

## Evidence Boundary

- Reset-credit data comes from the live Codex/ChatGPT backend endpoint.
- Rate-limit windows come from local Codex session `token_count` events.
- Local session snapshots may be stale if Codex has not emitted recent usage
  events.

## Portable package files

```text
plugin.json                                      Agent Plugins v1 manifest
LICENSE                                          MIT license terms
README.md                                        usage and safety guidance
skills/codex-reset-credit/SKILL.md               skill instructions
skills/codex-reset-credit/scripts/               read-only helper CLI
```

## Development

In a Charms source checkout, run the package tests from the repository root:

```sh
python3 -m unittest discover -s packages/codex-reset-credit/tests -p 'test_*.py'
```
