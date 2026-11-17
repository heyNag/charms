"""Verify a selected Codex root without modifying the installed payload."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import re


class RuntimeErrorBase(ValueError):
    """An unavailable or invalid runtime contract, suitable for a concise CLI error."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeErrorBase("duplicate JSON key")
        result[key] = value
    return result


def load_json(path: Path) -> object:
    regular(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorBase("invalid JSON document") from exc


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeErrorBase(f"expected a regular file: {path.name}")


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeErrorBase("invalid relative resource path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {"", ".", ".."} for x in value.split("/")):
        raise RuntimeErrorBase("resource path escapes its root")
    if any(ord(c) < 32 for c in value):
        raise RuntimeErrorBase("control character in resource path")
    return value


def contained(root: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    path = root.joinpath(*relative.split("/"))
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise RuntimeErrorBase("symlink in resource path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeErrorBase("resource path escapes its root")
    return path


def file_record(root: Path, path: Path) -> dict:
    regular(path)
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest(data),
        "mode": "100755" if path.stat().st_mode & 0o111 else "100644",
        "size": len(data),
    }


def tree_records(root: Path, *, exclude_manifest: bool = True) -> list[dict]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeErrorBase("runtime root must be a real directory")
    result = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        here = Path(directory)
        for name in dirs:
            if (here / name).is_symlink():
                raise RuntimeErrorBase("symlink directory in runtime")
        for name in names:
            p = here / name
            if exclude_manifest and p == root / "payload-manifest.json":
                continue
            result.append(file_record(root, p))
    return sorted(result, key=lambda item: item["path"])


def verify_payload(
    root: Path,
    *,
    expected_manifest: str | None = None,
    expected_upstream: str | None = None,
    expected_version: str | None = None,
) -> dict:
    if root.is_symlink():
        raise RuntimeErrorBase("runtime root cannot be a symlink")
    root = root.resolve(strict=True)
    manifest_path = contained(root, "payload-manifest.json")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeErrorBase("unsupported payload manifest schema")
    manifest_hash = digest(manifest_path.read_bytes())
    if expected_manifest is not None:
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_manifest)
            or manifest_hash != expected_manifest
        ):
            raise RuntimeErrorBase("payload manifest does not match the external installation pin")
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict) or not re.fullmatch(
        r"[0-9a-f]{40}", str(upstream.get("commit", ""))
    ):
        raise RuntimeErrorBase("missing upstream identity")
    if expected_upstream is not None and upstream["commit"] != expected_upstream:
        raise RuntimeErrorBase("wrong upstream commit")
    if expected_version is not None and manifest.get("bundle_version") != expected_version:
        raise RuntimeErrorBase("wrong bundle version")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise RuntimeErrorBase("empty payload inventory")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "mode", "size"}:
            raise RuntimeErrorBase("invalid payload file record")
        path = safe_relative(record["path"])
        if path == "payload-manifest.json" or path in seen:
            raise RuntimeErrorBase("duplicate or circular payload record")
        seen.add(path)
        if record["mode"] not in {"100644", "100755"}:
            raise RuntimeErrorBase("unsupported payload mode")
        if not isinstance(record["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["sha256"]
        ):
            raise RuntimeErrorBase("invalid payload content hash")
        if type(record["size"]) is not int or record["size"] < 0:
            raise RuntimeErrorBase("invalid payload size")
    if records != sorted(records, key=lambda item: item["path"]):
        raise RuntimeErrorBase("payload inventory is not in canonical path order")
    if digest(canonical(records)) != manifest.get("tree_sha256"):
        raise RuntimeErrorBase("payload inventory tree hash mismatch")
    actual = tree_records(root)
    if actual != records:
        expected_map = {r["path"]: r for r in records}
        actual_map = {r["path"]: r for r in actual}
        changed = sorted(
            k
            for k in expected_map.keys() | actual_map.keys()
            if expected_map.get(k) != actual_map.get(k)
        )
        raise RuntimeErrorBase("payload content/path/mode mismatch: " + ", ".join(changed[:8]))
    return {
        "status": "integrity_verified",
        "root": str(root),
        "manifest_sha256": manifest_hash,
        "tree_sha256": manifest["tree_sha256"],
        "upstream": upstream,
        "bundle_version": manifest.get("bundle_version"),
        "files": len(records),
        "origin_verified": expected_manifest is not None,
        "trust": "externally_pinned" if expected_manifest else "installed_root_consistency_only",
    }


def resolve_locator(path: Path, *, surface: str, supplied_root: Path | None = None) -> dict:
    value = load_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeErrorBase("unsupported runtime locator")
    if value.get("surface") not in {surface, "all"}:
        raise RuntimeErrorBase("runtime locator belongs to another surface")
    root_text = value.get("runtime_root")
    if not isinstance(root_text, str) or not Path(root_text).is_absolute():
        raise RuntimeErrorBase("runtime locator needs an absolute root")
    root = Path(root_text)
    if supplied_root is not None and supplied_root.resolve() != root.resolve():
        raise RuntimeErrorBase("runtime locator/root mismatch")
    pin = value.get("manifest_sha256")
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise RuntimeErrorBase("runtime locator lacks the external payload pin")
    if path.resolve().is_relative_to(root.resolve()):
        raise RuntimeErrorBase("installation locator must be outside the immutable runtime")
    return {"root": root, "expected_manifest": pin}


def resolve_skill(
    root: Path, skill: str, *, overrides: Path | None = None, verified: dict | None = None
) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill):
        raise RuntimeErrorBase("invalid skill identity")
    verified = verified or verify_payload(root)
    if Path(verified["root"]).resolve() != root.resolve():
        raise RuntimeErrorBase("verification belongs to another root")
    descriptor = contained(root, f"skills/{skill}/SKILL.md")
    body = contained(root, f"skills/{skill}/instructions.md")
    regular(descriptor)
    regular(body)
    original_hash = digest(body.read_bytes())
    selected = body
    applied = None
    if overrides is not None:
        if overrides.resolve().is_relative_to(root.resolve()):
            raise RuntimeErrorBase("overrides must live outside the immutable plugin cache")
        registry = load_json(overrides)
        if not isinstance(registry, dict) or registry.get("schema_version") != 1:
            raise RuntimeErrorBase("unsupported override registry")
        if registry.get("payload_sha256") != verified["manifest_sha256"]:
            raise RuntimeErrorBase("override registry targets a different payload")
        entries = registry.get("skills")
        if not isinstance(entries, dict):
            raise RuntimeErrorBase("invalid override skill map")
        entry = entries.get(skill)
        if entry is not None:
            if not isinstance(entry, dict) or entry.get("base_sha256") != original_hash:
                raise RuntimeErrorBase("stale override base; reconcile the approved edit")
            if not isinstance(entry.get("approval_id"), str) or not entry["approval_id"].strip():
                raise RuntimeErrorBase("override has no recorded approval reference")
            selected = contained(overrides.parent.resolve(), entry.get("body_path"))
            regular(selected)
            if selected.resolve().is_relative_to(root.resolve()):
                raise RuntimeErrorBase("override cannot edit or redirect into the plugin cache")
            if digest(selected.read_bytes()) != entry.get("body_sha256"):
                raise RuntimeErrorBase("approved override content changed")
            applied = entry["approval_id"]
    return {
        "skill": skill,
        "descriptor": str(descriptor),
        "instructions": str(selected),
        "payload_root": str(root.resolve()),
        "resource_root": str(body.parent.resolve()),
        "resource_policy": "Resolve relative helpers from resource_root and skill bodies through the same registry, never from a relocated override directory.",
        "instructions_sha256": digest(selected.read_bytes()),
        "base_sha256": original_hash,
        "override_approval_id": applied,
        "payload_sha256": verified["manifest_sha256"],
        "metadata_activation": "host reactivation required for descriptor/description changes",
    }


