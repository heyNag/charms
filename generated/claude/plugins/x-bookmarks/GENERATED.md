# Generated Claude Code Package

This directory is generated from:

```text
packages/x-bookmarks
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/x-bookmarks/README.md              -> generated/claude/plugins/x-bookmarks/README.md
packages/x-bookmarks/plugin/plugin.json     -> generated/claude/plugins/x-bookmarks/.claude-plugin/plugin.json
packages/x-bookmarks/SKILL.md               -> generated/claude/plugins/x-bookmarks/skills/x-bookmarks/SKILL.md
packages/x-bookmarks/scripts/               -> generated/claude/plugins/x-bookmarks/skills/x-bookmarks/scripts/
packages/x-bookmarks/references/            -> generated/claude/plugins/x-bookmarks/skills/x-bookmarks/references/
packages/x-bookmarks/agents/                -> generated/claude/plugins/x-bookmarks/skills/x-bookmarks/agents/
packages/x-bookmarks/commands/              -> generated/claude/plugins/x-bookmarks/commands/

LICENSE                                  -> generated/claude/plugins/x-bookmarks/LICENSE
~~~

After editing source:

1. Edit `packages/x-bookmarks`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
