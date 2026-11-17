"""Release records and complete host catalogs for the trusted pstack bundle."""

from __future__ import annotations

import base64
import contextlib
import copy
import fcntl
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import tempfile

from plugin_release import (
    GIT_SHA_RE,
    MARKETPLACE_PATH,
    catalog_metadata_errors,
    REPOSITORY_URL,
    parse_calver,
    parse_version,
    release_tag,
    run_git,
    tag_commit,
)

CODEX_MARKETPLACE_PATH = pathlib.PurePosixPath(".agents/plugins/marketplace.json")
PUBLISHED_PATH = pathlib.PurePosixPath("integrations/pstack/published.json")
CATALOG_PATHS = {"claude-code": MARKETPLACE_PATH, "codex": CODEX_MARKETPLACE_PATH}
TRANSACTION_PATHS = frozenset(str(p) for p in (*CATALOG_PATHS.values(), PUBLISHED_PATH))


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def json_at(root: pathlib.Path, revision: str, path: str) -> dict:
    if not revision or revision.startswith("-"):
        raise ValueError(f"invalid revision: {revision!r}")
    result = run_git(root, ["show", f"{revision}:{path}"], check=False)
    if result.returncode:
        raise ValueError(f"cannot read {path} at {revision}")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError(f"{path} at {revision} is not a JSON object")
    return data


def _tree_records(root: pathlib.Path, sha: str, prefix: str) -> list[dict]:
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-rz", sha, "--", prefix],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    entries = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755"} or not path.startswith(prefix + "/"):
            raise ValueError(f"invalid bundle tree entry: {path}")
        entries.append((path[len(prefix) + 1:], mode, oid))
    if not entries:
        raise ValueError(f"empty bundle target: {prefix}")
    answer = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(oid + "\n" for _, _, oid in entries).encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout
    offset = 0
    records = []
    for path, mode, oid in entries:
        end = answer.index(b"\n", offset)
        got_oid, kind, size = answer[offset:end].decode().split()
        if got_oid != oid or kind != "blob":
            raise ValueError("Git returned an unexpected bundle object")
        length = int(size)
        start = end + 1
        data = answer[start:start + length]
        offset = start + length + 1
        records.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                        "mode": mode, "size": length})
    return sorted(records, key=lambda r: r["path"])


def bundle_at(root: pathlib.Path, sha: str) -> dict:
    """Verify committed target identities before any publication or tag exists."""
    if not isinstance(sha, str) or GIT_SHA_RE.fullmatch(sha) is None:
        raise ValueError("release commit must be a full 40-character SHA")
    bundle = json_at(root, sha, "packages/pstack/bundle.json")
    if bundle.get("schema_version") != 1 or bundle.get("name") != "pstack":
        raise ValueError("invalid pstack bundle identity")
    version = bundle.get("version")
    parse_calver(version)
    tag = release_tag("pstack", version)
    upstream = bundle.get("upstream")
    if not isinstance(upstream, dict) or not GIT_SHA_RE.fullmatch(upstream.get("commit", "")):
        raise ValueError("bundle must bind its upstream commit")
    parse_version(upstream.get("version"))
    targets = {}
    for host in CATALOG_PATHS:
        target = bundle.get("targets", {}).get(host)
        if not isinstance(target, dict) or target.get("path") != host:
            raise ValueError(f"invalid {host} target path")
        path = f"packages/pstack/{host}"
        manifest = json_at(root, sha, path + "/plugin.json")
        native_version = manifest.get("version")
        parse_version(native_version)
        if manifest.get("name") != "pstack" or target.get("version") != native_version:
            raise ValueError(f"{host} target manifest identity differs from bundle")
        if native_version != (upstream["version"] if host == "claude-code" else version):
            raise ValueError(f"{host} native version has the wrong owner")
        description = manifest.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{host} manifest has no description")
        records = _tree_records(root, sha, path)
        tree_hash = hashlib.sha256(canonical_bytes(records)).hexdigest()
        if target.get("tree_sha256") != tree_hash:
            raise ValueError(f"{host} committed bytes/modes differ from bundle tree digest")
        target_record = {"path": path, "version": native_version, "description": description,
                         "tree_sha256": tree_hash}
        if host == "codex":
            manifest_records = [r for r in records if r["path"] == "payload-manifest.json"]
            if len(manifest_records) != 1 or target.get("payload_manifest_sha256") != manifest_records[0]["sha256"]:
                raise ValueError("Codex payload manifest checksum differs from bundle")
            target_record["payload_manifest_sha256"] = manifest_records[0]["sha256"]
        targets[host] = target_record
    return {"version": version, "commit": sha, "tag": tag,
            "upstream": upstream,
            "adapter": bundle.get("adapter"), "targets": targets}


