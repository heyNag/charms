# Releasing

Each native Charms plugin is versioned and released independently from its
`packages/<name>/plugin.json`. A release publishes one immutable GitHub release
and then points that plugin's entries in `.claude-plugin/marketplace.json` and
`.agents/plugins/marketplace.json` at it in one commit. The two complete
catalogs preserve the same native plugin entries.
The [pstack bundle](#pstack-bundle-releases) has two host roots
and separate upstream/native and downstream release versions.

## Versions and tags

Versions are calendar versions, `YEAR.MONTH.RELEASE`:

- `YEAR` and `MONTH` are the year and the month in UTC. The month has no
  leading zero.
- `RELEASE` is the number of releases the plugin has already made in that
  month, so the first one is 0.

`2026.11.0` is a plugin's first release of November 2026, `2026.11.1` is its
second, and `2026.12.0` is its first of December. Each plugin counts its own
releases.

- A version is never reused. Each release must be greater than the plugin's
  latest release, and its third number must be the next one of its month.
- A version says when a release was prepared, not what it changes. The
  release notes list the subjects of the commits made to the plugin since
  its previous release, the newest 30 at most, so a change that an existing
  setup will notice belongs in the subject of its commit.
- A version is three plain numbers, which makes it a valid semantic version
  as well. Claude Code resolves version ranges against the release tags and
  ignores a tag whose version it cannot read as a semantic version, so
  there is no fourth number and no suffix.
- The releases made before the move to calendar versions are numbered
  `1.x`. Their tags and marketplace entries stay as they are, and every
  calendar version is greater than any of them.

Release tags follow Claude Code's plugin tag convention:

```text
<name>--v<version>
```

For example, `watch-video--v2026.11.0`. Each native release attaches
`<name>-agent-plugin-v<version>.zip` and its `.sha256` checksum.
Pstack instead attaches `pstack-bundle-v<version>.zip` and its checksum.

Only the `Release Plugin` workflow creates these tags. Do not run
`claude plugin tag` or push a `*--v*` tag by hand: a pushed tag uses up that
version, and `claude plugin tag` refuses Charms releases anyway because the
marketplace entry moves to a version only after its tag exists.

## Bump a version

Between releases a manifest holds the version of the plugin's latest release.
Before the next release, set the next version in a normal commit:

```sh
git fetch --tags
python3 scripts/bump-plugin-version.py watch-video
```

For native plugins, the helper takes the package name. It reads releases from
the release tags and marketplace, works out the version for today's date
in UTC, rewrites only that `plugin.json`, and prints the version. `--dry-run`
prints the version without changing the file. A new plugin gets its first
version the same way.

Running the helper again before the release prints the same version and
changes nothing. Once a new month has begun, it moves the version to that
month instead. That second run is optional, because a version set in one
month can still be released in a later one.

Commit the bump on a branch, run `make check`, and merge its pull request once
CI is green, as for any other change. `make check` and the release workflow
both refuse a version that breaks the rules above, with a message that names
the helper, so do not type a version by hand. The marketplace does not change
until the release runs.

## Pstack bundle releases

`pstack` is currently **unreleased**. Its release will contain two complete
host roots. Its downstream version is owned by
`integrations/pstack/projection.json` and generated into
`packages/pstack/bundle.json`. Codex uses that downstream version. Claude keeps
its exact upstream native version, currently `0.15.43`; it must never be
rewritten to match the bundle's calendar version.

After preparing the pinned upstream source in the sync cache, use the same
bump command and verify the generated output:

```sh
python3 scripts/bump-plugin-version.py pstack
python3 scripts/sync-pstack.py --check
python3 scripts/build-plugin-archive.py pstack
```

The bump sends the new projection to the sync generator, which replaces the
projection and generated bundle in one rollback transaction. It does not edit
Claude's manifest. A missing retained source cache or failed generation leaves
the previous inputs and output unchanged. `--dry-run` does not generate.

The combined release ZIP retains `pstack/claude-code/` and `pstack/codex/`.
For a host API that takes a single plugin root, use
`build-plugin-archive.py pstack --target codex` or `--target claude-code`.
Those deterministic transport ZIPs contain one `pstack/` folder with the
selected `plugin.json` and complete host subtree. They have checksums distinct
from the combined release archive and are not additional release assets.

Only a verified tagged release is promoted. The release workflow supplies the
verified archive digest to `update-marketplace.py`; the helper verifies each
committed target's bytes and modes against the bundle record, then updates
both complete catalogs and `integrations/pstack/published.json` together.
Claude's entry selects `packages/pstack/claude-code` at its native version;
Codex selects `packages/pstack/codex`. Both reference the same bundle tag and
commit. Existing native entries retain their pins. Before the first verified
release, the published record is empty and neither catalog lists pstack.

Tagless version lookup reads the published bundle record, not Claude's native
version. Adapter-only releases may keep Claude's bytes and native version
unchanged. Changed Claude bytes at the same native version, or a native
version downgrade, block promotion because no supported host cache transition
has been established. Recovery uses a new downstream release; it does not
rewrite an immutable release or patch Claude's metadata. Repeated identical
promotion is a no-op; failed/interrupted local catalog writes are rolled back
before the next attempt. The repository commit publishes the three-file set
as one change.

Artifact checks do not certify live Codex host capabilities. Desktop and native
Cloud activation, original-history access and configured provider integrations
still require actual qualification before claiming those workflows are
supported. See the [pstack support boundary](pstack.md#support-boundary).

## Record what the release was tested with

CI tries each change with the Python and FFmpeg versions it installs. The
other tools are only tried by hand, so before a release, try the plugin once
with the real ones and write their versions into the
[Last tested with](compatibility.md#last-tested-with) table, in the same pull
request as the version bump:

```sh
yt-dlp --version
ffmpeg -version | sed -n '1p'
deno --version | sed -n '1p'
bird --version
make omlx-test        # watch-video, on a Mac with oMLX running
```

`make omlx-test` puts the read-only questions of `setup_local.py --check` to
the running oMLX server and fails when the helper no longer understands the
answers. It changes nothing in oMLX. The oMLX and Splash versions are in the
app's About window and in `splash --version`.

## Check what an agent does with the skill

The tests show what the scripts do. They cannot show what an agent does after
reading `SKILL.md`, and the consent rule lives there. Before a watch-video
release, and after any change to its `SKILL.md`, run the agent evals:

```sh
make agent-evals
```

This runs `claude plugin eval` on `packages/watch-video/evals/`. Each case
gives an agent the skill and one request, such as a private recording with
every API key set, and checks the command it answers with: no hosted
transcriber and no Gemini without the user's consent, and both when the user
gave it. The cases ask for the command only, so nothing is downloaded or
uploaded, and they are given no shell.

It needs Claude Code 2.1.269 or later, signed in. Every case runs three agent
sessions on your own account, and one case also asks a judge model, so a run
costs a little. The first run asks whether you trust the plugin directory.
Results are written to `packages/watch-video/evals/results/`, which Git
ignores. A case that scores below 1.0 fails the command: read the report it
names, then fix `SKILL.md` or the case.

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
just merged. It does not change versions or commit to `main`, except for the
marketplace update at the end.

Several plugins can be released at once. Each plugin has its own concurrency
group, and the marketplace push retries when `main` moves.

## What the workflow does

The workflow runs six jobs:

1. `ci` runs the full CI workflow on the exact commit, including macOS.
2. `validate` is read-only. When the optional `RELEASE_SETTINGS_TOKEN` secret
   is set, it first requires release immutability to be turned on; see
   [Repository settings](#repository-settings). `scripts/plan-plugin-release.py`
   refuses a tag that already exists and a version that is not the plugin's
   next one under [Versions and tags](#versions-and-tags), and the job also
   checks that the tag is absent on GitHub. It then builds and validates the
   ZIP and records its digest. The full check runs once, in `ci`.
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
   `main`, checks the result with `scripts/validate_plugins.py --marketplace`,
   and pushes one commit containing both complete catalogs. A pstack release
   also includes `integrations/pstack/published.json`; other paths are refused.
   It retries if `main` moved. The job installs nothing: that check needs only
   Git and the standard library.
6. `ci-on-main` starts a CI run on `main`. A push made with `GITHUB_TOKEN`
   starts no workflow, so the marketplace commit would otherwise have no CI
   result.

`verify` and `marketplace` are separate jobs so that **Re-run failed jobs**
can finish an interrupted release without publishing it again.

A native marketplace entry takes its version and description from `plugin.json`
at the release commit and pins the release tag and full commit SHA. It only
moves to a newer version. Pstack uses the selected host's native manifest
version and description while both entries pin the same downstream bundle
tag and commit.

The native archive contains one top-level plugin directory with `plugin.json`,
`LICENSE`, `README.md`, and the complete `skills/` tree. It excludes tests and
repository tooling, rejects symlinks and special files, and uses stable
timestamps and modes. Pstack archives retain the complete validated host trees,
including upstream fixtures; they follow the bundle layout described above.

## Verify a release

After the run succeeds, confirm:

- all six jobs passed, and so did the CI run that the last one started on
  `main`;
- `gh release verify <tag> --repo heyNag/charms` passes;
- `gh release verify-asset <tag> <zip> --repo heyNag/charms` passes for the
  downloaded ZIP;
- the entries in both catalogs on `main` name the expected native version,
  release tag, and commit; pstack's publication record also matches the verified
  bundle and archive;
- after `git pull` and `git fetch --tags`, `make check` passes locally.

## Repair a release

- `validate` failed because release immutability is off, or because GitHub
  refused the token in `RELEASE_SETTINGS_TOKEN`: nothing was published. Follow
  the `fix:` line in the job log and dispatch again.
- `publish` failed before the release existed: fix the cause on `main` and
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
  python3 scripts/validate_plugins.py --marketplace
  git commit -m "Point marketplace at watch-video <version>" \
    .claude-plugin/marketplace.json .agents/plugins/marketplace.json
  git push
  ```

  This example repairs a native release. For pstack, prefer rerunning the
  workflow so the verified archive digest is carried forward. A manual repair
  additionally requires `--archive-sha256 <verified-archive-sha256>` and must
  commit `integrations/pstack/published.json` together with both catalogs.

- `marketplace` refused the new entry: its log has an `error:` line from the
  marketplace check, and nothing was pushed. Fix what the line names on
  `main`, then use **Re-run failed jobs**.

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

   Changes still reach `main` through pull requests that are merged once CI
   is green; see [Development](development.md#branches-and-pull-requests).
   That is a working rule, which this ruleset does not enforce. To enforce
   it, the `marketplace` job would have to push with the token of a GitHub
   App that the ruleset names as a bypass actor, and the ruleset could then
   require pull requests and the CI checks. The workflow does not do that
   today.

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
