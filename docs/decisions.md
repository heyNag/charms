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