def bundle_release_at(root: pathlib.Path, sha: str, archive_sha256: str) -> dict:
    """Require real tag and independently verified archive evidence for promotion."""
    _digest(archive_sha256, "verified archive checksum")
    bundle = bundle_at(root, sha)
    if tag_commit(root, bundle["tag"]) != sha:
        raise ValueError(f"release tag {bundle['tag']} is missing or does not point at {sha}")
    return {**bundle, "archive_sha256": archive_sha256}


def check_native_transition(current: dict | None, proposed: dict) -> None:
    if current is None:
        return
    old = current["targets"]["claude-code"]
    new = proposed["targets"]["claude-code"]
    if parse_version(new["version"]) < parse_version(old["version"]) or (
        new["version"] == old["version"] and new["tree_sha256"] != old["tree_sha256"]
    ):
        raise ValueError("Claude version/cache transition is uncertified; native metadata stays unchanged")


def _regular_path(root: pathlib.Path, relative: pathlib.PurePosixPath, *, missing: bool = False) -> pathlib.Path:
    path = root
    parts = relative.parts
    for index, part in enumerate(parts):
        path = path / part
        if not path.exists() and not path.is_symlink():
            if missing:
                continue
            raise ValueError(f"missing release file: {relative}")
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or (index < len(parts) - 1 and not stat.S_ISDIR(mode)):
            raise ValueError(f"release path must not contain symlinks: {relative}")
        if index == len(parts) - 1 and not stat.S_ISREG(mode):
            raise ValueError(f"release file must be regular: {relative}")
    return path


def read_published(root: pathlib.Path) -> dict | None:
    path = _regular_path(root, PUBLISHED_PATH, missing=True)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("schema_version") != 1 or "release" not in data:
        raise ValueError("invalid pstack published record")
    release = data["release"]
    if release is not None:
        if not isinstance(release, dict):
            raise ValueError("invalid pstack published release")
        parse_calver(release.get("version"))
        if not isinstance(release.get("commit"), str) or not GIT_SHA_RE.fullmatch(release["commit"]):
            raise ValueError("invalid published bundle commit")
        if release.get("tag") != release_tag("pstack", release["version"]):
            raise ValueError("published bundle tag/version mismatch")
        _digest(release.get("archive_sha256"), "published archive checksum")
    return release


def entries_for_release(release: dict | None) -> dict[str, dict]:
    if release is None:
        return {}
    entries = {}
    for host in CATALOG_PATHS:
        target = release.get("targets", {}).get(host)
        if not isinstance(target, dict) or target.get("path") != f"packages/pstack/{host}":
            raise ValueError(f"invalid published {host} target")
        parse_version(target.get("version"))
        _digest(target.get("tree_sha256"), "target tree")
        description = target.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"invalid published {host} description")
        entries[host] = {"name": "pstack", "description": description, "version": target["version"],
                         "source": {"source": "git-subdir", "url": REPOSITORY_URL,
                                    "path": target["path"], "ref": release["tag"],
                                    "sha": release["commit"]}}
    return entries


