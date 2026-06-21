# Codex Reset Credit

`codex-reset-credit` is a read-only local skill for checking Codex reset credits
and local Codex rate-limit reset windows.

Source of truth:

```text
packages/codex-reset-credit
```

Public install targets:

```text
generated/claude/plugins/codex-reset-credit
generated/claude/custom-skills/codex-reset-credit
generated/codex/skills/codex-reset-credit
generated/agent-skills/codex-reset-credit
```

These public install targets are generated from `packages/codex-reset-credit`.
Edit the source package first, then run `make rebuild-generated`.

## Install

Claude Code marketplace install:

```text
/plugin marketplace add heyNag/agent-tools
/plugin install codex-reset-credit@agent-tools
```

After installing, try:

```text
/codex-reset-credit:codex-reset-credit
```

If your Claude Code version shows a different command name, run `/plugin list`
or `/plugin details codex-reset-credit@agent-tools`.

Codex install:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.codex/skills
rm -rf ~/.codex/skills/codex-reset-credit
cp -R generated/codex/skills/codex-reset-credit ~/.codex/skills/codex-reset-credit
```

Claude Desktop / claude.ai custom skill ZIP:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
make rebuild-generated
cd generated/claude/custom-skills
zip -r codex-reset-credit.zip codex-reset-credit
```

OpenCode install:

```sh
git clone https://github.com/heyNag/agent-tools.git
cd agent-tools
mkdir -p ~/.config/opencode/skills
rm -rf ~/.config/opencode/skills/codex-reset-credit
cp -R generated/agent-skills/codex-reset-credit ~/.config/opencode/skills/codex-reset-credit
```

`generated/agent-skills/codex-reset-credit/SKILL.md` and
`generated/claude/custom-skills/codex-reset-credit/skill.md` are both generated
from `packages/codex-reset-credit/SKILL.md`.

Local development install from source:

```sh
./scripts/install-all.sh
```

## Design

The helper script:

1. Reads local Codex auth from `CODEX_HOME`, `~/.codex`, or Codex Desktop app
   support paths when available.
2. Calls the live Codex/ChatGPT reset-credit endpoint unless `--no-live` is set.
3. Reads local Codex session logs for the latest `token_count` rate-limit
   snapshot.
4. Emits either a concise text report or sanitized JSON.

It does not redeem credits, consume credits, modify Codex files, or write local
state.

The skill folder format is portable across agent surfaces, but the useful live
behavior needs access to local Codex auth/session state. It is most useful in
local agent shells such as Claude Code, Codex, or OpenCode. Hosted Claude custom
skill upload cannot read local Codex Desktop auth files on your machine.

## Usage

```sh
python3 packages/codex-reset-credit/scripts/check_reset_credits.py
python3 packages/codex-reset-credit/scripts/check_reset_credits.py --json
python3 packages/codex-reset-credit/scripts/check_reset_credits.py --no-live
python3 packages/codex-reset-credit/scripts/check_reset_credits.py --thread-id <thread-id>
```

## Evidence Boundary

- Reset-credit data comes from the live Codex/ChatGPT backend endpoint.
- Rate-limit windows come from local Codex session `token_count` events.
- Local snapshots may be stale if Codex has not emitted recent token-count
  events.

## Security

Never print access tokens, refresh tokens, account IDs, raw auth file contents,
credit IDs, email addresses, profile image URLs, or unredacted auth paths.

## Source Note

Keep changes for this package in `packages/codex-reset-credit`.
