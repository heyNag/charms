# Releasing A Skill

Use this guide when publishing a public version of an existing skill.

## Release Model

Releases are per skill. A release updates only:

```text
packages/<name>/.claude-plugin/plugin.json
.claude-plugin/marketplace.json
skillshare-hub.json
```

Root `skills/` and `commands/` indexes are refreshed from package source during
the workflow. Claude Desktop custom-skill folders are local `.dist/` artifacts
and are not committed.

## Versioning

Versions are UTC date versions:

```text
YYYY.M.D
YYYY.M.D.1
YYYY.M.D.2
```

If you trigger multiple releases for the same skill on the same UTC day, the
workflow increments the suffix.

Do not edit versions manually. CI rejects package plugin version changes unless
they are made by the GitHub Actions release bot.

## Before Release

From a clean local checkout:

```sh
make build-packages
make public-check
make release-dry-run SKILL=watch-video
git status
```

Change `SKILL` to the package you are releasing.

## Trigger Release

1. Open GitHub Actions.
2. Choose `Release Skill`.
3. Run workflow.
4. Enter the package name, for example:

```text
watch-video
codex-reset-credit
x-bookmarks
```

The workflow validates the package name by loading
`packages/<name>/.claude-plugin/plugin.json`. New public skills do not need to
be manually registered in the workflow; if the package exists and follows the
repo shape, the workflow can release it.

## What The Workflow Does

1. Computes the next UTC date version.
2. Updates `packages/<name>/.claude-plugin/plugin.json`.
3. Runs `make build-packages`.
4. Runs tests, syntax checks, package verification, and skill metadata
   verification.
5. Verifies source indexes are current.
6. Commits the release metadata.
7. Pushes to `main`.
8. Creates a GitHub Release tagged `<skill>@<version>`.

## New Skill Release Readiness

A new skill is release-ready when:

- `packages/<name>/tool.json` exists with `"public": true`.
- `targets` includes the intended target set.
- `packages/<name>/.claude-plugin/plugin.json` exists.
- `packages/<name>/skills/<name>/SKILL.md` exists.
- `make build-packages` creates or refreshes the root symlinks and indexes.
- `make public-check` passes.

The package manifest and build scripts apply the skill to all declared targets.
Do not hand-edit root indexes, marketplace entries, hub entries, or `.dist/`
artifacts.
