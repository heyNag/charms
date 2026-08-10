# Compatibility

Every Charms package targets Agent Plugins v1.0.0 and currently provides one
Agent Skill. A client must support the Agent Plugins manifest and Agent Skills
component type to discover it.

The current client matrix is maintained by the Agent Plugins project:
[Compatible Clients](https://agent-plugins.org/compatible-clients).
Conformance establishes package discovery and validation; it does not imply
that every client exposes the same tools, permissions, browser access, local
filesystem access, or approval interface.

## Runtime requirements

| Plugin | Required environment |
| --- | --- |
| `chatgpt-pro-review` | Access to ChatGPT Pro or Extended Pro through an approved browser or user-mediated transport. Local file, Git, and test access improve evidence reconciliation. |
| `codex-reset-credit` | Python 3.11+, local Codex authentication and session data, plus network access for live reset-credit checks. Local rate-limit checks can run offline. |
| `mnemosyne-memory` | A host-configured Mnemosyne MCP server exposing the required `mnemosyne_*` tools. |
| `watch-video` | macOS or Linux, Python 3.11+, `yt-dlp`, `ffmpeg`, and `ffprobe`. Remote media and hosted transcription require network access. |
| `x-bookmarks` | Python 3.11+ and either Bird with browser-cookie access or X API v2 OAuth credentials. Live retrieval requires network access. |

These requirements are also declared in each skill's `compatibility`
frontmatter and explained in its package README.

## Capability handling

A skill may describe an operation that its current host cannot perform. The
agent should use an available equivalent only when it preserves the skill's
safety and evidence requirements. Otherwise it should explain the missing
capability and offer a user-mediated step.

Host-specific tool names and permission grants are intentionally absent from
the portable packages. The host remains responsible for authorization,
sandboxing, confirmations, and credential access.
