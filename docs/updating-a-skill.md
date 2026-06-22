# Updating A Skill

Use this guide when changing an existing public skill package or explaining how
users get updates.

## Source Paths

Edit source under:

```text
packages/<name>/
packages/<name>/skills/<name>/
```

Do not edit installed copies. Do not commit `.dist/` artifacts.

## Maintainer Update Flow

For normal source changes:

```sh
make build-packages
make public-check
git status
git add ...
git commit -m "..."
git push
```

`make build-packages` refreshes:

```text
.claude-plugin/marketplace.json
skillshare-hub.json
.dist/claude/custom-skills/<name>  ignored local artifact
```

## Versioning And Releases

Versions are per skill. Public releases use UTC date versions:

```text
YYYY.M.D
YYYY.M.D.1
YYYY.M.D.2
```

If multiple releases happen on the same UTC day, the workflow increments the
same-day suffix.

Do not manually edit:

```text
packages/<name>/.claude-plugin/plugin.json
```

Use the manual GitHub Actions `Release Skill` workflow. It bumps the selected
skill version, refreshes indexes/artifacts, verifies, commits, pushes, and
creates a GitHub Release tagged:

```text
<skill>@<version>
```

## User Update Paths

| Target | User update process |
|---|---|
| Claude Code | Reinstall/update the plugin from the marketplace if Claude Code offers an update flow. If unsure, run `/plugin list`, `/plugin details <name>@agent-tools`, then reinstall with `/plugin install <name>@agent-tools`. |
| Codex | Pull the repo and copy `packages/<name>/skills/<name>` into `~/.codex/skills/<name>`. |
| OpenCode | Pull the repo and copy `packages/<name>/skills/<name>` into `~/.config/opencode/skills/<name>` or the configured skill path. |
| Claude Desktop / claude.ai | Pull the repo, run `make build-packages`, zip `.dist/claude/custom-skills/<name>`, and import/replace the skill. |
| Skillshare | If installed with `--track`, run `skillshare check`, `skillshare update <name>`, then `skillshare sync`. Otherwise reinstall from the hub or direct skill path. |

## Codex Copy Example

```sh
git pull
rm -rf ~/.codex/skills/x-bookmarks
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

## OpenCode Copy Example

```sh
git pull
rm -rf ~/.config/opencode/skills/x-bookmarks
cp -R packages/x-bookmarks/skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

## Claude Desktop ZIP Example

```sh
git pull
make build-packages
cd .dist/claude/custom-skills
zip -r x-bookmarks.zip x-bookmarks
```

## Release Checklist

- Source changes are under `packages/<name>`.
- Version bump is not manual.
- `make public-check` passes.
- The manual `Release Skill` workflow is used for public version bumps.
- No `.dist/`, ZIPs, credentials, local state, media, transcripts, frames, or
  caches are committed.
