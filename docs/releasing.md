# Releasing

Each Charms plugin is versioned and released independently from its
`packages/<name>/plugin.json`. A release publishes one immutable GitHub release
and then points that plugin's entry in `.claude-plugin/marketplace.json` at it.

## Versions and tags

Versions are plain Semantic Versioning, `MAJOR.MINOR.PATCH`, with no
prerelease or build suffix. Every plugin starts at `1.0.0`.

- Bump `major` for incompatible changes, `minor` for compatible additions,
  and `patch` for fixes.
- A version is never reused. Each release must be greater than the plugin's
  latest release.

Release tags follow Claude Code's plugin tag convention:

```text
<name>--v<version>
```

For example, `watch-video--v1.0.0`. Each release attaches
`<name>-agent-plugin-v<version>.zip` and its `.sha256` checksum.

Only the `Release Plugin` workflow creates these tags. Do not run
`claude plugin tag` or push a `*--v*` tag by hand: a pushed tag uses up that
version, and `claude plugin tag` refuses Charms releases anyway because the
marketplace entry moves to a version only after its tag exists.

## Bump a version

A plugin's first release publishes the `1.0.0` already in its manifest. Before
each later release, change the version in a normal commit:

```sh
python3 scripts/bump-plugin-version.py watch-video patch
```

The helper takes the package name and `major`, `minor`, or `patch`, rewrites
only that `plugin.json`, and prints the new version. `--dry-run` prints the
version without changing the file.

Commit the bump, run `make check`, and push it to `main`. The marketplace does
not change until the release runs.

## Run a release

Dispatch the `Release Plugin` workflow from `main` with one input, the plugin
name. Use GitHub Actions or GitHub CLI:

```sh
gh workflow run release-plugin.yml \
  --repo heyNag/charms \
  --ref main \
  -f plugin=watch-video
```

The workflow releases the `main` commit it starts from, normally the one you
just pushed. It does not change versions or commit to `main`, except for the
marketplace update at the end.

Several plugins can be released at once. Each plugin has its own concurrency
group, and the marketplace push retries when `main` moves.

## What the workflow does

The workflow runs five jobs:

1. `ci` runs the full CI workflow on the exact commit, including macOS.
2. `validate` is read-only. When the optional `RELEASE_SETTINGS_TOKEN` secret
   is set, it first requires release immutability to be turned on; see
   [Repository settings](#repository-settings). `scripts/plan-plugin-release.py`
   refuses a tag that already exists and a version that is not greater than
   the latest release, and the job also checks that the tag is absent on
   GitHub. It then runs `make check`, requires a clean tree, builds and
   validates the ZIP, and records its digest.
3. `publish` has write access and runs after `ci` and `validate`. It requires
   the validated commit to still be on `main`, re-plans the release against
   the current tags and requires the same plan, rebuilds the ZIP from
   `git archive` of that commit, and requires the same digest. It then creates
   the tag and release with `gh release create` at that exact commit.
4. `verify` downloads the published assets and requires the tag to point at
   the release commit, the release to be immutable, the asset digests to
   match the validated ZIP, and `gh release verify` and
   `gh release verify-asset` to pass.
5. `marketplace` runs `scripts/update-marketplace.py` against the latest
   `main` and pushes one commit that changes only
   `.claude-plugin/marketplace.json`, retrying if `main` moved.

`verify` and `marketplace` are separate jobs so that **Re-run failed jobs**
can finish an interrupted release without publishing it again.

The marketplace entry takes its version and description from `plugin.json` at
the release commit and pins the release tag and full commit SHA. It only moves
to a newer version.

The archive contains one top-level plugin directory with `plugin.json`,
`LICENSE`, `README.md`, and the complete `skills/` tree. It excludes tests and
repository tooling, rejects symlinks and special files, and uses stable
timestamps and modes.

## Verify a release

After the run succeeds, confirm:

- all five jobs passed;
- `gh release verify <tag> --repo heyNag/charms` passes;
- `gh release verify-asset <tag> <zip> --repo heyNag/charms` passes for the
  downloaded ZIP;
- the marketplace entry on `main` names the new version, tag, and release
  commit;
- after `git pull` and `git fetch --tags`, `make check` passes locally.

## Repair a release

- `validate` failed because release immutability is off, or because GitHub
  refused the token in `RELEASE_SETTINGS_TOKEN`: nothing was published. Follow
  the `fix:` line in the job log and dispatch again.
- `publish` failed before the release existed: fix the cause, push, and
  dispatch again.
- `verify` or `marketplace` failed: use **Re-run failed jobs** on the
  workflow run. It does not republish the release. To finish only the
  marketplace step, you can also update the entry from an up-to-date `main`
  checkout and push it. The release commit is the one the release tag points
  at:

  ```sh
  git pull
  git fetch --tags
  python3 scripts/update-marketplace.py watch-video --sha <release-commit-sha>
  git commit -m "Point marketplace at watch-video <version>" \
    .claude-plugin/marketplace.json
  git push
  ```

- `verify` failed because the release is not immutable: the setting was off
  when the release was published, and turning it on does not change a release
  that already exists. Turn it on first. GitHub's changelog for immutable
  releases says an existing release stays mutable "unless you republish" it,
  so publish the same release again and then use **Re-run failed jobs**:

  ```sh
  gh release edit <tag> --repo heyNag/charms --draft
  gh release edit <tag> --repo heyNag/charms --draft=false --latest=false
  ```

  This route has not been tried in this repository. If `verify` still finds
  the release not immutable, bump to a new version and release that. The old
  tag stays, because the tag ruleset blocks its deletion.

- The release itself is bad: a published release is immutable, and its tag
  name can never be reused, even after the release is deleted. Fix the
  problem, bump to a new version, and release that.

## Repository settings

The repository owner configures these once, before the first release.
Immutability applies only to releases published after it is turned on.

1. **Release immutability.** Enable it in Settings > Releases, or run:

   ```sh
   gh api -X PUT repos/heyNag/charms/immutable-releases
   ```

   The workflow cannot turn the setting on. `verify` fails if the release
   is not immutable, but by then the release is published and its tag
   exists. The optional token in item 4 moves that check in front of
   publishing.

2. **Tag ruleset.** Target `refs/tags/*--v*` with only the **Restrict
   updates** and **Restrict deletions** rules and no bypass actors. Leave out
   a creation rule so the workflow can still create tags.

3. **Branch ruleset on `main`.** Use only **Restrict deletions** and **Block
   force pushes**. Do not require pull requests or status checks: the release
   workflow pushes the marketplace commit with `GITHUB_TOKEN`, which can
   neither satisfy nor bypass those rules. CI is enforced inside the release
   workflow instead.

4. **Optional: a token that can read the immutability setting.** GitHub
   shows the setting only to a token with the repository's Administration
   permission, and the `GITHUB_TOKEN` of a workflow run cannot hold that
   permission. To have `validate` check the setting before anything is
   published, create a fine-grained personal access token for this repository
   only, with the Administration permission set to read-only and no other
   permission, and save it as an Actions secret:

   ```sh
   gh secret set RELEASE_SETTINGS_TOKEN --repo heyNag/charms
   ```

   With the secret set, `validate` stops the release when the setting is off,
   and also when GitHub refuses the token, for example once it has expired.
   Without the secret, the run notes that the setting was not checked and
   continues as before. The token is used in one step of the read-only
   `validate` job, before any dependency is installed.