def expected_pstack_catalog_entries(root: pathlib.Path) -> dict[str, dict]:
    return entries_for_release(read_published(root))


def _read_catalog(root: pathlib.Path, path: pathlib.PurePosixPath) -> dict:
    data = json.loads(_regular_path(root, path).read_text())
    problems = catalog_metadata_errors(data)
    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise ValueError(f"{path} must contain a plugins array")
    names = []
    for entry in data["plugins"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError(f"malformed entry in {path}")
        names.append(entry["name"])
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate plugin entries in {path}")
    return data


def validate_pstack_catalogs(root: pathlib.Path) -> list[str]:
    """Validate publication identity and preservation of all shared native entries."""
    try:
        published = read_published(root)
        expected = entries_for_release(published)
        claude = _read_catalog(root, MARKETPLACE_PATH)
        codex_path = _regular_path(root, CODEX_MARKETPLACE_PATH, missing=True)
        if not codex_path.exists():
            if published:
                raise ValueError("published pstack requires the complete Codex catalog")
            if any(e["name"] == "pstack" for e in claude["plugins"]):
                raise ValueError("unreleased pstack must not appear in a catalog")
            return []
        codex = _read_catalog(root, CODEX_MARKETPLACE_PATH)
        for host, catalog in [("claude-code", claude), ("codex", codex)]:
            actual = next((e for e in catalog["plugins"] if e["name"] == "pstack"), None)
            if actual != expected.get(host):
                raise ValueError(f"{host} pstack entry differs from the published bundle record")
        native = lambda catalog: sorted(  # noqa: E731
            [e for e in catalog["plugins"] if e["name"] != "pstack"], key=lambda e: e["name"]
        )
        if native(claude) != native(codex):
            raise ValueError("Codex catalog must preserve every native Claude catalog entry exactly")
        if published:
            verified = bundle_release_at(root, published["commit"], published["archive_sha256"])
            if verified != published:
                raise ValueError("published pstack record differs from its tagged bundle")
        return []
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        return [str(exc)]


def _git_state_path(root: pathlib.Path, name: str) -> pathlib.Path:
    value = run_git(root, ["rev-parse", "--git-path", name]).stdout.strip()
    path = pathlib.Path(value)
    return path if path.is_absolute() else root / path


def _replace_bytes(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".charms-release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sync_directory(path: pathlib.Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _checkout_identity(root: pathlib.Path) -> dict:
    head = run_git(root, ["rev-parse", "--verify", "HEAD"], check=False)
    return {"root": str(root.resolve()), "head": head.stdout.strip() if head.returncode == 0 else None}


def _content_identity(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _recover(root: pathlib.Path, journal: pathlib.Path) -> None:
    if not journal.exists():
        return
    data = json.loads(journal.read_text())
    if data.get("schema_version") != 2 or not isinstance(data.get("before"), dict):
        raise ValueError("invalid catalog transaction journal; inspect before retrying")
    if data.get("checkout") != _checkout_identity(root):
        raise ValueError("catalog recovery checkout changed; preserve the journal and reconcile explicitly")
    if not isinstance(data.get("identities"), dict) or set(data["identities"]) != set(data["before"]):
        raise ValueError("catalog transaction identities are missing")
    restore = []
    # Preflight every member before restoring any. An operator edit is neither
    # side of our transaction and must never be overwritten by crash recovery.
    for relative, encoded in data["before"].items():
        if relative not in TRANSACTION_PATHS:
            raise ValueError("invalid catalog transaction path")
        path = _regular_path(root, pathlib.PurePosixPath(relative), missing=True)
        original = None if encoded is None else base64.b64decode(encoded, validate=True)
        expected = data["identities"][relative]
        if not isinstance(expected, dict) or set(expected) != {"before", "after"}:
            raise ValueError("invalid catalog transaction identity")
        if expected["before"] != _content_identity(original):
            raise ValueError("catalog journal before-image is corrupt")
        _digest(expected["after"], "catalog after-image")
        current = path.read_bytes() if path.exists() else None
        if _content_identity(current) not in {expected["before"], expected["after"]}:
            raise ValueError("catalog changed outside the interrupted transaction; reconcile before recovery")
        restore.append((path, original))
    for path, original in restore:
        if original is None:
            path.unlink(missing_ok=True)
            if path.parent.exists():
                _sync_directory(path.parent)
        else:
            _replace_bytes(path, original)
    journal.unlink()
    _sync_directory(journal.parent)


@contextlib.contextmanager
def catalog_transaction(root: pathlib.Path):
    """Serialize catalog writers and roll back any interrupted prior local promotion."""
    lock = _git_state_path(root, "charms-catalog.lock")
    journal = _git_state_path(root, "charms-catalog-transaction.json")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        _recover(root, journal)
        yield journal


def write_catalog_transaction(root: pathlib.Path, journal: pathlib.Path, updates: dict) -> bool:
    """Write a Git-commit-sized record/catalog set, restoring all files on failure."""
    before = {}
    contents = {}
    for relative, data in updates.items():
        relative = str(relative)
        if relative not in TRANSACTION_PATHS:
            raise ValueError("unsupported catalog transaction path")
        path = _regular_path(root, pathlib.PurePosixPath(relative), missing=True)
        original = path.read_bytes() if path.exists() else None
        encoded = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
        if original == encoded:
            continue
        before[relative] = None if original is None else base64.b64encode(original).decode()
        contents[relative] = encoded
    if not contents:
        return False
    identities = {
        relative: {"before": _content_identity(None if before[relative] is None else
                                               base64.b64decode(before[relative], validate=True)),
                   "after": _content_identity(content)}
        for relative, content in contents.items()
    }
    _replace_bytes(journal, (json.dumps({"schema_version": 2, "before": before,
                                       "identities": identities,
                                       "checkout": _checkout_identity(root)}) + "\n").encode())
    try:
        for relative, content in contents.items():
            _replace_bytes(root / relative, content)
    except BaseException:
        _recover(root, journal)
        raise
    journal.unlink()
    _sync_directory(journal.parent)
    return True


def promote_bundle(root: pathlib.Path, sha: str, archive_sha256: str) -> tuple[dict, bool]:
    proposed = bundle_release_at(root, sha, archive_sha256)
    entries = entries_for_release(proposed)
    with catalog_transaction(root) as journal:
        current = read_published(root)
        if current != proposed and current is not None:
            if parse_version(proposed["version"]) <= parse_version(current["version"]):
                raise ValueError("refusing to replace a newer or same-version published bundle")
            check_native_transition(current, proposed)
        claude = _read_catalog(root, MARKETPLACE_PATH)
        codex_path = _regular_path(root, CODEX_MARKETPLACE_PATH, missing=True)
        codex = _read_catalog(root, CODEX_MARKETPLACE_PATH) if codex_path.exists() else copy.deepcopy(claude)
        # Both full catalogs are derived from the same canonical set of native entries.
        native = [e for e in claude["plugins"] if e["name"] != "pstack"]
        if codex_path.exists() and sorted(
            [e for e in codex["plugins"] if e["name"] != "pstack"], key=lambda e: e["name"]
        ) != sorted(native, key=lambda e: e["name"]):
            raise ValueError("existing native Codex catalog entries differ; reconcile before promotion")
        for host, catalog in [("claude-code", claude), ("codex", codex)]:
            catalog["plugins"] = sorted(native + [entries[host]], key=lambda e: e["name"])
        changed = write_catalog_transaction(root, journal, {
            MARKETPLACE_PATH: claude, CODEX_MARKETPLACE_PATH: codex,
            PUBLISHED_PATH: {"schema_version": 1, "release": proposed},
        })
        return entries["claude-code"], changed
