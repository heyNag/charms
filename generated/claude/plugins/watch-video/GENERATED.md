# Generated Claude Code Package

This directory is generated from:

```text
packages/watch-video
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/watch-video/README.md              -> generated/claude/plugins/watch-video/README.md
packages/watch-video/plugin/plugin.json     -> generated/claude/plugins/watch-video/.claude-plugin/plugin.json
packages/watch-video/SKILL.md               -> generated/claude/plugins/watch-video/skills/watch-video/SKILL.md
packages/watch-video/scripts/               -> generated/claude/plugins/watch-video/skills/watch-video/scripts/
packages/watch-video/commands/              -> generated/claude/plugins/watch-video/commands/

LICENSE                                  -> generated/claude/plugins/watch-video/LICENSE
~~~

After editing source:

1. Edit `packages/watch-video`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
