# Updating A Skill

Use this guide when publishing an update to an existing public skill package or
when helping a user refresh an installed skill.

The short version:

```text
Edit packages/<name>/ only.
For normal development, run make rebuild-generated and commit source plus generated output together.
For a public release, run the manual Release Skill GitHub Action.
The workflow creates a skill-scoped GitHub Release and tag.
Tell users how to update for their target.
```

Do not manually edit files under `generated/` or `.claude-plugin/`. Those paths
are rebuilt from package source.
Do not manually edit `skillshare-hub.json`; it is rebuilt from package
`SKILL.md` frontmatter, package manifests, and plugin versions.

## Target Map

The skill targets in this repo are:

```text
Claude Code       -> generated/claude/plugins/<name>
Claude Desktop    -> generated/claude/custom-skills/<name>
Codex             -> generated/codex/skills/<name>
OpenCode          -> generated/agent-skills/<name>
Skillshare        -> skillshare-hub.json entry resolving to packages/<name>
```

The source package is always:

```text
packages/<name>
```

## Versioning

Use package-level versions. Each skill can release independently.

For skill packages, use UTC date-based CalVer:

```text
YYYY.M.D
```

Examples:

```text
2026.6.21
2026.12.5
2027.1.14
```

Do not zero-pad version parts. If a fixed-width date is useful in prose, write
it as a release date:

```text
Release date: 2026-06-21
Plugin version: 2026.6.21
```

If the same skill is released more than once on the same UTC day, append a
numeric same-day sequence:

```text
2026.6.21
2026.6.21.1
2026.6.21.2
```

The version source is:

```text
packages/<name>/plugin/plugin.json
```

Do not edit this version by hand. The only supported write path is the manual
GitHub Actions `Release Skill` workflow. Local use of
`scripts/bump-skill-version.py` is for `--dry-run` checks only.

The generated Claude Code plugin manifest and marketplace catalog inherit the
version from the source plugin metadata. The Skillshare hub `generatedAt` value
is derived deterministically from package date versions, so rebuilding does not
create timestamp-only diffs.

## Manual Release Workflow

Public releases are intentionally manual. Ordinary pushes and pull requests run
verification only; they do not publish a new skill version.

To release a skill in GitHub's web UI:

1. Open `https://github.com/heyNag/agent-tools`.
2. Open the `Actions` tab.
3. Choose the `Release Skill` workflow.
4. Click `Run workflow`.
5. Select the skill/package name:

```text
watch-video
codex-reset-credit
x-bookmarks
```

6. Confirm the run.

To release from a local checkout with the GitHub CLI:

```sh
gh workflow run release-skill.yml -f skill=x-bookmarks
gh run list --workflow release-skill.yml --limit 5
```

Replace `x-bookmarks` with the package being released:

```text
watch-video
codex-reset-credit
x-bookmarks
```

For a newly added package such as `awesome-skill`, first add the package name
to `.github/workflows/release-skill.yml` as described in
`docs/adding-a-skill.md`. The first release workflow run moves the package from
the bootstrap `0.1.0` version to the UTC date-based version.

The workflow:

1. Computes the next UTC date version.
2. Updates `packages/<name>/plugin/plugin.json`.
3. Runs `make rebuild-generated`.
4. Rebuilds all four skill targets:

```text
generated/claude/plugins/<name>
generated/claude/custom-skills/<name>
generated/codex/skills/<name>
generated/agent-skills/<name>
```

5. Regenerates the Claude marketplace and Skillshare hub index.
6. Runs tests, syntax checks, package verification, generated-output audit, and
   generated-clean verification.
7. Commits and pushes:

```text
Release <name> <version>
```

8. Creates a skill-scoped git tag and GitHub Release:

```text
<name>@<version>
```

Examples:

```text
watch-video@YYYY.M.D
codex-reset-credit@YYYY.M.D.N
x-bookmarks@YYYY.M.D
```

GitHub Releases are package-level because each skill can release
independently. The repo does not publish GitHub Packages yet; there is no npm,
container, or binary package artifact to publish today. GitHub may still show
the newest skill release as the repo's `Latest` release; that label is a GitHub
UI artifact, not a repo-wide version.

Release workflows are serialized so two release button presses cannot update
the shared marketplace catalog at the same time.

## Supported Release Choices

The current release workflow dropdown includes:

```text
watch-video
codex-reset-credit
x-bookmarks
```

When adding `awesome-skill`, the only manual release-path wiring is adding
`awesome-skill` to that dropdown. The builders already discover package targets
from `packages/awesome-skill/tool.json`.

## Local Version Bump Helper

Use the same helper locally when testing release behavior:

```sh
python3 scripts/bump-skill-version.py x-bookmarks --dry-run
python3 scripts/bump-skill-version.py x-bookmarks --date 2026-06-21 --dry-run
```

Without `--dry-run`, the helper refuses to run outside the GitHub Actions
`Release Skill` workflow. The workflow is the only supported command that
updates:

```text
packages/<name>/plugin/plugin.json
```

Version bump guidance:

- User-visible behavior or docs update: run the manual release workflow.
- Internal source-only cleanup that does not affect generated outputs or public
  behavior: a public release is optional.
- Claude Code marketplace updates need a changed plugin version to reliably
  appear as an update, so use the release workflow when a public update should
  be visible.

