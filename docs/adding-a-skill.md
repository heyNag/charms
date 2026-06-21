# Adding A Skill

Use this guide when adding a new public skill package to `agent-tools`.

The short version:

```text
Edit packages/<name>/ only.
Declare targets once in packages/<name>/tool.json.
Run make rebuild-generated.
Validate generated outputs.
Commit source and generated outputs together.
```

Do not manually create or edit files under `generated/` or `.claude-plugin/`.
Those paths are rebuilt from package source.

## What Gets Generated

One source package can produce every public target this repo supports:

```text
packages/<name>/                         source of truth
generated/claude/plugins/<name>/         Claude Code plugin package
generated/claude/custom-skills/<name>/   Claude Desktop / claude.ai custom skill ZIP source
generated/codex/skills/<name>/           Codex skill package
generated/agent-skills/<name>/           OpenCode / generic SKILL.md package
.claude-plugin/marketplace.json          Claude Code marketplace catalog
```

The generator decides what to build from `packages/<name>/tool.json`.

Use this target set for a normal agent-agnostic skill:

```json
{
  "name": "my-skill",
  "description": "One sentence describing what the skill does.",
  "targets": ["claude", "codex", "generic"],
  "surfaces": ["claude-code", "claude-desktop", "codex", "opencode"],
  "agent_agnostic": true,
  "has_mcp": false,
  "public": true
}
```

With those targets, `make rebuild-generated` builds every target listed above.

## Package Shape

Start with this source layout:

```text
packages/<name>/
  README.md                 required
  SKILL.md                  required
  SOURCE.md                 required ownership note
  tool.json                 required package manifest
  plugin/
    plugin.json             recommended for Claude Code metadata
  agents/
    openai.yaml             recommended display metadata
  commands/
    <name>.md               optional Claude Code slash command
  scripts/
    ...                     optional helper scripts
  references/
    ...                     optional docs loaded only when needed
  tests/
    test_basic.py           recommended offline tests
```

Only create optional folders when they help the skill. The builders copy
`scripts/`, `references/`, `agents/`, and `commands/` automatically when they
exist.

## Step 1: Pick The Name

Use a short lowercase hyphenated name:

```text
watch-video
codex-reset-credit
x-bookmarks
my-new-skill
```

Rules:

- Use lowercase letters, digits, and hyphens.
- Keep the folder name, `tool.json` name, plugin name, and SKILL frontmatter
  name identical.
- Prefer a clear verb or task phrase.
- Do not rename generated outputs by hand.

## Step 2: Create The Source Folder

Create only the source package:

```sh
mkdir -p packages/my-skill/{agents,commands,plugin,references,scripts,tests}
```

For instruction-only skills, omit folders you do not need:

```sh
mkdir -p packages/my-skill/{agents,plugin,tests}
```

Do not create these manually:

```text
generated/claude/plugins/my-skill
generated/claude/custom-skills/my-skill
generated/codex/skills/my-skill
generated/agent-skills/my-skill
```

The build scripts create them.

## Step 3: Add `tool.json`

Create `packages/my-skill/tool.json`:

```json
{
  "name": "my-skill",
  "description": "Describe the skill in one public-facing sentence.",
  "targets": ["claude", "codex", "generic"],
  "surfaces": ["claude-code", "claude-desktop", "codex", "opencode"],
  "agent_agnostic": true,
  "has_mcp": false,
  "public": true
}
```

Target meanings:

- `claude` builds `generated/claude/plugins/<name>` and adds the marketplace
  entry.
- `codex` builds `generated/codex/skills/<name>`.
- `generic` builds `generated/agent-skills/<name>` and
  `generated/claude/custom-skills/<name>`.

Set `has_mcp` to `true` only when an MCP folder exists or is intentionally part
of the package plan. Do not add an MCP gateway.

## Step 4: Add Claude Plugin Metadata

Create `packages/my-skill/plugin/plugin.json`:

```json
{
  "name": "my-skill",
  "version": "0.1.0",
  "description": "Describe the skill in one public-facing sentence.",
  "author": {
    "name": "Nagarjuna Boddu"
  },
  "repository": "https://github.com/heyNag/agent-tools",
  "license": "MIT"
}
```

The marketplace generator uses this file for the Claude Code plugin entry. If
the file is missing, the builder creates basic defaults from `tool.json`, but
explicit metadata is clearer.

