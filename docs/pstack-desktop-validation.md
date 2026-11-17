# Validate pstack on Desktop

Use a local test marketplace to validate this unreleased bundle in the Desktop
app. Fetching the repository supplies the files; installation and a fresh
Desktop conversation establish whether the host actually loads them.
`pstack@charms` is not published yet.

These steps follow OpenAI's [local plugin installation guidance](https://developers.openai.com/plugins/build/plugins/):
add a local marketplace through the CLI, restart the ChatGPT desktop app, then
install and test from its Plugins Directory in Codex mode. The documented route
was checked on 2026-11-17. The user's actual app build still needs validation;
CLI installation alone does not prove Desktop activation.

The current documentation calls the desktop application ChatGPT, while the
[official Codex launcher](https://github.com/openai/codex/blob/e5839cbc591df02408d5009e287887c7d57a9167/codex-rs/cli/src/desktop_app/mac.rs#L67)
recognizes both `Codex.app` and `ChatGPT.app` with the same `com.openai.codex`
bundle identifier. The standalone app's name therefore does not rule out this
route. Validate the installed build and its actual plugin activation below;
an older ChatGPT application with bundle identifier `com.openai.chat` is not
the application selected by that launcher.

## Get the branch on your Mac

From an existing `charms` checkout:

```sh
git fetch origin
git switch heyNag/pstack-codex-01543
git pull --ff-only origin heyNag/pstack-codex-01543
git rev-parse HEAD
codex --version
python3 --version
```

`git switch` can create the local tracking branch when that name exists only
on `origin`. If local edits prevent switching, preserve them before continuing.
Record the commit, Desktop app version/build from its About screen, and macOS
version. The runtime requires **Python 3.11 or newer**. The CLI must expose
`codex plugin marketplace add --help`; no Desktop minimum build has been
certified here.

This test targets bundle `2026.11.0`, based on pstack `0.15.43` at upstream
commit `2f87c854fe3e2fcda44ca86b46ede35aad3c46b7`. No regeneration is needed
after pulling the committed bundle.

## Create an isolated test source

Run from the repository root. This creates a fresh external copy, including
hidden manifests and executable modes, and leaves the repository's release
catalogs and existing personal marketplace unchanged.

```sh
PSTACK_TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/charms-pstack-2026.11.0.XXXXXX")"
mkdir -p "$PSTACK_TEST_ROOT/.agents/plugins" "$PSTACK_TEST_ROOT/plugins"
cp -pR packages/pstack/codex "$PSTACK_TEST_ROOT/plugins/pstack"

cat > "$PSTACK_TEST_ROOT/.agents/plugins/marketplace.json" <<'JSON'
{
  "name": "charms-pstack-dev-2026-11-0",
  "interface": {"displayName": "Charms pstack Desktop test"},
  "plugins": [
    {
      "name": "pstack",
      "source": {"source": "local", "path": "./plugins/pstack"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
JSON

PSTACK_EXPECTED_MANIFEST="$(python3 -c 'import json; print(json.load(open("packages/pstack/bundle.json"))["targets"]["codex"]["payload_manifest_sha256"])')"
python3 "$PSTACK_TEST_ROOT/plugins/pstack/adapters/codex/runtime/pstack_runtime.py" \
  verify --root "$PSTACK_TEST_ROOT/plugins/pstack" \
  --expected-manifest "$PSTACK_EXPECTED_MANIFEST"

codex plugin marketplace add "$PSTACK_TEST_ROOT"
```

The expected manifest comes from the reviewed checkout, not from the installed
copy asserting its own identity. A successful `verify` proves the copy matches
that artifact; it does not prove native discovery or instruction activation.
Keep this temporary source directory for the whole test. If this test
marketplace is already registered, use the cleanup steps before creating
another copy under the same marketplace name.

Restart the Desktop app. In **Plugins Directory**, select **Charms pstack
Desktop test**, install **pstack**, then start a **new local Codex conversation**.
Select only the Codex target; the aggregate `packages/pstack/` directory and
the sibling Claude target are not Codex installation roots. If the app has no
local marketplace source or this directory does not appear, record its build
and that failure before proceeding; shell access to the checkout is not a
substitute for plugin activation.

## Exercise the installed plugin

First select `pstack:poteto-help` through the skill picker in a new local Codex
conversation. Alternatively, send this prompt as an actual user message:

```text
$pstack:poteto-help
Read-only Desktop smoke test. Resolve the installed pstack skill through its
runtime. Report the installed root, upstream version, bundle version, and
effective instruction path. Explain which pstack workflow fits a read-only
code investigation. Do not edit files, install dependencies, create commits
or PRs, or contact external services.
```

The model's default skill catalog is not the complete installed inventory.
Pstack intentionally exposes only `setup-pstack` there; its other 57 skills
set `allow_implicit_invocation: false`. Those skills remain eligible for explicit
selection. Their absence from the default catalog is expected and does not
establish an activation failure. Check the native picker or the host's complete
skill inventory separately from the model-visible list.

An app-tool `create_thread` prompt can arrive as delegated tool output rather
than a skill-bearing user input. A literal `$pstack:poteto-help` in that output
does not test the native explicit-invocation path. Record that transport as an
untested activation route; do not infer a plugin defect or require a restart
solely because the new agent's default catalog omits manual-only skills.

Then try a small real read-only investigation with `$pstack:poteto-mode` in a
disposable project. Keep the deployment profile `default`. If setup is needed,
use `$pstack:setup-pstack` and review the actual offered model choices; do not
invent a model catalog or enable providers just to make the test pass.

Missing model preferences alone do not prohibit all delegation. Follow the
selected workflow's fallback order and disclose any permitted fallback to the
parent model. Preserve requirements for distinct vendors or independent review;
parent-model fallback cannot satisfy a caller that requires another vendor.

Record observed tool calls and artifact identities against these criteria:

| Check | Passing evidence |
| --- | --- |
| Discovery | One installed pstack plugin, with 58 skill definitions. Its 57 manual-only policies survive installation; only `setup-pstack` permits implicit invocation. The default model catalog may therefore list only `setup-pstack`. Check manual skills through the complete host inventory or picker. Benny's three internal procedures are not registered as additional skills. |
| Native activation | The fresh Desktop conversation can explicitly select and invoke `pstack:poteto-help`. An unrelated conversation does not implicitly start a manual-only pstack mode. |
| Installed identity | The installed root passes the runtime `verify` command against `PSTACK_EXPECTED_MANIFEST`. Verify the actual installed copy reported by the host, not just the checkout or test source. |
| Complete instructions | The invocation runs `resolve`, reads the adapter and effective `instructions.md`, and uses the same verified resource root for linked files. Reading only the short `SKILL.md` descriptor is insufficient. |
| Internal routing and workers | A read-only mode task resolves its selected playbook and any sibling skills from that payload. If delegation is used, a fresh worker receives the verified `worker.md` pointer first and the actual role/mode resources. Record this separately as blocked if the required model or worker capability is unavailable. |
| Persistence and limits | A new conversation after restart still resolves the same installation and `default` profile. Missing history, providers or durable automation produce explicit incomplete outcomes, without fabricated success or silent fallback. |

For example, once the app reports the actual installed root, run its
`adapters/codex/runtime/pstack_runtime.py verify --root <installed-root>
--expected-manifest "$PSTACK_EXPECTED_MANIFEST"`. Do not guess the newest cache
directory. Installed cache contents are immutable; change the test source and
reinstall/restart when testing a new build.

Passing discovery and help establishes a Desktop installation smoke test.
It does not certify every workflow. Statechart additionally needs its Node/Java/TLC
toolchain and actual artifact/Stop tests; the watcher needs its Bun/GitHub
execution checks. Missing required capabilities remain blocked acceptance
cases, even when their error reporting is correct. See the
[support boundary](pstack.md#support-boundary) for remaining host/provider work.

## Remove the test installation

The inspected CLI supports these commands:

```sh
codex plugin remove pstack@charms-pstack-dev-2026-11-0
codex plugin marketplace remove charms-pstack-dev-2026-11-0
```

Restart the app and confirm that this test plugin is gone. You can then delete
the recorded temporary source directory. These commands target only this test
marketplace; they do not remove the published Charms marketplace or its plugins.