## Maintainer Update Flow

1. Edit source files under `packages/<name>/`.
2. Update tests for behavior changes.
3. Run the clean generation flow:

```sh
make rebuild-generated
```

4. Verify:

```sh
make test
make syntax
make mcp-build
make verify-skill-metadata
make verify-packages
make audit-generated
make verify-generated-clean
git diff --check
git status
```

5. Commit source and generated output changes together.
6. Push to GitHub.
7. When the change should become a public update, run the manual `Release Skill`
   workflow for that package.

## User Update Flow: Claude Code

Claude Code users install from the marketplace:

```text
/plugin marketplace add heyNag/agent-tools
/plugin install x-bookmarks@agent-tools
```

To update an installed skill:

```text
/plugin marketplace update agent-tools
/plugin update x-bookmarks@agent-tools
/reload-plugins
```

Replace `x-bookmarks` with the package name being updated.

Terminal equivalent:

```sh
claude plugin marketplace update agent-tools
claude plugin update x-bookmarks@agent-tools
```

Claude Code can also auto-update marketplace plugins at startup when the user
enables auto-update for the marketplace. Third-party marketplaces may not have
auto-update enabled by default, so the manual commands above remain the
portable update path.

If Claude Code says the plugin is already latest after a release, check that
`packages/<name>/plugin/plugin.json` had a version bump before the generated
outputs were committed.

## User Update Flow: Claude Desktop Or Claude.ai

Claude Desktop and claude.ai custom skills use uploaded ZIP files. They do not
pull from the marketplace automatically.

To update:

```sh
cd agent-tools
git pull
make rebuild-generated
cd generated/claude/custom-skills
zip -r x-bookmarks.zip x-bookmarks
```

Then upload or replace the ZIP in Claude's `Customize > Skills` flow.

Replace `x-bookmarks` with the package name being updated.

Optional no-terminal update path: after the release is pushed, paste the
public generated folder URL into the third-party
[Skills Compiler](https://skill-compiler.statechange.ai/), download the new
`.skill`, and replace the existing Claude Desktop skill:

```text
https://github.com/heyNag/agent-tools/tree/main/generated/claude/custom-skills/x-bookmarks
```

Replace `x-bookmarks` with the package name being updated. Preview the files
before importing. This path still uses the generated folder built from
`packages/<name>/`.

The generated custom-skill folder uses lowercase `skill.md`, generated from:

```text
packages/<name>/SKILL.md
```

## User Update Flow: Codex

Codex users copy generated skill folders into `~/.codex/skills`.

To update all Codex-targeted public skills from a cloned repo:

```sh
cd agent-tools
git pull
./scripts/install-codex.sh
```

To update one skill manually:

```sh
cd agent-tools
git pull
rm -rf ~/.codex/skills/x-bookmarks
cp -R generated/codex/skills/x-bookmarks ~/.codex/skills/x-bookmarks
```

Replace `x-bookmarks` with the package name being updated.

## User Update Flow: OpenCode

OpenCode uses the generated Agent Skills folder shape:

```text
generated/agent-skills/<name>
```

To update one skill manually:

```sh
cd agent-tools
git pull
rm -rf ~/.config/opencode/skills/x-bookmarks
cp -R generated/agent-skills/x-bookmarks ~/.config/opencode/skills/x-bookmarks
```

Replace `x-bookmarks` with the package name being updated.

If the user stores OpenCode skills somewhere else, copy
`generated/agent-skills/<name>` into that configured skill directory.

## Local Development Update Flow

For local development on this repo, rerun the install scripts after pulling:

```sh
cd agent-tools
git pull
./scripts/install-all.sh
```

`install-all.sh` installs the public packages that target Claude local skills
and Codex local skills. OpenCode uses the manual copy flow above until an
OpenCode install script exists.

## Troubleshooting

Claude Code still shows the old skill:

```text
Run /plugin marketplace update agent-tools, /plugin update <name>@agent-tools,
then /reload-plugins. Confirm the package version changed in plugin.json.
```

Codex still shows the old skill:

```text
Re-run ./scripts/install-codex.sh from a freshly pulled repo. Confirm the copied
folder under ~/.codex/skills/<name> has the updated SKILL.md or scripts.
```

Claude Desktop still shows the old skill:

```text
Create a fresh ZIP from generated/claude/custom-skills/<name> and replace the
uploaded skill in Claude's Skills UI.
```

OpenCode still shows the old skill:

```text
Replace the folder under ~/.config/opencode/skills/<name> with
generated/agent-skills/<name> from a freshly pulled repo.
```

Generated outputs are stale:

```sh
make rebuild-generated
make verify-skill-metadata
make audit-generated
make verify-generated-clean
```

## Final Checklist

- Source changes are under `packages/<name>`.
- Public release version is bumped by the manual `Release Skill` workflow.
- `packages/<name>/plugin/plugin.json` version was not edited by hand.
- Generated outputs are rebuilt with `make rebuild-generated`.
- Skill metadata is checked with `make verify-skill-metadata`.
- All verification commands pass.
- Docs mention any changed setup, update, or runtime behavior.
- No secrets, local auth state, media, transcripts, caches, or runtime
  artifacts are staged.
- The final user-facing update instructions name the correct target: Claude
  Code, Claude Desktop, Codex, or OpenCode.
