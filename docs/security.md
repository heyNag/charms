# Security

Agent Plugins package instructions and executable helpers. Installing a plugin
does not make its code safe, sandbox it, or grant it permission to access local
data. Inspect the selected plugin and use the host's normal approval model.

## Package trust

Each Charms plugin is an independent trust boundary. Install only the plugin
you need, and inspect `plugin.json`, `SKILL.md`, and bundled scripts before
execution.

Charms validation enforces:

- fixed Agent Plugins v1 component locations;
- filesystem containment inside each plugin root;
- strict Agent Skills frontmatter;
- no package symlinks in release artifacts;
- an allowlisted deterministic archive;
- marketplace entries pinned to an existing release tag and commit;
- scans for tracked secrets and runtime artifacts.

## Release integrity

Every Charms GitHub release is immutable: once published, its assets cannot
change and its tag name cannot be reused, even after the release is deleted.
The release workflow fails, and leaves the marketplace unchanged, unless the
release is immutable and its attestation verifies. A tag ruleset also blocks
updates and deletions of `<name>--v<version>` tags; see
[Repository settings](releasing.md#repository-settings).

Marketplace entries pin the release tag and the full release commit SHA, and
Claude Code and Codex install from that SHA. The release workflow writes an
entry only after the release is published and verified, and
`scripts/update-marketplace.py` refuses a tag that does not point at the
pinned commit. Skill-only installs through Skillshare or the skills CLI follow
`main` instead and are not release content.

Verify a release and a downloaded ZIP before extraction:

```sh
gh release verify <tag> --repo heyNag/charms
gh release verify-asset <tag> <zip> --repo heyNag/charms
```

The `.sha256` asset also works with `sha256sum --check`.

## Credentials

Never commit or paste into issue logs:

- API keys or OAuth client secrets;
- browser cookies or session tokens;
- Codex authentication or rollout records;
- X bookmark exports or OAuth state;
- Mnemosyne databases or private memory exports;
- private media, transcripts, frames, or reports.

Skills must read credentials from the runtime environment or documented
user-local configuration and redact them from output. A plugin must not place
secrets in `plugin.json`, `SKILL.md`, release archives, or committed test
fixtures.

## Plugin-specific boundaries

### chatgpt-pro-review

Sending repository context to ChatGPT is an external disclosure. The skill
requires authorization for the specific private context, excludes unrelated
files and secrets, and reconciles the response against local evidence.

### codex-reset-credit

The helper is read-only. It sanitizes live and local results and must not print
tokens, account identifiers, raw authentication files, or unredacted session
records.

### mnemosyne-memory

The package does not bundle a server or memory database. The host's configured
Mnemosyne profile owns data isolation. The skill excludes credentials, raw
transcripts, noisy output, broad maintenance, and destructive memory
operations from automatic use.

### watch-video

Media and derived artifacts remain local unless the user selects hosted
transcription. Groq or OpenAI transcription sends audio to that provider.
Generated media, transcripts, and frames must not enter source control or
release archives.

### x-bookmarks

Browser cookies and OAuth tokens stay in user-local state. The skill requests
read-only scopes by default and adds write scope only for an explicit bookmark
mutation.

## Reporting

Report security issues through
[GitHub private vulnerability reporting](https://github.com/heyNag/charms/security/advisories/new)
before public disclosure. Include the affected plugin, version, impact,
reproduction steps, and any proposed fix without including live credentials or
private data.
