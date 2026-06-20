# Generated Codex Skill Package

This directory is generated from:

```text
packages/watch-video
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/watch-video/README.md      -> generated/codex/skills/watch-video/README.md
packages/watch-video/SKILL.md       -> generated/codex/skills/watch-video/SKILL.md
packages/watch-video/scripts/       -> generated/codex/skills/watch-video/scripts/
LICENSE                          -> generated/codex/skills/watch-video/LICENSE
~~~

After editing source:

1. Edit `packages/watch-video`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
