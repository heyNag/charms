# Distribution Targets

This repo keeps package source in one place and lets each target consume that
source directly whenever possible.

## Source To Targets

```mermaid
flowchart TD
  P["packages/<name><br/>package source + Claude plugin root"] --> T["tool.json<br/>targets + metadata"]
  P --> C[".claude-plugin/plugin.json"]
  P --> S["skills/<name>/SKILL.md"]
  S --> H["skills/<name>/scripts<br/>optional"]
  S --> R["skills/<name>/references<br/>optional"]
  S --> A["skills/<name>/agents<br/>optional"]
  P --> CMD["commands<br/>optional Claude commands"]
  S --> RSI["root skills/ symlink index"]
  CMD --> RCI["root commands/ symlink index"]

  P --> CC["Claude Code<br/>/plugin install <name>@charms"]
  RSI --> CUR["Cursor<br/>.cursor-plugin/plugin.json"]
  RSI --> CXPLUG["Codex plugin<br/>.codex-plugin/plugin.json"]
  RSI --> OCPLUG["OpenCode plugin<br/>.opencode/plugins/charms.js"]
  S --> CX["Codex<br/>copy skills/<name>"]
  S --> OC["OpenCode / generic<br/>copy skills/<name>"]
  S --> SH["Skillshare Hub<br/>source packages/<name>/skills/<name>"]
  S --> DIST["Claude Desktop<br/>make build-packages -> .dist/"]
  T --> IDX[".claude-plugin/marketplace.json<br/>skillshare-hub.json"]
  C --> IDX
```

## Target Shapes

Claude Code consumes the package root:

```text
packages/<name>/
  .claude-plugin/plugin.json
  skills/<name>/SKILL.md
  skills/<name>/scripts/
  skills/<name>/references/
  skills/<name>/agents/
  commands/
  README.md
```

Codex consumes the skill folder:

```text
packages/<name>/skills/<name>/
  SKILL.md
  scripts/
  references/
  agents/
```

OpenCode and generic Agent Skills consume the same skill folder:

```text
packages/<name>/skills/<name>/
```

Cursor and root Codex/OpenCode plugin wrappers consume the root symlink index:

```text
skills/<name> -> ../packages/<name>/skills/<name>
```

Claude Desktop / claude.ai custom skills need lowercase `skill.md`, so the
local artifact builder creates:

```text
.dist/claude/custom-skills/<name>/
  skill.md
  scripts/
  references/
  agents/
  README.md
  LICENSE
```

`.dist/` is ignored and not committed.

## What Is Shared

Codex, Cursor, OpenCode, generic Agent Skills, and Skillshare use the same
source skill folder. The Agent Skills CLI (`npx skills add heyNag/charms`,
listed via `.agents/plugins/marketplace.json`) copies that folder into
whatever hosts it detects. Some root plugin wrappers reach it through the `skills/`
symlink index. Claude Code uses the package root for per-skill marketplace
plugins because it also needs plugin metadata and commands. Claude Desktop uses
a local artifact because its filename expectation differs.

## Update Rule

Edit only source paths during normal development:

```text
packages/<name>/
```

Then run:

```sh
make build-packages
make public-check
```
