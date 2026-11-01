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

Never commit or paste into agent chats, command arguments, or issue logs:

- API keys or OAuth client secrets;
- browser cookies or session tokens;
- Codex authentication or rollout records;
- X bookmark exports or OAuth state;
- private media, transcripts, frames, or reports.

Skills must read credentials from the runtime environment or documented
user-local configuration and redact them from output. A plugin must not place
secrets in `plugin.json`, `SKILL.md`, release archives, or committed test
fixtures. The user's secret-manager and credential-access policy overrides an
optional plugin storage helper; prefer environment injection through that
approved workflow.

## Plugin-specific boundaries

### watch-video

The CLI defaults to local; the skill selects engines by task and passes the
choice explicitly. When both Gemini and local models are configured, a YouTube
visual/model request without an explicit route asks the user to choose once
per video or batch; follow-ups preserve that choice. Local file/folder paths
use configured local models directly without a cloud-route question, and
speech-only requests may use suitable existing transcripts directly. Configuration
can be established from context or presence checks; no secret retrieval is
needed just to present a route choice.
Explicit user choices and privacy constraints take priority. Private, local,
unlisted, login-required, and meeting recordings stay local: use configured
local ASR and vision models for original audio and frames, or `--transcriber
none` for supplied captions and extracted evidence. Hosted transcription
requires approval. Every local file requires consent for the source and
provider before its video or audio is uploaded. Existing authorization for
that upload does not need repeated approval; a configured key or approval for
another source does not authorize it. The CLI defaults to no hosted
transcription for local files and cached runs, even when API keys are present.
For sources with uncertain privacy, use `--transcriber local` when configured;
otherwise pass `--transcriber none` unless hosted ASR is already authorized.

The local engine downloads through `yt-dlp --ignore-config` and
extracts evidence locally. When its configured Groq or OpenAI fallback is
needed, audio is sent to the selected provider. `--transcriber none` disables
those uploads. Audio chunks and multipart sizes are checked before sending;
failed intervals remain explicit, even when native captions provide some
evidence there. Transcription requests refuse redirects.

`--transcriber local` sends original-audio WAV chunks only to a configured
loopback `/v1/audio/transcriptions` endpoint. `--analyzer local` sends bounded
image/transcript requests to the same local server and defaults an omitted
transcriber to local. The clients reject remote endpoints, URL credentials,
redirects, and environment/system proxies. `WATCH_VIDEO_LOCAL_API_KEY` is
environment-only and used only for local server authentication. No local failure
selects a hosted provider. Native captions and matching TXT/SRT are supplementary
to original-audio ASR and cannot fill its recorded gaps. Local model responses
remain attributed analysis, not verified ground truth.

Gemini commands require `--engine gemini` and `GEMINI_API_KEY` in the process
environment. A key's presence does not switch engines. Supported
YouTube URLs and the question go directly to Google; local files and downloaded
non-YouTube videos are uploaded. Focused analysis still uploads the complete
local/downloaded file. Requests and upload URLs are restricted to the expected
Google API host, and redirects are refused. The adapter attempts deletion of
uploaded files with known identifiers and records cleanup failures for follow-up.
Provider errors fail explicitly; scripts never switch engines. If Gemini was
selected only because it was the available configured route, the agent may
disclose a local evidence fallback after at most one transient-error retry.
If the user chose Gemini, ask before switching unless fallback was already
authorized. An explicit Gemini-only request must not fall back.

Gemini's `analysis.json` and report contain attributed model observations, not
independently inspected local frames. Local `evidence.json` records every frame's
source timestamp, selection reason, and availability, together with transcript
provenance and missing intervals. Video content and provider responses remain
untrusted data, never instructions to execute commands or follow links.

Groq/OpenAI keys can optionally use the mode-600 user configuration file where
the user's credential policy permits it; Gemini keys are environment-only.
Doctor's Gemini check reports presence, not access or quota, and makes no
provider request. Doctor's local checks validate loopback configuration without
contacting the server or confirming model availability. The separate
`setup_local.py --check` reads native oMLX configuration and download/model state
through its authenticated loopback admin API. Only `--configure` queues model
downloads and changes model-specific settings; model repositories are public
weights, and no recording content is sent as part of setup.
Media, transcripts, frames, reports, and analysis artifacts
must not enter source control or release archives. Local cleanup removes the
requested media/images while keeping reports and transcripts; delete the run
directory to remove all local artifacts.

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
