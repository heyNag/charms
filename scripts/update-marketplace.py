#!/usr/bin/env python3
"""Point one marketplace entry at a published, tagged plugin release.

The entry's version and description come from the plugin manifest at the
release commit, and its source pins both the release tag and the full commit
SHA. An entry may only move to a newer version; re-running for the release it
already names is a no-op.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from plugin_release import (  # noqa: E402
    GIT_SHA_RE,
    MARKETPLACE_PATH,
    manifest_at,
    marketplace_entry,
    parse_version,
    release_tag,
    tag_commit,
    validate_plugin_name,
)


def load_marketplace(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise ValueError(f"{path} must be a JSON object with a plugins array")
    return data


def update_marketplace(
    root: pathlib.Path, plugin: str, sha: str, *, archive_sha256: str | None = None
) -> tuple[dict, bool]:
    """Return the new entry and whether the marketplace file changed."""

    validate_plugin_name(plugin)
    if plugin == "pstack":
        from pstack_release import promote_bundle

        if archive_sha256 is None:
            raise ValueError("pstack promotion requires the verified archive SHA-256")
        return promote_bundle(root, sha, archive_sha256)
    if GIT_SHA_RE.fullmatch(sha) is None:
        raise ValueError(f"release commit must be a full 40-character SHA: {sha!r}")
    manifest = manifest_at(root, sha, plugin)
    if manifest.get("name") != plugin:
        raise ValueError(f"packages/{plugin}/plugin.json at {sha} is not {plugin!r}")
    version = manifest.get("version")
    parse_version(version)
    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"packages/{plugin}/plugin.json at {sha} has no description")

    tag = release_tag(plugin, version)
    if tag_commit(root, tag) != sha:
        raise ValueError(f"release tag {tag} is missing or does not point at {sha}")
    entry = marketplace_entry(plugin, version, description, sha)

    from pstack_release import (
        CODEX_MARKETPLACE_PATH,
        _read_catalog,
        _regular_path,
        catalog_transaction,
        expected_pstack_catalog_entries,
        write_catalog_transaction,
    )

    with catalog_transaction(root) as journal:
        marketplace = _read_catalog(root, MARKETPLACE_PATH)
        plugins = marketplace["plugins"]
        current = next((item for item in plugins if item.get("name") == plugin), None)
        if current is not None and current != entry:
            current_version = current.get("version")
            if parse_version(version) <= parse_version(current_version):
                raise ValueError(
                    f"marketplace already lists {plugin} {current_version}; "
                    f"refusing to move it to {version}"
                )
        codex_path = _regular_path(root, CODEX_MARKETPLACE_PATH, missing=True)
        codex = _read_catalog(root, CODEX_MARKETPLACE_PATH) if codex_path.exists() else None
        if codex is not None:
            original_native = sorted(
                [item for item in plugins if item["name"] != "pstack"], key=lambda item: item["name"]
            )
            other_native = sorted(
                [item for item in codex["plugins"] if item["name"] != "pstack"],
                key=lambda item: item["name"],
            )
            if original_native != other_native:
                raise ValueError("existing native catalogs differ; reconcile before release update")
            expected = expected_pstack_catalog_entries(root)
            for host, catalog in [("claude-code", marketplace), ("codex", codex)]:
                actual = next((item for item in catalog["plugins"] if item["name"] == "pstack"), None)
                if actual != expected.get(host):
                    raise ValueError("pstack catalog entry differs from its published record")
        marketplace["plugins"] = sorted(
            [item for item in plugins if item.get("name") != plugin] + [entry],
            key=lambda item: item["name"],
        )
        updates = {MARKETPLACE_PATH: marketplace}
        if codex is not None:
            codex["plugins"] = sorted(
                [item for item in marketplace["plugins"] if item["name"] != "pstack"]
                + [item for item in codex["plugins"] if item["name"] == "pstack"],
                key=lambda item: item["name"],
            )
            updates[CODEX_MARKETPLACE_PATH] = codex
        return entry, write_catalog_transaction(root, journal, updates)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", help="Plugin package name under packages/")
    parser.add_argument("--sha", required=True, help="Full SHA of the tagged release commit.")
    parser.add_argument(
        "--archive-sha256",
        help="Verified immutable archive digest; required for pstack bundle promotion.",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    try:
        entry, changed = update_marketplace(
            args.root.resolve(), args.plugin, args.sha, archive_sha256=args.archive_sha256
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state = "updated" if changed else "unchanged"
    print(f"{state}: {entry['name']} {entry['version']} -> {entry['source']['sha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
