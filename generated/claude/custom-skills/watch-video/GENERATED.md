# Generated Claude Custom Skill Package

This directory is generated from:

```text
packages/watch-video
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/watch-video/README.md      -> generated/claude/custom-skills/watch-video/README.md
packages/watch-video/SKILL.md       -> generated/claude/custom-skills/watch-video/skill.md
packages/watch-video/scripts/       -> generated/claude/custom-skills/watch-video/scripts/

LICENSE                          -> generated/claude/custom-skills/watch-video/LICENSE
~~~

This bundle is for Claude Desktop / claude.ai custom skill upload. Create the
ZIP from `generated/claude/custom-skills` so the archive contains the
`watch-video/` folder at its root.

After editing source:

1. Edit `packages/watch-video`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
