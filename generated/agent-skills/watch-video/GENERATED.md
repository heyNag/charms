# Generated Agent-Agnostic Skill Package

This directory is generated from:

```text
packages/watch-video
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/watch-video/README.md      -> generated/agent-skills/watch-video/README.md
packages/watch-video/SKILL.md       -> generated/agent-skills/watch-video/SKILL.md
packages/watch-video/scripts/       -> generated/agent-skills/watch-video/scripts/

LICENSE                          -> generated/agent-skills/watch-video/LICENSE
~~~

This bundle is the portable skill-folder shape for agents that consume the
Agent Skills convention directly, including Codex, OpenCode, and other
`SKILL.md` consumers. Claude custom-skill ZIPs use
`generated/claude/custom-skills/watch-video` because that surface documents a
lowercase `skill.md` file.

After editing source:

1. Edit `packages/watch-video`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
