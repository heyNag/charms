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
| `watch-video` | macOS or Linux, Python 3.9+. Local files need `ffmpeg` and `ffprobe` for local extraction; local URL runs also need `yt-dlp`, which needs a JavaScript runtime such as Deno for YouTube. Gemini needs network access and environment-supplied `GEMINI_API_KEY`, with no local binaries for supported YouTube URLs or local files; other URLs need the downloader toolkit. Remote media and hosted transcription need network access. Optional local ASR/VLM needs a separately configured loopback OpenAI-compatible server. |
| `x-bookmarks` | Python 3.9+ and either Bird with browser-cookie access or X API v2 OAuth credentials. Live retrieval requires network access. |

These requirements are also declared in each skill's `compatibility`
frontmatter and explained in its package README. Each plugin's scripts check
the Python version before anything else and stop with one line on an older
`python3`.

`watch-video` uses only Python's standard library for provider adapters. The CLI
defaults to local; the skill passes an explicit engine based on the task.
When both Gemini and local models are configured, YouTube visual/model requests
without an explicit route ask the user to choose once per video or batch. The
choice is preserved for follow-ups; exact visual work recommends local. Local
file/folder paths use configured local models directly, without a cloud-route
question. Speech-only tasks can use local transcript detail with existing
captions directly. Explicit choices and privacy constraints take priority.
Whether anything may be uploaded is decided by one rule, the skill's
[Uploads need consent](../packages/watch-video/skills/watch-video/SKILL.md#uploads-need-consent)
section: cloud use needs the user's consent for that source and provider.
The CLI defaults to no hosted transcription for every source, fresh URLs
included: Groq or OpenAI transcription runs only with an explicit
`--transcriber groq` or `--transcriber openai`.
`--analyzer local` defaults an omitted transcriber to local;
an explicit `--transcriber none` is respected. Local model failures never
select a hosted fallback. These clients use loopback endpoints only, with
separate speech and vision-language models, and do not install or start a runtime.
The explicit `setup_local.py --configure` workflow queues missing weights through
oMLX's native downloader into its configured model directory and sets the vision
alias/Splash options. It requires a running, configured native runtime.
Before that stage, `setup_local.py --preflight` detects Mac hardware and local
prerequisites without contacting a server, resolving secrets, or installing
anything. Its onboarding guidance distinguishes Splash M1 for M1/M2 from
official Splash for M3 or later. It does not establish model or inference readiness.
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

## Last tested with

A newer version of a tool usually works. This table records the versions a
release was last tried with, so that it is the first place to look when one
does not. Update the rows when a plugin is released; the
[release steps](releasing.md#record-what-the-release-was-tested-with) list the
commands.

| Tool | Version | How it is tried | Recorded |
| --- | --- | --- | --- |
| Python | 3.9, 3.11 and 3.15, and the `python3` of Apple's Command Line Tools | CI, on every change | 2026-11-14 |
| FFmpeg | 6.1.1 on the Ubuntu 24.04 runner, which still accepts `-vsync`; the build of the latest Ubuntu runner; and the current Homebrew build, which has dropped `-vsync` | CI, on every change. Each run prints the version it used | 2026-11-14 |
| yt-dlp, and Deno for it | Not recorded yet | A real URL run by hand: `doctor.py "<url>"`, then `watch.py "<url>" --detail transcript` | |
| oMLX and Splash | Not recorded yet. Splash must be 1.3.0 or later | `make omlx-test` against the running server, then a short `--transcriber local --analyzer local` run | |
| Bird | 0.8.0, read as source when the incremental fetch was written. No live run is recorded yet | `bird check --plain`, then a small fetch with each helper | 2026-11-14 |
| X API v2 | Not recorded yet | `x_api_auth.py --status`, then a small fetch | |
| Claude Code | 2.1.307 | A marketplace install | |
| Codex CLI | 0.147.0 | A marketplace install | |

"Not recorded yet" means that nobody wrote the version down, not that the
tool fails.

## Capability handling

A skill may describe an operation that its current host cannot perform. The
agent should use an available equivalent only when it preserves the skill's
safety and evidence requirements. Otherwise it should explain the missing
capability and offer a user-mediated step.

Host-specific tool names and permission grants are intentionally absent from
the portable packages. The host remains responsible for authorization,
sandboxing, confirmations, and credential access.
