# Generated Agent-Agnostic Skill Package

This directory is generated from:

```text
packages/codex-reset-credit
```

Do not edit this directory directly during normal development.

Edit the source paths on the left; the generated outputs on the right are
rewritten by `make rebuild-generated`.

~~~text
packages/codex-reset-credit/README.md      -> generated/agent-skills/codex-reset-credit/README.md
packages/codex-reset-credit/SKILL.md       -> generated/agent-skills/codex-reset-credit/SKILL.md
packages/codex-reset-credit/scripts/       -> generated/agent-skills/codex-reset-credit/scripts/
LICENSE                          -> generated/agent-skills/codex-reset-credit/LICENSE
~~~

This bundle is the portable skill-folder shape for agents that consume the
Agent Skills convention directly, including Codex, OpenCode, and other
`SKILL.md` consumers. Claude custom-skill ZIPs use
`generated/claude/custom-skills/codex-reset-credit` because that surface documents a
lowercase `skill.md` file.

After editing source:

1. Edit `packages/codex-reset-credit`.
2. Run `make rebuild-generated`.
3. Run `make verify-generated-clean`.
4. Commit both source and regenerated output changes.
