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
| `chatgpt-pro-review` | Access to ChatGPT Pro through an approved browser or user-mediated transport. Local file, Git, and test access improve evidence reconciliation. |
| `codex-reset-credit` | Python 3.11+. Live reset-credit checks require local Codex authentication and network access; local rate-limit checks require local Codex session data and can run offline. |
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