def resolve_resource(
    root: Path,
    skill: str,
    reference: str,
    *,
    overrides: Path | None = None,
    verified: dict | None = None,
) -> dict:
    """Resolve source-relative references while keeping approved body selection active."""
    verified = verified or verify_payload(root)
    binding = resolve_skill(root, skill, overrides=overrides, verified=verified)
    if not isinstance(reference, str) or not reference or "\\" in reference or ":" in reference:
        raise RuntimeErrorBase("resource reference must be a relative package path")
    if any(ord(character) < 32 for character in reference):
        raise RuntimeErrorBase("control character in resource reference")
    target, _, fragment = reference.partition("#")
    if target.startswith("/"):
        raise RuntimeErrorBase("absolute resource reference is not permitted")
    relative = posixpath.normpath(posixpath.join("skills", skill, target or "instructions.md"))
    path = contained(root, relative)
    regular(path)
    parts = PurePosixPath(relative).parts
    if len(parts) == 3 and parts[0] == "skills" and parts[2] in {"SKILL.md", "instructions.md"}:
        selected = resolve_skill(root, parts[1], overrides=overrides, verified=verified)
        return {
            **selected,
            "reference": reference,
            "fragment": fragment,
            "path": selected["instructions"],
            "kind": "effective_skill",
        }
    return {
        "path": str(path.resolve()),
        "sha256": digest(path.read_bytes()),
        "reference": reference,
        "fragment": fragment,
        "kind": "immutable_resource",
        "resource_root": binding["resource_root"],
        "payload_sha256": verified["manifest_sha256"],
    }


def require_external_destination(path: Path) -> None:
    """Configuration writes never belong inside any installed plugin payload."""
    if path.is_symlink():
        raise RuntimeErrorBase("configuration destination cannot be a symlink")
    for ancestor in path.resolve().parents:
        markers = [
            ancestor / "payload-manifest.json",
            ancestor / "plugin.json",
            ancestor / ".codex-plugin/plugin.json",
            ancestor / ".claude-plugin/plugin.json",
        ]
        if any(marker.exists() or marker.is_symlink() for marker in markers):
            raise RuntimeErrorBase(
                "configuration must be outside installed plugin payloads and caches"
            )
