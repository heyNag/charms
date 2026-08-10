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

Create one new immediate child of `packages/`. The package name must use
lowercase letters, digits, and hyphens and must satisfy both the Agent Plugins
and Agent Skills name rules.

Required files:

```text
packages/<name>/plugin.json
packages/<name>/LICENSE
packages/<name>/README.md
packages/<name>/skills/<name>/SKILL.md
packages/<name>/tests/test_basic.py
```

Start the manifest at the version that will be published and keep its
`$schema` fixed to the supported v1 identifier. The skill description must
state its activation conditions. Add `compatibility` only for real runtime
requirements.

Add scripts or references inside the skill directory. Do not add a client
adapter, aggregate index, command wrapper, placeholder `mcp.json`, or a
second metadata source.

Update the root README, `packages/README.md`, and compatibility table so the
repository presents a complete current inventory.

## Versions

Each plugin uses Semantic Versioning:

- major for incompatible behavior or package-contract changes;
- minor for backward-compatible capabilities;
- patch for backward-compatible corrections.

Published version changes are performed by the Release Plugin workflow.
Ordinary source commits leave existing manifest versions unchanged.

## Review checklist

- `plugin.json` validates against the vendored v1 schema.
- The manifest, package directory, and skill names match.
- `SKILL.md` passes the official Agent Skills validator.
- Every bundled path stays inside the plugin root.
- Runtime data and secrets stay outside the package.
- Package behavior tests cover the change.
- Package and root documentation describe the resulting behavior.
- `make check` passes from a clean checkout.
