# Decisions

Lightweight architecture decisions for `agent-tools`.

## 2026-06-19: Repository Name

Decision: Use `agent-tools`, not `agent-skills`.

Reason: The repo is meant to hold skills, commands, plugins, helper scripts, and
MCP experiments. A broader name avoids prematurely narrowing the scope.

## 2026-06-19: Hybrid Incubator

Decision: Use this repo as a hybrid incubator.

Reason: Packages can start here while their shape is still changing. If a tool
becomes independently useful or needs separate release management, it can later
graduate into its own standalone repo.

## 2026-06-19: Separate Local Package And MCP Placeholder

Decision: Keep `packages/watch-video` and `mcp/watch-video` separate.

Reason: The local skill/scripts package is useful now. The MCP server is a
future deployable shape and should not force the local package into a server
architecture too early.

## 2026-06-19: Default Groq Model

Decision: Use Groq `whisper-large-v3-turbo` as the default transcription model.

Reason: It is fast and practical for local video analysis fallback when native
captions are unavailable.

## 2026-06-19: Live API Tests Stay Manual

Decision: Keep live Groq and network tests manual/local, not required in CI.

Reason: CI should pass without secrets, paid services, or network-sensitive
fixtures. Behavior that can be tested offline should have normal tests.

## 2026-06-19: No MCP Gateway For Now

Decision: Do not build an MCP gateway.

Reason: The current need is local tooling plus independently deployable MCP
server shapes. A gateway would add architecture before there is a clear need.

## 2026-06-19: Committed Public Package Outputs

Decision: Commit generated public package outputs under `generated/` and
`.claude-plugin/`.

Reason: Users and future agents should be able to install Claude Code plugins
and Codex/generic skills without learning the internal source layout. Source
still lives under `packages/`; generated outputs are rebuilt from scratch with
`make rebuild-generated` and checked with `make verify-packages`.

## 2026-06-19: Package Manifests Declare Targets

Decision: Future packages use `packages/<name>/tool.json` to declare public
status, install targets, and MCP presence.

Reason: A small manifest keeps build and verification scripts generic without
adding a package framework. New packages can follow the same shape when they are
ready for public distribution.

## 2026-06-19: Auto Frame Budgeting With Hard Caps

Decision: Use automatic frame budgeting by default while keeping manual interval
mode available.

Reason: Short focused clips need denser coverage, while long videos need sparse
bounded extraction. The hard limits of 100 frames and 2 fps keep local agent
runs practical and predictable.

## 2026-06-19: Caption-First Transcription

Decision: Prefer native captions, especially manual English captions, before
using paid transcription fallback.

Reason: Native captions are faster, cheaper, and often higher quality for
YouTube sources. Groq or OpenAI fallback should be used when captions are
missing or suspiciously incomplete.

## 2026-06-19: OpenAI Fallback Uses Whisper-1

Decision: Keep Groq as the default fallback and support optional OpenAI
transcription with `whisper-1` as the default model.

Reason: `watch-video` needs verbose JSON segment timestamps. `whisper-1` is the
compatible OpenAI default for that response shape, while newer transcription
models can be selected manually if the API response shape supports the workflow.
