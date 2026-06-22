# Packages

`packages/` contains the canonical source packages for this repo.

Each package is directly consumable:

- Claude Code installs the package directory as a plugin source.
- Codex copies the package's `skills/<name>` folder.
- OpenCode/generic Agent Skills copy the same `skills/<name>` folder.
- Claude Desktop custom-skill ZIP folders are built locally under `.dist/`.

Current packages:

- `watch-video`
- `codex-reset-credit`
- `x-bookmarks`

## Package Shape

```text
packages/<name>/
  README.md
  SOURCE.md
  tool.json
  .claude-plugin/
    plugin.json
  skills/
    <name>/
      SKILL.md
      scripts/       optional
      references/    optional
      agents/        optional
  commands/          optional Claude Code slash commands
  tests/             optional offline tests
```

The source skill is:

```text
packages/<name>/skills/<name>/SKILL.md
```

Do not create a second root-level `packages/<name>/SKILL.md`. If a package
grows to multiple skills, add another `skills/<other-skill>/SKILL.md` and update
the package manifest/build checks in the same change.

## Normal Edit Flow

Edit source under `packages/<name>/`, then refresh indexes and local artifacts:

```sh
make build-packages
make public-check
```

Do not commit `.dist/` artifacts.
