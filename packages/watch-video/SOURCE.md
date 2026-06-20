# Source Package

This directory is the source of truth for `watch-video`.

Edit files here first:

- `SKILL.md`
- `README.md`
- `commands/`
- `plugin/plugin.json`
- `scripts/`
- `tests/`
- `tool.json`

After changing package source, run:

```sh
make build-packages
make verify-generated-clean
```

The public install copies under `plugins/watch-video` and `codex/watch-video`
are generated from this directory.

Generated Markdown and Python files include in-file notices that point back to
the source paths in this package. Generated JSON and LICENSE files are covered
by the nearest `GENERATED.md` marker because those file formats should not carry
extra comments.
