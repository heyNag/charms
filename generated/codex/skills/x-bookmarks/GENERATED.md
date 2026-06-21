# Generated Codex Skill Package

This directory is generated from:

```text
packages/x-bookmarks
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/x-bookmarks/README.md      -> generated/codex/skills/x-bookmarks/README.md
packages/x-bookmarks/SKILL.md       -> generated/codex/skills/x-bookmarks/SKILL.md
packages/x-bookmarks/scripts/       -> generated/codex/skills/x-bookmarks/scripts/
packages/x-bookmarks/references/    -> generated/codex/skills/x-bookmarks/references/
packages/x-bookmarks/agents/        -> generated/codex/skills/x-bookmarks/agents/

LICENSE                          -> generated/codex/skills/x-bookmarks/LICENSE
~~~

After editing source:

1. Edit `packages/x-bookmarks`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
