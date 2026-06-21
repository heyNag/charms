# Generated Agent-Agnostic Skill Package

This directory is generated from:

```text
packages/x-bookmarks
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/x-bookmarks/README.md      -> generated/agent-skills/x-bookmarks/README.md
packages/x-bookmarks/SKILL.md       -> generated/agent-skills/x-bookmarks/SKILL.md
packages/x-bookmarks/scripts/       -> generated/agent-skills/x-bookmarks/scripts/
packages/x-bookmarks/references/    -> generated/agent-skills/x-bookmarks/references/
packages/x-bookmarks/agents/        -> generated/agent-skills/x-bookmarks/agents/

LICENSE                          -> generated/agent-skills/x-bookmarks/LICENSE
~~~

This bundle is the portable skill-folder shape for agents that consume the
Agent Skills convention directly, including Codex, OpenCode, and other
`SKILL.md` consumers. Claude custom-skill ZIPs use
`generated/claude/custom-skills/x-bookmarks` because that surface documents a
lowercase `skill.md` file.

After editing source:

1. Edit `packages/x-bookmarks`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
