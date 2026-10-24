# Charms documentation

Use the shortest guide that matches the task:

| Task | Guide |
| --- | --- |
| Understand repository and product boundaries | [Architecture](architecture.md) |
| Understand the exact portable package contract | [Plugin format](plugin-format.md) |
| Install or update a plugin in Claude Code, Codex, or another host | [Installation](installing.md) |
| Check supported clients and runtime requirements | [Compatibility](compatibility.md) |
| Change or add a plugin | [Development](development.md) |
| Review trust, credentials, and artifact safety | [Security](security.md) |
| Bump a version, publish a release, or configure release settings | [Releasing](releasing.md) |

Behavior and operational details live with each plugin:

- [watch-video](../packages/watch-video/README.md)
- [x-bookmarks](../packages/x-bookmarks/README.md)

The normative external references are the
[Agent Plugins v1 specification](https://agent-plugins.org/specification), its
[plugin manifest schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json),
and the [Agent Skills specification](https://agentskills.io/specification).