## Step 5: Add Agent UI Metadata

Create `packages/my-skill/agents/openai.yaml`:

```yaml
interface:
  display_name: "My Skill"
  short_description: "Do the useful thing"
  default_prompt: "Use $my-skill to do the useful thing."

policy:
  allow_implicit_invocation: true
```

Use a human-readable display name here. Keep the internal package name crisp and
hyphenated.

## Step 6: Write `SKILL.md`

Create `packages/my-skill/SKILL.md`:

~~~markdown
---
name: my-skill
description: Describe what the skill does and when agents should use it. Include trigger phrases and task contexts here.
argument-hint: "[optional args]"
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---

# my-skill

Use this skill when ...

## Operating Rules

- Keep the rules short and actionable.
- Do not print secrets.
- Prefer local, deterministic helpers when available.

## Invocation

```sh
python3 scripts/example.py --help
```

## Response Shape

Unless the user asks for a narrower format, return:

1. Direct answer
2. Evidence or source used
3. Caveats and next action

## Failure Handling

- Missing dependency: give a concrete fix command.
- Missing auth: explain the safe setup path without exposing secrets.
~~~

Guidelines:

- Put trigger wording in the frontmatter `description`; agents see it before
  loading the full skill.
- Keep the body concise.
- Move detailed backend docs, schemas, API notes, and long examples into
  `references/`.
- Keep scripts executable and testable.
- Never include real secrets or local machine state.

## Step 7: Add `README.md`

Create `packages/my-skill/README.md` for humans browsing the repo:

~~~markdown
# my-skill

`my-skill` does ...

Source lives under `packages/my-skill`.

Generated install targets:

```text
generated/claude/plugins/my-skill
generated/claude/custom-skills/my-skill
generated/codex/skills/my-skill
generated/agent-skills/my-skill
```

Edit source first, then run:

```sh
make rebuild-generated
make verify-packages
make audit-generated
make verify-generated-clean
```
~~~

Keep package README content current and practical. Do not describe generated
folders as source.

## Step 8: Add `SOURCE.md`

Create `packages/my-skill/SOURCE.md`:

~~~markdown
# Source Package

This directory is the source of truth for `my-skill`.

Edit files here first:

- `SKILL.md`
- `README.md`
- `agents/`
- `commands/`
- `plugin/plugin.json`
- `references/`
- `scripts/`
- `tests/`
- `tool.json`

After changing package source, run:

```sh
make rebuild-generated
make verify-packages
make audit-generated
make verify-generated-clean
```

This source directory generates these public install copies:

```text
packages/my-skill -> generated/claude/plugins/my-skill
packages/my-skill -> generated/claude/custom-skills/my-skill
packages/my-skill -> generated/codex/skills/my-skill
packages/my-skill -> generated/agent-skills/my-skill
```

Generated Markdown, Python, shell, and YAML files include in-file notices that
point back to the source paths in this package. Generated JSON and LICENSE files
are covered by the nearest `GENERATED.md` marker.
~~~

Remove optional folders from the list if the package does not have them.

## Step 9: Add Optional Commands

Claude Code commands live in `packages/my-skill/commands/` and are copied only
into the generated Claude Code plugin target.

Example `packages/my-skill/commands/my-skill.md`:

```markdown
---
description: Run my-skill.
argument-hint: "[args]"
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: my-skill command -->

Use the `my-skill` skill with the user's arguments: $ARGUMENTS

Run scripts from the installed `my-skill` skill, or
`packages/my-skill/scripts/` when working from this repository.
```

Commands are optional. Do not add commands for other targets by hand.

## Step 10: Add Scripts And References

Use `scripts/` for deterministic helpers:

```text
packages/my-skill/scripts/example.py
packages/my-skill/scripts/example.sh
```

Use `references/` for detail the agent should load only when needed:

```text
packages/my-skill/references/backend.md
packages/my-skill/references/api.md
```

Rules:

- Scripts should use safe subprocess calls and clear errors.
- Scripts should avoid network or secrets in tests unless explicitly manual.
- References should be current-state docs, not history logs.
- Do not duplicate long reference content in `SKILL.md`.

## Step 11: Add Offline Tests

Create `packages/my-skill/tests/test_basic.py`.

Good tests:

