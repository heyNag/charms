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
2. `validate` is read-only. `scripts/plan-plugin-release.py` refuses a tag
   that already exists and a version that is not greater than the latest
   release, and the job also checks that the tag is absent on GitHub. It then
   runs `make check`, requires a clean tree, builds and validates the ZIP, and
   records its digest.
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

- `publish` failed before the release existed: fix the cause, push, and
  dispatch again.
- `verify` or `marketplace` failed: use **Re-run failed jobs** on the
  workflow run. It does not republish the release. If `verify` fails because
  the release is not immutable, the immutability setting was off when it was
  published; the setting is not retroactive, so turn it on and release a new
  version. To finish only the marketplace step, you can also update the entry
  from an up-to-date `main` checkout and push it. The release commit is the
  one the release tag points at:

  ```sh
  git pull
  git fetch --tags
  python3 scripts/update-marketplace.py watch-video --sha <release-commit-sha>
  git commit -m "Point marketplace at watch-video <version>" \
    .claude-plugin/marketplace.json
  git push
  ```

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

   The `publish` job fails if a release is not immutable.

2. **Tag ruleset.** Target `refs/tags/*--v*` with only the **Restrict
   updates** and **Restrict deletions** rules and no bypass actors. Leave out
   a creation rule so the workflow can still create tags.

3. **Branch ruleset on `main`.** Use only **Restrict deletions** and **Block
   force pushes**. Do not require pull requests or status checks: the release
   workflow pushes the marketplace commit with `GITHUB_TOKEN`, which can
   neither satisfy nor bypass those rules. CI is enforced inside the release
   workflow instead.
