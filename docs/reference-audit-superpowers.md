# Reference Audit: Superpowers

Reference inspected:

```text
https://github.com/obra/Superpowers
```

This repo uses Superpowers as architecture inspiration only. No substantial code
is copied.

## Useful Patterns

Superpowers keeps one source skills tree and points multiple target manifests at
that source. It avoids committing a separate generated copy for every target.

Useful ideas adopted here:

- source-first package layout
- target manifests pointing at source folders
- no committed per-target generated tree
- ignored local artifacts for target-specific packaging
- explicit target docs and runtime boundaries
- manual release workflow rather than version bumps on every push

## Current agent-tools Mapping

`agent-tools` keeps package boundaries because each tool may own more than a
skill:

```text
packages/<name>
packages/<name>/skills/<name>
packages/<name>/.claude-plugin/plugin.json
packages/<name>/commands
```

Claude Code marketplace entries point directly at `./packages/<name>`. Codex,
OpenCode, generic Agent Skills, and Skillshare use
`packages/<name>/skills/<name>`. Claude Desktop custom-skill artifacts are built
under ignored `.dist/`.

## Differences Kept Deliberately

- Superpowers is a broad methodology with bootstrap/session-start behavior.
  `agent-tools` currently contains task/domain skills and does not inject global
  bootstrap context.
- Superpowers supports many more harnesses. `agent-tools` currently documents
  Claude Code, Claude Desktop, Codex, OpenCode, and optional Skillshare.
- Superpowers has official marketplace integrations. `agent-tools` uses a
  public GitHub repo, Claude Code marketplace catalog, direct skill folders, and
  optional Skillshare hub metadata.

## Deferred Ideas

- target-specific plugin adapters beyond Claude Code
- OpenCode plugin that registers the package skill paths automatically
- official Codex plugin metadata
- richer skill behavior tests across harnesses
- bootstrap-style process skills, only if the repo later adds broad workflow
  skills that require automatic activation

## License Notes

No Superpowers code was copied into this repo. Ideas are reflected as original
repo structure, scripts, and docs.
