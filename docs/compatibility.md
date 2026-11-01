# Compatibility

Every Charms package targets Agent Plugins v1.0.0 and currently provides one
Agent Skill. A client must support the Agent Plugins manifest and Agent Skills
component type to discover it.

## Clients

Claude Code and Codex are the first-class clients. Both install from the
`charms` marketplace at `.claude-plugin/marketplace.json` and fetch
`packages/<name>/` at the pinned release commit SHA.

| Client | Support | Minimum version | How it installs a package |
| --- | --- | --- | --- |
| Claude Code | First-class, tested | No documented minimum; tested with 2.1.307 | Reads the marketplace entry, fetches the package at the pinned `sha`, and loads the skill from `skills/<name>/`. |
| Codex | First-class, tested | CLI 0.147.0 | Reads the Claude-format marketplace natively, fetches the package at the pinned `sha`, and loads its root Agent Plugins `plugin.json` and skill. |
| Other Agent Plugins clients, such as VS Code, GitHub Copilot CLI, and Cursor | Best-effort, not tested | Client-specific | Load a release ZIP or a `packages/<name>/` checkout through the client's own flow. |
| Agent Skills hosts without plugins | Skill only | Client-specific | Install `packages/<name>/skills/<name>/` from `main` with Skillshare or the skills CLI. |

Codex 0.147.0 is the first release that installs root Agent Plugins
`plugin.json` packages from a marketplace. The marketplace entry and the
package's `plugin.json` at the release commit always carry the same name,
version, and description; validation enforces it.
See [Installation](installing.md) for commands.

The Agent Plugins project maintains a broader client list:
[Compatible Clients](https://agent-plugins.org/compatible-clients).
Conformance establishes package discovery and validation; it does not imply
that every client exposes the same tools, permissions, browser access, local
filesystem access, or approval interface.

## Runtime requirements

| Plugin | Required environment |
| --- | --- |
| `watch-video` | macOS or Linux, Python 3.11+. Local files need `ffmpeg` and `ffprobe` for local extraction; local URL runs also need `yt-dlp`. Gemini needs network access and environment-supplied `GEMINI_API_KEY`, with no local binaries for supported YouTube URLs or local files; other URLs need the downloader toolkit. Remote media and hosted transcription need network access. Optional local ASR/VLM needs a separately configured loopback OpenAI-compatible server. |
| `x-bookmarks` | Python 3.11+ and either Bird with browser-cookie access or X API v2 OAuth credentials. Live retrieval requires network access. |

These requirements are also declared in each skill's `compatibility`
frontmatter and explained in its package README.

`watch-video` uses only Python's standard library for provider adapters. The CLI
defaults to local; the skill passes an explicit engine based on the task.
When both Gemini and local models are configured, YouTube visual/model requests
without an explicit route ask the user to choose once per video or batch. The
choice is preserved for follow-ups; exact visual work recommends local. Local
file/folder paths use configured local models directly, without a cloud-route
question. Speech-only tasks can use local transcript detail with existing
captions directly. Explicit choices and privacy constraints take priority. Private/local,
unlisted, login-required, and meeting recordings stay local. Use configured
local ASR/VLM for original audio and frames, or `--transcriber none` with provided
captions. Hosted transcription requires approval. Other or unclear sources use local unless Gemini is requested;
for uncertain privacy, use `--transcriber local` when configured, otherwise
`--transcriber none` unless hosted ASR is approved.
The CLI also defaults to no hosted transcription for local files and cached
runs. Cloud use requires the user's consent for that source and provider;
a configured API key is not consent. Fresh URL runs retain Groq as the CLI
fallback, so agents must explicitly disable it for private or uncertain URLs.
`--analyzer local` defaults an omitted transcriber to local rather than Groq;
an explicit `--transcriber none` is respected. Local model failures never
select a hosted fallback. These clients use loopback endpoints only, with
separate speech and vision-language models, and do not install or start a runtime.
The explicit `setup_local.py --configure` workflow queues missing weights through
oMLX's native downloader into its configured model directory and sets the vision
alias/Splash options. It requires a running, configured native runtime.
The vision-language model receives ASR text rather than raw audio.

With `--engine gemini`, supported YouTube URLs are passed directly to Google,
while local files and downloaded non-YouTube videos are uploaded. Local-only
extraction/transcription flags are rejected for that engine. Gemini access,
model availability, and quota depend on the user's Google project.

`doctor.py "<source>" --engine local|gemini --check` checks the selected route;
`--json` returns structured results. `--install` and setup hints cover only that
route's binaries. The default engine is local. Cached local runs can pass
`--from-run` to skip the downloader check. Without a source or `--from-run`,
doctor checks the full local toolkit, even when Gemini is selected. Its Gemini key check is
advisory and presence-only; it does not validate API access or quota. Pass
`--transcriber local --analyzer local` to validate local endpoint configuration
and report model prerequisites; no server connection or model loading occurs.

Scripts do not automatically route or fall back. If Gemini was selected only
because it was the available configured route, the agent may disclose a local
evidence fallback after at most one transient-error retry. If the user chose
Gemini, ask before switching unless fallback was already authorized; an explicit
Gemini-only request must not fall back. Targeted local verification
can supplement Gemini's findings.

Local frame output supports JPEG, PNG, and WebP; WebP requires an FFmpeg build
with the encoder. Full scene output remains bounded at 300 frames; uniform
sampling and its fallbacks remain bounded at 100. A complete `evidence.json`
index accompanies local runs, while Gemini returns an attributed
`analysis.json` and report. These artifacts serve different evidence workflows;
an agent needs image-reading capability to inspect local frames. Optional local
model analysis adds `local_analysis.json`, `local_analysis.md`, and persisted
batch results. The host must retain their provenance, uncertainty, and gaps.

## Capability handling

A skill may describe an operation that its current host cannot perform. The
agent should use an available equivalent only when it preserves the skill's
safety and evidence requirements. Otherwise it should explain the missing
capability and offer a user-mediated step.

Host-specific tool names and permission grants are intentionally absent from
the portable packages. The host remains responsible for authorization,
sandboxing, confirmations, and credential access.
