# Development

## Setup

Use Python 3.11 or newer for the repository tooling:

```sh
python3 -m pip install -r requirements-dev.txt
make check
```

The plugins themselves support Python 3.9, so code under `packages/` stays
within Python 3.9's syntax and standard library. See
[Python versions](#python-versions).

`requirements-dev.txt` pins the three development tools and every package they
pull in. CI installs them with `make dev-deps`, which installs those lines and
nothing else, then runs `pip check`: a tool that starts to need a package the
file does not list fails the run, so add the package to the file. Dependabot
opens at most one pull request a month for these pins and one for the actions
pinned in the workflows; see `.github/dependabot.yml`.

Validation uses a vendored copy of the immutable Agent Plugins v1 manifest
schema and the official Agent Skills reference validator.

`make check` also validates `.claude-plugin/marketplace.json` against the
release tags, so it needs them locally. Fetch them if your clone lacks them:

```sh
git fetch --tags
```

## Change a plugin

Edit only the plugin root that owns the behavior:

```text
packages/<name>/
├── plugin.json
├── README.md
├── LICENSE
├── skills/<name>/
└── tests/
```

Keep instructions, scripts, references, and package tests together. A skill
must resolve its bundled files relative to its own directory so the released
package works outside this repository.

Run the focused tests while iterating:

```sh
PLUGIN=watch-video
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "packages/${PLUGIN}/tests" -p 'test_*.py'
python3 scripts/validate_plugins.py "packages/${PLUGIN}"
```

Then run the complete check before committing:

```sh
make check
```

A file that a plugin writes while it runs must never be committed. The list of
such files is in `scripts/validate_plugins.py`, and `.gitignore` carries a
line for each entry; validation fails when a line is missing. When a
watch-video run starts to create a new file or folder, name it in
`RUN_FILES` or `RUN_FOLDERS` in `prune_runs.py`, in the validator's list, and
in `.gitignore`. `make check` fails until all three have it.

## Branches and pull requests

Skill-only installs take whatever `main` holds, so `main` has to stay fit to
use at every commit:

1. Work on a short-lived branch, one change to a branch.
2. Open a pull request. CI runs on pull requests and on `main`, not on a
   branch by itself, so open one, as a draft if need be, to get a run.
3. Merge when every CI job is green, then delete the branch.

Dependabot's pull requests follow the same rule. Only the release workflow
pushes to `main` directly, for the marketplace commit, which it validates
first.

This is a working rule, not one the repository enforces: the branch ruleset
on `main` cannot require a pull request or a status check. See
[Repository settings](releasing.md#repository-settings) for the reason and
for what enforcing it would take.

## Python versions

Each plugin states its oldest supported Python once, as `MIN_PYTHON` in
`skills/<name>/scripts/python_floor.py`. Every script that can be run directly
imports `python_floor` before any other module of the skill, so an older
`python3` stops with one line instead of a traceback. A package test starts
each script that way and fails if a new one skips the import.

Three checks keep the plugins inside that floor:

- Ruff treats `packages/` as Python 3.9 code and reports newer syntax as an
  error. The rest of the repository targets Python 3.11.
- `make test-plugins` runs only the plugin tests. They need no development
  dependencies, so they also run on a bare Python 3.9:
  `make test-plugins PYTHON=python3.9`. Without `jsonschema`, one schema
  cross-check is skipped.
- CI runs the plugin tests on Python 3.9 and the complete check on Python 3.11
  and the newest release.

To raise the floor, change `MIN_PYTHON` in each plugin, the `compatibility`
line of each `SKILL.md`, the Ruff target in `pyproject.toml`, the Python
version of the `python-floor` CI job, and the documented requirement in the
package READMEs and [Compatibility](compatibility.md).

## Add a plugin

Create one new immediate child directory of `packages/`. The package name must
use lowercase letters, digits, and hyphens and must satisfy both the Agent
Plugins and Agent Skills name rules.

Required files:

```text
packages/<name>/plugin.json
packages/<name>/LICENSE
packages/<name>/README.md
packages/<name>/skills/<name>/SKILL.md
packages/<name>/tests/test_basic.py
```

A plugin with Python scripts also carries its own
`skills/<name>/scripts/python_floor.py` and `plugin_version.py`; copy them
from an existing plugin and change `PLUGIN` in each.

Set the manifest version to `1.0.0` and keep its `$schema` fixed to the
supported v1 identifier. The skill description must state its activation
conditions. Add `compatibility` only for real runtime requirements.

Keep scripts and references inside the skill directory, plugin metadata in
`plugin.json`, and skill metadata in `SKILL.md`. The current Charms package
contract is skill-only and does not accept `mcp.json`.

Update the root README, `packages/README.md`, and compatibility table so the
repository presents a complete current inventory. Do not add a marketplace
entry; the first release adds it.

## Versions

Each plugin uses Semantic Versioning, `MAJOR.MINOR.PATCH`, and starts at
`1.0.0`. Bump the version in a normal commit when the plugin is ready to
release:

```sh
python3 scripts/bump-plugin-version.py watch-video minor
```

The second argument is `major`, `minor`, or `patch`. Add `--dry-run` to print
the next version without changing `plugin.json`.

`plugin.json` is the only place a version is written. The scripts read it
through `skills/<name>/scripts/plugin_version.py`, which supplies what
`--version` prints, the `User-Agent` on requests and, for watch-video, the
doctor header and the `plugin_version` saved in a run's `metadata.json`. A
copy of a skill without its plugin folder has no manifest and reports
`unknown`.

Commits on `main` do not reach marketplace installs until a release. A version
may never be reused or go below a released one, and validation fails if a
package's version is lower than its marketplace entry. See
[Releasing](releasing.md).

## CI

The CI workflow runs on every pull request and on every push to `main`. A
newer push to a pull request cancels the run of the older one. The release
workflow reuses CI on the commit being released, and starts it once more on
`main` after it pushes the marketplace commit:

- the Ubuntu job runs `make ci` on Python 3.11 and on the newest Python
  release, with the FFmpeg that its runner image packages, and requires the
  checks to leave the working tree clean;
- the Python floor job runs `make test-plugins` on Python 3.9 with nothing
  installed from `requirements-dev.txt`. Its older runner image packages an
  FFmpeg that accepts both `-fps_mode` and `-vsync`. The job asserts that,
  because the test of the `-vsync` fallback is skipped on any other build;
- the macOS job installs current Homebrew FFmpeg and asserts that it lacks
  `-vsync`, which shows that the plugin passes `-fps_mode` to a build that
  dropped the old option. It runs `make test` on the newest Python release,
  then `make test-plugins` on the `python3` that Apple's Command Line Tools
  provide.

When a new Python release reaches `actions/setup-python`, raise the newest
version in `.github/workflows/ci.yml`.

## Review checklist

- `plugin.json` validates against the vendored v1 schema.
- The manifest, package directory, and skill names match.
- `SKILL.md` passes the official Agent Skills validator.
- Every bundled path stays inside the plugin root.
- Runtime data and secrets stay outside the package.
- Package behavior tests cover the change.
- Package and root documentation describe the resulting behavior.
- A version bump, when needed, uses `scripts/bump-plugin-version.py`.
- The change is on a branch, and CI is green on its pull request before the
  merge.
- `.claude-plugin/marketplace.json` is unchanged; only releases update it.
- `make check` passes from a clean checkout with release tags fetched.
