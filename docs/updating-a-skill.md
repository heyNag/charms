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
skills/<name>                    symlink index
commands/*.md                    symlink index when package commands exist
.dist/claude/custom-skills/<name>  ignored local artifact
```

These outputs are driven by `packages/<name>/tool.json`,
`packages/<name>/.claude-plugin/plugin.json`, and
`packages/<name>/skills/<name>/SKILL.md`. Do not update target indexes by hand.

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

Use the manual GitHub Actions `Release Skill` workflow. Enter the package name
as the `skill` input. The workflow bumps the selected skill version, refreshes
indexes/artifacts, verifies, commits, pushes, and creates a GitHub Release
tagged:

```text
<skill>@<version>
```

## User Update Paths

| Target | User update process |
|---|---|
| Claude Code | Reinstall/update the plugin from the marketplace if Claude Code offers an update flow. If unsure, run `/plugin list`, `/plugin details <name>@charms`, then reinstall with `/plugin install <name>@charms`. |
| Codex | Pull the repo and copy `packages/<name>/skills/<name>` into `~/.codex/skills/<name>`. |
| Cursor | Update the repo/plugin checkout. The Cursor manifest points at the root `skills/` symlink index. |
| OpenCode | Pull the repo and copy `packages/<name>/skills/<name>` into `~/.config/opencode/skills/<name>` or the configured skill path. |
| Claude Desktop / claude.ai | Download the new release's attached ZIP and import/replace the skill, or pull the repo, run `make build-packages`, and zip `.dist/claude/custom-skills/<name>`. |
| Agent Skills CLI installs | `npx skills update <name>` (or re-run `npx skills add heyNag/charms`). |
| Skillshare | For a normal hub or direct GitHub-subdirectory install, run `skillshare check <name>`, `skillshare update <name>`, then `skillshare sync`. Reserve `--track` for intentionally preserving and updating a broader Git repository checkout. |

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
- `make release-dry-run SKILL=<name>` prints the expected next version.
- `make public-check` passes.
- The manual `Release Skill` workflow is used for public version bumps.
- No `.dist/`, ZIPs, credentials, local state, media, transcripts, frames, or
  caches are committed.