- Import scripts.
- Test pure helper functions.
- Test parsing, path handling, and safe error messages.
- Avoid live network calls.
- Avoid real API keys or local auth files.

Run:

```sh
make test
make syntax
```

## Step 12: Rebuild Every Target

Run the clean generation flow:

```sh
make rebuild-generated
```

This deletes and recreates only:

```text
.claude-plugin/
generated/
```

It then rebuilds every public package from `packages/*/tool.json`.

Expected new outputs for `my-skill`:

```text
generated/claude/plugins/my-skill
generated/claude/custom-skills/my-skill
generated/codex/skills/my-skill
generated/agent-skills/my-skill
```

Do not patch generated output if something is wrong. Fix the source package or
builder script, then run `make rebuild-generated` again.

## Step 13: Verify

Run:

```sh
make test
make syntax
make mcp-build
make rebuild-generated
make verify-packages
make audit-generated
make verify-generated-clean
git diff --check
git status
```

What each check catches:

- `make test`: package unit tests.
- `make syntax`: Python and shell syntax.
- `make mcp-build`: existing MCP placeholder still builds.
- `make verify-packages`: target folders, marketplace JSON, plugin metadata,
  and forbidden files.
- `make audit-generated`: generated files match source paths after stripping
  generated notices.
- `make verify-generated-clean`: a clean rebuild does not change committed
  generated outputs.
- `git diff --check`: whitespace mistakes.
- `git status`: staged/untracked review.

If Claude CLI is available, also run:

```sh
claude plugin validate .
claude plugin validate generated/claude/plugins/my-skill
```

## Step 14: Update Docs

Update docs when adding a public skill:

- Root `README.md`: add the skill to public tools and install examples when
  appropriate.
- `docs/README.md`: add the package docs page to the reading order.
- `docs/architecture.md`: add the package to the package list and edit map.
- `docs/agent-compatibility.md`: mention runtime requirements if the skill
  needs local auth, local binaries, or network.
- `docs/roadmap.md`: mention the package only if it changes direction or scope.
- `docs/security.md`: add any package-specific secret or artifact rules.
- `docs/<name>.md`: add a package-specific docs page for public tools.

Keep docs latest-state only. Avoid origin notes, migration notes, or old
package names.

## Step 15: Commit

Before committing:

```sh
git status
git diff --cached --check
```

Confirm:

- Source files under `packages/<name>/` are staged.
- Generated outputs under `generated/` and `.claude-plugin/` are staged.
- Docs are staged.
- No `.env.local`, secrets, local auth state, generated run artifacts, media,
  caches, `node_modules/`, `dist/`, or `.venv/` files are staged.

Then commit:

```sh
git commit -m "Add my-skill package"
git push
```

## Troubleshooting

Generated output is missing:

```text
Check packages/<name>/tool.json.
public must be true, and targets must include claude, codex, or generic.
```

Marketplace entry is missing:

```text
The package needs "public": true and "claude" in targets.
Run make rebuild-generated.
```

Generated files are stale:

```sh
make rebuild-generated
make audit-generated
make verify-generated-clean
```

A generated file needs a wording fix:

```text
Edit the matching source file under packages/<name>/.
If the wording is in GENERATED.md or generated notices, edit the builder script.
Run make rebuild-generated again.
```

Tests need live credentials:

```text
Do not put those tests in CI.
Keep CI no-secret and offline.
Add helper tests for pure behavior instead.
Document live verification as manual/local.
```

The skill needs an MCP server:

```text
Add mcp/<name> only when a real MCP surface is needed.
Keep it independently deployable.
Do not add an MCP gateway.
```

## Final Checklist

- `packages/<name>/tool.json` declares `targets`: `claude`, `codex`, `generic`.
- `packages/<name>/SKILL.md` has clear trigger text in `description`.
- `packages/<name>/agents/openai.yaml` has display metadata.
- `packages/<name>/README.md` explains source and generated targets.
- `packages/<name>/SOURCE.md` points future edits to source paths.
- Optional `scripts/`, `references/`, and `commands/` are useful and tested.
- Package-specific docs and security notes are updated.
- `make rebuild-generated` creates every target.
- `make verify-packages`, `make audit-generated`, and
  `make verify-generated-clean` pass.
- Generated files are committed with source changes.
- No secrets or local artifacts are committed.
