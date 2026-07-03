# Installing Charms for OpenCode

OpenCode can install this repo as a git-backed plugin:

```json
{
  "plugin": ["charms@git+https://github.com/heyNag/charms.git"]
}
```

Restart OpenCode after editing `opencode.json`.

The plugin registers the repo's root `skills/` symlink index. That index points
back to package source folders under `packages/<name>/skills/<name>`, so package
source remains the only editable skill source.

If the plugin path does not work in your OpenCode version, use the direct copy
fallback documented in `docs/installing-skills.md`.
