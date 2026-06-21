# Generated Claude Custom Skill Package

This directory is generated from:

```text
packages/codex-reset-credit
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/codex-reset-credit/README.md      -> generated/claude/custom-skills/codex-reset-credit/README.md
packages/codex-reset-credit/SKILL.md       -> generated/claude/custom-skills/codex-reset-credit/skill.md
packages/codex-reset-credit/scripts/       -> generated/claude/custom-skills/codex-reset-credit/scripts/
LICENSE                          -> generated/claude/custom-skills/codex-reset-credit/LICENSE
~~~

This bundle is for Claude Desktop / claude.ai custom skill upload. Create the
ZIP from `generated/claude/custom-skills` so the archive contains the
`codex-reset-credit/` folder at its root.

After editing source:

1. Edit `packages/codex-reset-credit`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
