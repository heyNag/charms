# Generated Claude Custom Skill Package

This directory is generated from:

```text
packages/x-bookmarks
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/x-bookmarks/README.md      -> generated/claude/custom-skills/x-bookmarks/README.md
packages/x-bookmarks/SKILL.md       -> generated/claude/custom-skills/x-bookmarks/skill.md
packages/x-bookmarks/scripts/       -> generated/claude/custom-skills/x-bookmarks/scripts/
packages/x-bookmarks/references/    -> generated/claude/custom-skills/x-bookmarks/references/
packages/x-bookmarks/agents/        -> generated/claude/custom-skills/x-bookmarks/agents/

LICENSE                          -> generated/claude/custom-skills/x-bookmarks/LICENSE
~~~

This bundle is for Claude Desktop / claude.ai custom skill upload. Create the
ZIP from `generated/claude/custom-skills` so the archive contains the
`x-bookmarks/` folder at its root.

After editing source:

1. Edit `packages/x-bookmarks`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
