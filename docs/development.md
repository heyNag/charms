# Development

## Setup

Use Python 3.11 or newer:

```sh
python3 -m pip install -r requirements-dev.txt
make check
```

The development dependencies are pinned in `requirements-dev.txt`. Validation
uses a vendored copy of the immutable Agent Plugins v1 manifest schema and the
official Agent Skills reference validator.

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

Commits on `main` do not reach marketplace installs until a release. A version
may never be reused or go below a released one, and validation fails if a
package's version is lower than its marketplace entry. See
[Releasing](releasing.md).

## CI

The CI workflow runs on every push and pull request, and the release workflow
reuses it on the commit being released:

- the Ubuntu job installs Ubuntu's packaged FFmpeg, which still accepts
  `-vsync`, and runs `make ci`;
- the macOS job installs current Homebrew FFmpeg, asserts that it lacks
  `-vsync` so the `-fps_mode` path is covered, and runs `make test`.

## Review checklist

- `plugin.json` validates against the vendored v1 schema.
- The manifest, package directory, and skill names match.
- `SKILL.md` passes the official Agent Skills validator.
- Every bundled path stays inside the plugin root.
- Runtime data and secrets stay outside the package.
- Package behavior tests cover the change.
- Package and root documentation describe the resulting behavior.
- A version bump, when needed, uses `scripts/bump-plugin-version.py`.
- `.claude-plugin/marketplace.json` is unchanged; only releases update it.
- `make check` passes from a clean checkout with release tags fetched.
