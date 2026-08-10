# Releasing

Each Charms plugin is released independently from its canonical
`packages/<name>/plugin.json` version.

## Version and tag contract

Versions use Semantic Versioning. Release tags use:

```text
agent-plugin/<name>/v<version>
```

For example:

```text
agent-plugin/watch-video/v1.2.0
```

The `Release Plugin` workflow accepts one plugin and one version action:

- `current` publishes the version already recorded in `plugin.json`;
- `patch`, `minor`, or `major` computes, commits, and publishes the
  corresponding next version.

The workflow rejects an existing destination tag. One invocation can publish
only one plugin.

## Run a release

The source branch must be `main` and repository checks must pass:

```sh
make check
git status --short
```

Dispatch from GitHub Actions or with GitHub CLI:

```sh
gh workflow run release-plugin.yml \
  --repo heyNag/charms \
  --ref main \
  -f plugin=watch-video \
  -f bump=patch
```

Use `bump=current` only when the manifest already contains the exact version
that should be published.

Release multiple plugins sequentially and wait for each run to finish before
starting the next one.

## Workflow guarantees

The workflow separates validation from publication:

- the validation job has read-only repository access, installs the pinned
  development dependencies, prepares the proposed version, runs the complete
  check, and records the deterministic archive digest;
- the publication job has repository write access, installs no third-party
  packages, requires `main` to remain at the validated commit, reapplies the
  exact proposed version, and rebuilds the archive from the final commit.

Publication then:

1. commits and pushes only the selected manifest when a bump was requested;
2. requires the final archive digest to match the read-only validated digest;
3. creates the namespaced tag and GitHub release;
4. uploads the ZIP and SHA-256 checksum;
5. verifies the tag target, release state, and exact asset names.

The archive contains one top-level plugin directory with `plugin.json`,
`LICENSE`, `README.md`, and the complete `skills/` tree. It excludes
tests and repository tooling, rejects symlinks and special files, and uses
stable timestamps and modes.

## Verify a release

For the released plugin, confirm:

- the workflow concluded successfully;
- the tag targets the intended commit;
- the tagged manifest contains the released version;
- the GitHub release is published and not a draft or prerelease;
- the ZIP and checksum assets exist;
- SHA-256 verification and `unzip -t` pass;
- the extracted plugin passes `scripts/validate_plugins.py`;
- the extracted allowlisted files match the tagged source;
- local `main` is fast-forwarded to the remote tip and `make check` passes.

## Repair an interrupted publication

Inspect the remote branch, tag, release, and assets before retrying:

- if no version commit reached `main`, correct the issue and run the workflow;
- if the version commit reached `main` but the release is absent, publish
  that exact committed version;
- if the release exists but an asset is absent, upload the missing artifact;
- never request another version bump merely to repair a tag, release, or upload.
