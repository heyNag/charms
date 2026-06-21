# Adding A Skill

Use this guide when adding a new public skill package to `agent-tools`.

The short version:

```text
Edit packages/<name>/ only.
Declare targets once in packages/<name>/tool.json.
Run make rebuild-generated.
Validate generated outputs.
Add the package name to the Release Skill workflow.
Keep SKILL.md tags aligned with tool.json tags.
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
skillshare-hub.json                      Skillshare hub index
```

The generator decides what to build from `packages/<name>/tool.json`.

Use this target set for a normal agent-agnostic skill:

```json
{
  "name": "awesome-skill",
  "description": "One sentence describing what the skill does.",
  "tags": ["awesome", "local"],
  "targets": ["claude", "codex", "generic"],
  "surfaces": ["claude-code", "claude-desktop", "codex", "opencode"],
  "agent_agnostic": true,
  "has_mcp": false,
  "public": true
}
```

With those targets, `make rebuild-generated` builds every target listed above.
It also regenerates `skillshare-hub.json`, so Skillshare Hub users can discover
the package from the canonical `packages/awesome-skill` source path.
Adding the package name to `.github/workflows/release-skill.yml` also makes it
available to the manual release/update workflow described in
[`updating-a-skill.md`](updating-a-skill.md).

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
awesome-skill
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
mkdir -p packages/awesome-skill/{agents,commands,plugin,references,scripts,tests}
```

For instruction-only skills, omit folders you do not need:

```sh
mkdir -p packages/awesome-skill/{agents,plugin,tests}
```

Do not create these manually:

```text
generated/claude/plugins/awesome-skill
generated/claude/custom-skills/awesome-skill
generated/codex/skills/awesome-skill
generated/agent-skills/awesome-skill
```

The build scripts create them.

## Step 3: Add `tool.json`

Create `packages/awesome-skill/tool.json`:

```json
{
  "name": "awesome-skill",
  "description": "Describe the skill in one public-facing sentence.",
  "tags": ["awesome", "local"],
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

`tags` are optional but recommended. They appear in `skillshare-hub.json` and
help Skillshare Hub search. For public skills in this repo, add the same tags
to `SKILL.md` frontmatter so Skillshare-style indexers can read the skill file
directly. Keep tags short, lowercase, and public-safe.

Set `has_mcp` to `true` only when an MCP folder exists or is intentionally part
of the package plan. Do not add an MCP gateway.

## Step 4: Add Claude Plugin Metadata

Create `packages/awesome-skill/plugin/plugin.json`:

```json
{
  "name": "awesome-skill",
  "version": "0.1.0",
  "description": "Describe the skill in one public-facing sentence.",
  "author": {
    "name": "Nagarjuna Boddu"
  },
  "repository": "https://github.com/heyNag/agent-tools",
  "license": "MIT"
}
```

`0.1.0` is a bootstrap version for the add-skill commit. The first public
release should use the manual `Release Skill` workflow, which replaces it with
the UTC date version described in `docs/updating-a-skill.md`.

The marketplace generator uses this file for the Claude Code plugin entry. If
the file is missing, the builder creates basic defaults from `tool.json`, but
explicit metadata is clearer.

## Step 5: Add Agent UI Metadata

Create `packages/awesome-skill/agents/openai.yaml`:

```yaml
interface:
  display_name: "Awesome Skill"
  short_description: "Do the awesome thing"
  default_prompt: "Use $awesome-skill to do the awesome thing."

policy:
  allow_implicit_invocation: true
```

Use a human-readable display name here. Keep the internal package name crisp and
hyphenated.

## Step 6: Write `SKILL.md`

Create `packages/awesome-skill/SKILL.md`:

~~~markdown
---
name: awesome-skill
description: Describe what the skill does and when agents should use it. Include trigger phrases and task contexts here.
argument-hint: "[optional args]"
tags: awesome, local
allowed-tools: Bash, Read
homepage: https://github.com/heyNag/agent-tools
repository: https://github.com/heyNag/agent-tools
author: Nagarjuna Boddu
license: MIT
user-invocable: true
---

# awesome-skill

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
- Keep frontmatter `tags` aligned with `packages/awesome-skill/tool.json`.
  `make verify-skill-metadata` checks this.
- Keep the body concise.
- Move detailed backend docs, schemas, API notes, and long examples into
  `references/`.
- Keep scripts executable and testable.
- Never include real secrets or local machine state.

## Step 7: Add `README.md`

Create `packages/awesome-skill/README.md` for humans browsing the repo:

~~~markdown
# awesome-skill

`awesome-skill` does ...

Source lives under `packages/awesome-skill`.

Generated install targets:

```text
generated/claude/plugins/awesome-skill
generated/claude/custom-skills/awesome-skill
generated/codex/skills/awesome-skill
generated/agent-skills/awesome-skill
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

Create `packages/awesome-skill/SOURCE.md`:

~~~markdown
# Source Package

This directory is the source of truth for `awesome-skill`.

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
packages/awesome-skill -> generated/claude/plugins/awesome-skill
packages/awesome-skill -> generated/claude/custom-skills/awesome-skill
packages/awesome-skill -> generated/codex/skills/awesome-skill
packages/awesome-skill -> generated/agent-skills/awesome-skill
```

Generated Markdown, Python, shell, and YAML files include in-file notices that
point back to the source paths in this package. Generated JSON and LICENSE files
are covered by the nearest `GENERATED.md` marker.
~~~

Remove optional folders from the list if the package does not have them.

## Step 9: Add Optional Commands

Claude Code commands live in `packages/awesome-skill/commands/` and are copied
only into the generated Claude Code plugin target.

Example `packages/awesome-skill/commands/awesome-skill.md`:

```markdown
---
description: Run awesome-skill.
argument-hint: "[args]"
allowed-tools: [Bash, Read]
---

<!-- agent-tools-managed: awesome-skill command -->

Use the `awesome-skill` skill with the user's arguments: $ARGUMENTS

Run scripts from the installed `awesome-skill` skill, or
`packages/awesome-skill/scripts/` when working from this repository.
```

Commands are optional. Do not add commands for other targets by hand.

## Step 10: Add Scripts And References

Use `scripts/` for deterministic helpers:

```text
packages/awesome-skill/scripts/example.py
packages/awesome-skill/scripts/example.sh
```

Use `references/` for detail the agent should load only when needed:

```text
packages/awesome-skill/references/backend.md
packages/awesome-skill/references/api.md
```

Rules:

- Scripts should use safe subprocess calls and clear errors.
- Scripts should avoid network or secrets in tests unless explicitly manual.
- References should be current-state docs, not history logs.
- Do not duplicate long reference content in `SKILL.md`.

## Step 11: Add Offline Tests

Create `packages/awesome-skill/tests/test_basic.py`.

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

Expected new outputs for `awesome-skill`:

```text
generated/claude/plugins/awesome-skill
generated/claude/custom-skills/awesome-skill
generated/codex/skills/awesome-skill
generated/agent-skills/awesome-skill
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
make verify-skill-metadata
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
- `make verify-skill-metadata`: `tool.json`, `SKILL.md`, `.skillignore`, and
  `skillshare-hub.json` agree on public skill metadata.
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
claude plugin validate generated/claude/plugins/awesome-skill
```

## Step 14: Add To The Release Workflow

Add the package name to the manual release workflow dropdown:

```yaml
# .github/workflows/release-skill.yml
workflow_dispatch:
  inputs:
    skill:
      options:
        - watch-video
        - codex-reset-credit
        - x-bookmarks
        - awesome-skill
```

This is the only manual release-path wiring for a new public skill. After this
step, the `Release Skill` workflow can bump `awesome-skill` to the next UTC
date version, rebuild all four generated targets, verify, commit, and push the
release.

If GitHub Actions later supports dynamic package choices for this repo, this
manual dropdown step can be removed. For now, keep the explicit list so the
release button is typo-resistant.

## Step 15: Update Docs

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
- `docs/updating-a-skill.md`: update only if the release/update process itself
  changes.

Keep docs latest-state only. Avoid origin notes, migration notes, or old
package names.

## Step 16: Commit

Before committing:

```sh
git status
git diff --cached --check
```

Confirm:

- Source files under `packages/<name>/` are staged.
- Generated outputs under `generated/`, `.claude-plugin/`, and
  `skillshare-hub.json` are staged.
- `.github/workflows/release-skill.yml` includes the new package name.
- Docs are staged.
- No `.env.local`, secrets, local auth state, generated run artifacts, media,
  caches, `node_modules/`, `dist/`, or `.venv/` files are staged.

Then commit:

```sh
git commit -m "Add awesome-skill package"
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
- `packages/<name>/SKILL.md` has `tags` matching `packages/<name>/tool.json`.
- `packages/<name>/agents/openai.yaml` has display metadata.
- `packages/<name>/README.md` explains source and generated targets.
- `packages/<name>/SOURCE.md` points future edits to source paths.
- Optional `scripts/`, `references/`, and `commands/` are useful and tested.
- Package-specific docs and security notes are updated.
- `.github/workflows/release-skill.yml` includes the package in the `Release
  Skill` dropdown.
- `make rebuild-generated` creates every target.
- `make verify-skill-metadata`, `make verify-packages`,
  `make audit-generated`, and `make verify-generated-clean` pass.
- Generated files are committed with source changes.
- The package can be released through the manual `Release Skill` workflow.
- No secrets or local artifacts are committed.
