"""Reproduce the pstack bundle from reviewed immutable upstream inputs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager


REPOSITORY = "https://github.com/cursor/plugins"
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
INPUT_NAMES = ("canonical", "claude", "support")
MANIFEST_NAME = "payload-manifest.json"
TRANSACTION_NAME = ".pstack-sync-transaction"


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def records_digest(records: list[dict]) -> str:
    return sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    )


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError(f"invalid relative path: {value!r}")
    return path


def tree_records(root: Path, *, exclude: frozenset[str] = frozenset()) -> list[dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"expected a real directory: {root}")
    records = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in dirs:
            if (base / name).is_symlink():
                raise ValueError(f"symlink directory is not allowed: {base / name}")
        for name in names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if relative in exclude:
                continue
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"non-regular input is not allowed: {path}")
            data = path.read_bytes()
            records.append(
                {
                    "path": relative,
                    "sha256": sha256(data),
                    "mode": "100755" if mode & 0o111 else "100644",
                    "size": len(data),
                }
            )
    return sorted(records, key=lambda record: record["path"])


def input_records(source: Path, manifest: dict) -> list[dict]:
    base = source if manifest["path"] == "." else source / relative_path(manifest["path"])
    if manifest["path"] != ".":
        records = tree_records(base)
    else:
        records = []
        for expected in manifest["files"]:
            relative = str(relative_path(expected["path"]))
            path = base / relative
            for parent in path.parents:
                if parent == source:
                    break
                if parent.is_symlink():
                    raise ValueError(f"symlink support parent is not allowed: {relative}")
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"missing/non-regular support input: {relative}")
            data = path.read_bytes()
            records.append(
                {
                    "path": relative,
                    "sha256": sha256(data),
                    "mode": "100755" if path.stat().st_mode & 0o111 else "100644",
                    "size": len(data),
                }
            )
        records.sort(key=lambda record: record["path"])
    return records


def without_git_blob(records: list[dict]) -> list[dict]:
    return [{key: record[key] for key in ("path", "sha256", "mode", "size")} for record in records]


def integration_records(
    root: Path, *, check_projection: bool = True
) -> tuple[dict, dict, dict[str, dict]]:
    integration = root / "integrations/pstack"
    lock = read_json(integration / "upstream.lock.json")
    projection = read_json(integration / "projection.json")
    if lock.get("schema_version") != 1 or lock.get("repository") != REPOSITORY:
        raise ValueError("unsupported upstream lock schema/repository")
    if not COMMIT_RE.fullmatch(lock.get("commit", "")):
        raise ValueError("upstream commit must be a complete lowercase Git SHA")
    if not VERSION_RE.fullmatch(lock.get("version", "")):
        raise ValueError("invalid upstream version")
    if (
        lock.get("canonical_path") != "pstack"
        or lock.get("claude_path") != "harness/pstack/claude-code"
    ):
        raise ValueError("canonical and Claude source paths cannot be redirected")
    manifests = {}
    for name in INPUT_NAMES:
        entry = lock["inputs"][name]
        manifest = read_json(integration / relative_path(entry["manifest"]))
        if manifest.get("schema_version") != 1 or manifest.get("commit") != lock["commit"]:
            raise ValueError(f"{name} manifest is not bound to the locked commit")
        if manifest.get("path") != entry["path"]:
            raise ValueError(f"{name} manifest path differs from lock")
        paths = [str(relative_path(row["path"])) for row in manifest["files"]]
        if paths != sorted(set(paths)) or len(paths) != entry["files"]:
            raise ValueError(f"{name} manifest has duplicate, unordered or missing paths")
        if name != "support" and manifest.get("git_tree") != entry["git_tree"]:
            raise ValueError(f"{name} manifest tree differs from lock")
        manifests[name] = manifest
    if check_projection:
        validate_projection(projection, lock)
    return lock, projection, manifests


def validate_projection(projection: dict, lock: dict) -> None:
    if projection.get("schema_version") != 1:
        raise ValueError("unsupported pstack projection schema")
    package = projection.get("package", {})
    if package.get("name") != "pstack" or not VERSION_RE.fullmatch(package.get("version", "")):
        raise ValueError("projection must name pstack and a three-number bundle version")
    if projection.get("reviewed_upstream_commit") != lock["commit"]:
        raise ValueError("projection has not reviewed the selected upstream commit")
    expected = {
        "claude-code": ("claude", "exact-copy"),
        "codex": ("canonical", "canonical-to-codex"),
    }
    if set(projection.get("targets", {})) != set(expected):
        raise ValueError("projection must select exactly Claude Code and Codex")
    for name, (source, transform) in expected.items():
        target = projection["targets"][name]
        if target != {"source": source, "path": name, "transform": transform}:
            raise ValueError(f"unsupported projection target: {name}")


def verify_inputs(source: Path, lock: dict, manifests: dict[str, dict]) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source snapshot must be a real directory")
    for name, manifest in manifests.items():
        have = input_records(source, manifest)
        wanted = without_git_blob(manifest["files"])
        if have != wanted:
            differences = record_diff(wanted, have)
            raise ValueError(
                f"{name} upstream input differs from lock: {json.dumps(differences[:12])}"
            )
        base = source if manifest["path"] == "." else source / manifest["path"]
        for record in manifest["files"]:
            data = (base / record["path"]).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if blob != record["git_blob"]:
                raise ValueError(f"invalid Git identity in {name}: {record['path']}")
    canonical = read_json(source / lock["canonical_path"] / "plugin.json")
    claude = read_json(source / lock["claude_path"] / "plugin.json")
    if canonical.get("version") != lock["version"] or claude.get("version") != lock["version"]:
        raise ValueError("upstream manifest versions do not match the lock")


def record_diff(before: list[dict], after: list[dict]) -> list[dict]:
    old = {record["path"]: record for record in before}
    new = {record["path"]: record for record in after}
    return [
        {
            "path": path,
            "change": "added" if path not in old else "deleted" if path not in new else "modified",
            "before": old.get(path),
            "after": new.get(path),
        }
        for path in sorted(old.keys() | new.keys())
        if old.get(path) != new.get(path)
    ]


def default_cache() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME")
    return (Path(cache) if cache else Path.home() / ".cache") / "charms/pstack"


def cache_path(root: Path, requested: Path | None) -> Path:
    cache = (requested or default_cache()).expanduser().resolve()
    if cache == root or root in cache.parents:
        raise ValueError("pstack source cache must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def git_command(git_dir: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(git_dir), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError(
            "Git input operation failed: " + result.stderr.decode(errors="replace")[:1200]
        )
    return result.stdout


def acquire_git(cache: Path, commit: str, supplied: Path | None, allow_fetch: bool) -> Path:
    if supplied is not None:
        git_dir = supplied.expanduser().resolve()
    else:
        git_dir = cache / "upstream.git"
        if not git_dir.exists():
            if not allow_fetch:
                raise ValueError(
                    "no retained upstream inputs; supply --source/--git-dir or use --fetch"
                )
            subprocess.run(["git", "init", "--bare", str(git_dir)], capture_output=True, check=True)
    present = (
        subprocess.run(
            ["git", "-C", str(git_dir), "cat-file", "-e", commit + "^{commit}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    if not present:
        if supplied is not None or not allow_fetch:
            raise ValueError(f"upstream Git store lacks commit {commit}")
        git_command(
            git_dir,
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "fetch",
            "--no-tags",
            "--depth=1",
            REPOSITORY + ".git",
            commit,
        )
    resolved = git_command(git_dir, "rev-parse", commit + "^{commit}").decode().strip()
    if resolved != commit:
        raise ValueError("Git store did not resolve the exact requested commit")
    return git_dir


def extract_git(git_dir: Path, commit: str, paths: list[str], destination: Path) -> None:
    for path in paths:
        relative_path(path)
    archive = git_command(git_dir, "archive", "--format=tar", commit, "--", *paths)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as handle:
        for member in handle:
            path = relative_path(member.name.rstrip("/"))
            output = destination / path
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                output.parent.mkdir(parents=True, exist_ok=True)
                data = handle.extractfile(member)
                if data is None:
                    raise ValueError(f"missing Git archive member: {path}")
                output.write_bytes(data.read())
                output.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError(f"unsupported Git object type: {path}")


def retain_source(source: Path, cache: Path, lock: dict, manifests: dict[str, dict]) -> Path:
    destination = cache / "sources" / lock["commit"]
    if destination.exists():
        verify_inputs(destination, lock, manifests)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=destination.parent) as temp:
        staged = Path(temp) / "source"
        staged.mkdir()
        for manifest in manifests.values():
            base = Path() if manifest["path"] == "." else Path(manifest["path"])
            for record in manifest["files"]:
                relative = base / record["path"]
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, target)
                target.chmod(0o755 if record["mode"] == "100755" else 0o644)
        verify_inputs(staged, lock, manifests)
        staged.rename(destination)
    return destination


def resolve_source(
    root: Path,
    lock: dict,
    manifests: dict[str, dict],
    *,
    source_root: Path | None,
    git_dir: Path | None,
    cache_dir: Path | None,
    allow_fetch: bool,
) -> Path:
    cache = cache_path(root, cache_dir)
    if source_root is not None:
        source = source_root.expanduser().resolve()
        verify_inputs(source, lock, manifests)
        return retain_source(source, cache, lock, manifests)
    cached = cache / "sources" / lock["commit"]
    if cached.exists():
        verify_inputs(cached, lock, manifests)
        return cached
    git = acquire_git(cache, lock["commit"], git_dir, allow_fetch)
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=cache) as temp:
        source = Path(temp)
        paths = [lock["canonical_path"], lock["claude_path"]]
        paths.extend(record["path"] for record in manifests["support"]["files"])
        extract_git(git, lock["commit"], paths, source)
        verify_inputs(source, lock, manifests)
        return retain_source(source, cache, lock, manifests)


def check_upstream_generator(source: Path, lock: dict, manifests: dict[str, dict]) -> None:
    command = lock.get("generator", {}).get("command")
    expected = ["node", "scripts/generate-pstack-harness-trees.mjs", "--check"]
    if command != expected:
        raise ValueError("unknown upstream generator command requires a reviewed adapter change")
    with tempfile.TemporaryDirectory(prefix="pstack-upstream-check-") as temp:
        disposable = Path(temp) / "source"
        shutil.copytree(source, disposable)
        result = subprocess.run(
            command, cwd=disposable, capture_output=True, text=True, check=False, timeout=120
        )
        if result.returncode:
            raise ValueError(
                "upstream Claude generation check failed: "
                + (result.stdout + result.stderr)[-2400:]
            )
        verify_inputs(disposable, lock, manifests)
    verify_inputs(source, lock, manifests)


def adapter_identity(root: Path, projection: dict, requirements: dict | None = None) -> dict:
    adapter = root / "integrations/pstack/codex"
    records = []
    if adapter.is_dir():
        for record in tree_records(adapter):
            if "__pycache__" in PurePosixPath(record["path"]).parts or record["path"].endswith(
                ".pyc"
            ):
                continue
            records.append({**record, "path": "integrations/pstack/codex/" + record["path"]})
    for relative in (
        "scripts/pstack_sync.py",
        "scripts/pstack_transform.py",
        "integrations/pstack/requirements.json",
    ):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing adapter source: {relative}")
        data = (
            json_bytes(requirements)
            if requirements is not None and relative == "integrations/pstack/requirements.json"
            else path.read_bytes()
        )
        records.append(
            {"path": relative, "sha256": sha256(data), "mode": "100644", "size": len(data)}
        )
    projection_data = json_bytes(projection)
    records.append(
        {
            "path": "integrations/pstack/projection.json",
            "sha256": sha256(projection_data),
            "mode": "100644",
            "size": len(projection_data),
        }
    )
    records.sort(key=lambda row: row["path"])
    return {"sha256": records_digest(records), "inputs": records}


def load_local_module(root: Path, name: str):
    path = root / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def render_bundle(
    root: Path,
    source: Path,
    staged: Path,
    lock: dict,
    projection: dict,
    manifests: dict[str, dict],
    *,
    validation_root: Path | None = None,
    requirements: dict | None = None,
) -> dict:
    version = projection["package"]["version"]
    adapter = adapter_identity(root, projection, requirements)
    context = {
        "upstream_version": lock["version"],
        "upstream_commit": lock["commit"],
        "bundle_version": version,
        "adapter_sha256": adapter["sha256"],
    }
    staged.mkdir()
    shutil.copytree(source / lock["claude_path"], staged / "claude-code")
    (staged / "codex").mkdir()
    transform = load_local_module(root, "pstack_transform")
    metadata = transform.project_codex(
        source, staged / "codex", root / "integrations/pstack/codex", context
    )
    upstream = {
        key: lock[key]
        for key in ("repository", "version", "commit", "canonical_tree", "claude_tree")
    }
    provenance = {
        "schema_version": 1,
        "upstream": upstream,
        "bundle_version": version,
        "adapter": adapter,
        "projection": metadata,
    }
    (staged / "codex/UPSTREAM.json").write_bytes(json_bytes(provenance))
    payload_records = tree_records(staged / "codex", exclude=frozenset({MANIFEST_NAME}))
    payload = {
        "schema_version": 1,
        "upstream": {"version": lock["version"], "commit": lock["commit"]},
        "bundle_version": version,
        "files": payload_records,
        "tree_sha256": records_digest(payload_records),
    }
    (staged / "codex" / MANIFEST_NAME).write_bytes(json_bytes(payload))
    claude_records = tree_records(staged / "claude-code")
    if claude_records != without_git_blob(manifests["claude"]["files"]):
        raise ValueError("generated Claude copy differs from the locked upstream tree")
    bundle = {
        "schema_version": 1,
        "name": "pstack",
        "version": version,
        "upstream": upstream,
        "adapter": {"sha256": adapter["sha256"]},
        "targets": {
            "claude-code": {
                "path": "claude-code",
                "version": lock["version"],
                "tree_sha256": records_digest(claude_records),
            },
            "codex": {
                "path": "codex",
                "version": version,
                "tree_sha256": records_digest(tree_records(staged / "codex")),
                "payload_manifest_sha256": sha256(json_bytes(payload)),
            },
        },
    }
    (staged / "bundle.json").write_bytes(json_bytes(bundle))
    shutil.copyfile(source / lock["canonical_path"] / "LICENSE", staged / "LICENSE")
    (staged / "README.md").write_text(
        f"# pstack for Claude Code and Codex\n\n"
        f"Bundle {version}, based on canonical [pstack {lock['version']}]"
        f"({REPOSITORY}/tree/{lock['commit']}/pstack).\n\n"
        "Select `claude-code/` for Claude Code or `codex/` for Codex. The bundle root "
        "is not a plugin. Desktop, Cloud and CLI use the same Codex root.\n\n"
        "The complete Claude tree is copied unchanged from this upstream commit, "
        "including its native version, dependencies and instructions referring to "
        "`pstack@cursor-plugins`. That upstream channel is separate from a Charms release; "
        "do not enable duplicate pstack installations. Codex is generated directly "
        "from canonical pstack through the maintained adapter.\n\n"
        "Native Cloud original-history access and provider-dependent workflows "
        "are not certified by this adapter implementation. Installation "
        "alone does not establish those capabilities. Read the Codex adapter and "
        "run its capability checks before promising an outcome.\n\n"
        "`bundle.json` records both target identities; `codex/UPSTREAM.json` records "
        "the adapter inputs. Generated files are replaced by `scripts/sync-pstack.py`; "
        "edit maintained integration sources instead. Publication is separate.\n",
        encoding="utf-8",
    )
    verify_inputs(source, lock, manifests)
    # Validation is the trusted repository profile, never a plugin-declared bypass.
    validator = load_local_module(root, "pstack_bundle")
    validator.require_valid_bundle(validation_root or root, staged, projection=projection)
    if adapter_identity(root, projection, requirements) != adapter:
        raise ValueError(
            "adapter inputs changed during generation; regenerate from a stable revision"
        )
    return bundle


@contextmanager
def integration_mutex(root: Path):
    """Serialize local sync/bump operations; the lock contains no user secrets."""
    path = root / ".pstack-sync.lock"
    if (root / TRANSACTION_NAME).exists():
        raise ValueError(
            "interrupted pstack transaction requires --recover before another operation"
        )
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "another pstack sync is active; inspect .pstack-sync.lock before recovery"
        ) from exc
    locked = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("pstack lock is being recovered; retry after recovery") from exc
        locked = True
        if not owns_lock_path(path, fd):
            raise ValueError("pstack lock changed before activation; retry")
        with os.fdopen(fd, "w", closefd=False) as handle:
            handle.write(str(os.getpid()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        if locked and owns_lock_path(path, fd):
            path.unlink()
        os.close(fd)


def owns_lock_path(path: Path, fd: int) -> bool:
    """Do not unlink a replacement lock or a lock whose flock another owner won."""
    try:
        current = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    opened = os.fstat(fd)
    return stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
        opened.st_dev,
        opened.st_ino,
    )


def path_identity(path: Path) -> dict | None:
    if path.is_symlink():
        raise ValueError(f"symlink transaction path is not allowed: {path}")
    if not path.exists():
        return None
    if path.is_dir():
        return {"kind": "directory", "sha256": records_digest(tree_records(path))}
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError(f"non-regular transaction path is not allowed: {path}")
    return {
        "kind": "file",
        "sha256": sha256(path.read_bytes()),
        "mode": "100755" if mode & 0o111 else "100644",
    }


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_tree(path: Path) -> None:
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    for entry in files:
        with entry.open("rb") as handle:
            os.fsync(handle.fileno())
    if path.is_dir():
        for directory, _, _ in os.walk(path, topdown=False):
            fsync_directory(Path(directory))


def durable_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".pending")
    with temporary.open("wb") as handle:
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def recover_transaction(root: Path, *, internal: bool = False) -> dict:
    """Roll an abandoned prepared transaction back, or finish committed cleanup.

    Every affected live path is checked before any recovery mutation. An edit
    after interruption is preserved and requires manual reconciliation.
    """
    root = root.resolve()
    if not internal:
        lock_path = root / ".pstack-sync.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another pstack recovery is active") from exc
            if not owns_lock_path(lock_path, fd):
                raise ValueError("pstack lock changed during recovery; retry")
            text = os.read(fd, 128).decode().strip()
            if text:
                try:
                    pid = int(text)
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                except (ValueError, PermissionError) as exc:
                    raise ValueError(
                        "cannot establish that the pstack operation is abandoned"
                    ) from exc
                else:
                    raise ValueError(
                        "pstack operation is still running; recovery would interrupt it"
                    )
            result = recover_transaction(root, internal=True)
            if not owns_lock_path(lock_path, fd):
                raise ValueError("pstack lock changed during recovery; reconcile before retrying")
            lock_path.unlink()
            fsync_directory(root)
            return result
        finally:
            os.close(fd)
    transaction = root / TRANSACTION_NAME
    if not transaction.exists():
        return {"recovered": False, "state": "no transaction"}
    journal_path = transaction / "journal.json"
    if transaction.is_symlink() or not journal_path.is_file():
        raise ValueError("transaction has no durable journal; inspect retained preparation files")
    journal = read_json(journal_path)
    if journal.get("schema_version") != 1 or journal.get("state") not in ("prepared", "committed"):
        raise ValueError("unsupported transaction recovery journal")
    seen = set()
    operations = []
    for index, entry in enumerate(journal.get("entries", [])):
        relative = str(relative_path(entry["destination"]))
        if relative in seen:
            raise ValueError("duplicate recovery destination")
        seen.add(relative)
        destination = root / relative
        for parent in destination.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("recovery destination parent is a symlink")
        backup = transaction / "old" / str(index)
        current, saved = path_identity(destination), path_identity(backup)
        old, new = entry["before"], entry["after"]
        if journal["state"] == "committed":
            if current != new:
                raise ValueError(f"committed destination changed after interruption: {relative}")
        elif saved is not None:
            if saved != old or current not in (None, new):
                raise ValueError(f"destination changed after interruption: {relative}")
        elif old is not None:
            if current != old:
                raise ValueError(f"missing original recovery data: {relative}")
        elif current not in (None, new):
            raise ValueError(f"new destination changed after interruption: {relative}")
        operations.append((destination, backup, old, saved))
    if journal["state"] == "prepared":
        for destination, backup, old, saved in reversed(operations):
            if saved is not None:
                remove_path(destination)
                os.replace(backup, destination)
                fsync_directory(destination.parent)
                fsync_directory(backup.parent)
            elif old is None:
                remove_path(destination)
                fsync_directory(destination.parent)
    shutil.rmtree(transaction)
    fsync_directory(root)
    return {"recovered": True, "state": journal["state"], "paths": len(operations)}


def replace_transaction(
    root: Path, replacements: list[tuple[Path, Path]], *, expected: dict | None = None
) -> None:
    """Durably stage complete paths, then promote with recoverable rename steps."""
    transaction = root / TRANSACTION_NAME
    if transaction.exists():
        raise ValueError("previous transaction requires recovery")
    for relative, identity in (expected or {}).items():
        if path_identity(root / relative_path(relative)) != identity:
            raise ValueError("active inputs changed before promotion; reprepare or regenerate")
    entries = []
    destinations = set()
    for source, destination in replacements:
        relative = str(relative_path(destination.relative_to(root).as_posix()))
        if relative in destinations:
            raise ValueError("duplicate transaction destination")
        destinations.add(relative)
        after = path_identity(source)
        if after is None:
            raise FileNotFoundError(source)
        before = (
            expected[relative]
            if expected is not None and relative in expected
            else path_identity(destination)
        )
        entries.append({"destination": relative, "before": before, "after": after})
    transaction.mkdir()
    (transaction / "new").mkdir()
    (transaction / "old").mkdir()
    journal = {"schema_version": 1, "state": "prepared", "entries": entries}
    # Persist the recovery map before staging; no active destination is changed yet.
    durable_json(transaction / "journal.json", journal)
    fsync_directory(root)
    try:
        for index, (source, _) in enumerate(replacements):
            staged = transaction / "new" / str(index)
            os.replace(source, staged)
            fsync_tree(staged)
        fsync_directory(transaction / "new")
        for index, (_, destination) in enumerate(replacements):
            entry = entries[index]
            if path_identity(destination) != entry["before"]:
                raise ValueError("active destination changed during transaction preparation")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if entry["before"] is not None:
                os.replace(destination, transaction / "old" / str(index))
                fsync_directory(destination.parent)
                fsync_directory(transaction / "old")
            os.replace(transaction / "new" / str(index), destination)
            fsync_directory(destination.parent)
            fsync_directory(transaction / "new")
        for relative, identity in (expected or {}).items():
            if (
                relative not in destinations
                and path_identity(root / relative_path(relative)) != identity
            ):
                raise ValueError(
                    "active inputs changed during promotion; regenerate after recovery"
                )
        journal["state"] = "committed"
        durable_json(transaction / "journal.json", journal)
    except BaseException:
        recover_transaction(root, internal=True)
        raise
    shutil.rmtree(transaction)
    fsync_directory(root)


def generate(
    root: Path,
    *,
    source_root: Path | None = None,
    git_dir: Path | None = None,
    cache_dir: Path | None = None,
    check: bool = False,
    projection_override: dict | None = None,
    allow_fetch: bool = False,
    expected_projection_sha256: str | None = None,
) -> dict:
    root = root.resolve()
    with integration_mutex(root):
        expected = {**active_update_state(root), **adapter_update_state(root)}
        lock, projection, manifests = integration_records(root)
        if projection_override is not None:
            projection_bytes = (root / "integrations/pstack/projection.json").read_bytes()
            if expected_projection_sha256 != sha256(projection_bytes):
                raise ValueError(
                    "projection override is stale or lacks its expected input identity"
                )
            projection = projection_override
            validate_projection(projection, lock)
        source = resolve_source(
            root,
            lock,
            manifests,
            source_root=source_root,
            git_dir=git_dir,
            cache_dir=cache_dir,
            allow_fetch=allow_fetch,
        )
        check_upstream_generator(source, lock, manifests)
        with tempfile.TemporaryDirectory(prefix=".pstack-stage-", dir=root) as temp:
            stage = Path(temp)
            candidate = stage / "pstack"
            bundle = render_bundle(root, source, candidate, lock, projection, manifests)
            verify_inputs(source, lock, manifests)
            output = root / "packages/pstack"
            previous = tree_records(output) if output.exists() else []
            changes = record_diff(previous, tree_records(candidate))
            result = {
                "upstream_version": lock["version"],
                "upstream_commit": lock["commit"],
                "bundle_version": bundle["version"],
                "changed": bool(changes),
                "changes": changes,
                "source_cache": str(source),
                "targets": bundle["targets"],
            }
            if check:
                if changes:
                    raise ValueError(
                        "generated pstack drift: "
                        + ", ".join(change["path"] for change in changes[:20])
                    )
            elif changes or projection_override is not None:
                replacements = [(candidate, output)]
                if projection_override is not None:
                    proposed = stage / "projection.json"
                    proposed.write_bytes(json_bytes(projection))
                    replacements.append((proposed, root / "integrations/pstack/projection.json"))
                replace_transaction(root, replacements, expected=expected)
            return result


def git_manifest(
    source: Path, git: Path, commit: str, path: str, *, selected_paths: list[str] | None = None
) -> dict:
    command_paths = selected_paths if selected_paths is not None else [path]
    listing = git_command(git, "ls-tree", "-rz", "--full-tree", commit, "--", *command_paths)
    records = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("new upstream input contains an unsupported Git object")
        name = raw_name.decode("utf-8")
        relative_path(name)
        data = (source / name).read_bytes()
        relative = name if path == "." else str(PurePosixPath(name).relative_to(path))
        records.append(
            {
                "path": relative,
                "sha256": sha256(data),
                "mode": mode,
                "size": len(data),
                "git_blob": blob,
            }
        )
    manifest = {
        "schema_version": 1,
        "commit": commit,
        "path": path,
        "files": sorted(records, key=lambda row: row["path"]),
    }
    if path != ".":
        manifest["git_tree"] = git_command(git, "rev-parse", commit + ":" + path).decode().strip()
    return manifest


def active_update_state(root: Path) -> dict:
    paths = [
        "integrations/pstack/upstream.lock.json",
        "integrations/pstack/projection.json",
        "integrations/pstack/requirements.json",
        "integrations/pstack/source-manifests",
        "packages/pstack",
    ]
    return {path: path_identity(root / path) for path in paths}


def adapter_update_state(root: Path) -> dict:
    # Bind the adapter used by this operation, not candidate preparation: an
    # upstream review may intentionally update maintained transformations.
    paths = ["integrations/pstack/codex", "scripts/pstack_sync.py", "scripts/pstack_transform.py"]
    return {path: path_identity(root / path) for path in paths}


def candidate_digest(
    lock: dict, manifests: dict[str, dict], base_commit: str, base_state: dict
) -> str:
    payload = {
        "base_commit": base_commit,
        "base_state": base_state,
        "lock": lock,
        "manifests": manifests,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def update_changes(old: dict[str, dict], new: dict[str, dict]) -> list[dict]:
    return [
        {"input": name, **row}
        for name in INPUT_NAMES
        for row in record_diff(old[name]["files"], new[name]["files"])
    ]


def prepare_update(
    root: Path,
    commit: str,
    candidate_dir: Path,
    *,
    git_dir: Path | None = None,
    cache_dir: Path | None = None,
    allow_fetch: bool = False,
    include_support: list[str] | None = None,
) -> dict:
    """Prepare immutable input/diff evidence. Never advance the active pin."""
    root = root.resolve()
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("prepare-update requires an explicit complete upstream commit SHA")
    destination = candidate_dir.expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ValueError("candidate directory must be outside the repository")
    if destination.exists():
        raise ValueError("candidate destination must not already exist")
    base_state = active_update_state(root)
    old_lock, old_projection, old_manifests = integration_records(root)
    cache = cache_path(root, cache_dir)
    git = acquire_git(cache, commit, git_dir, allow_fetch)
    support_paths = sorted(
        {row["path"] for row in old_manifests["support"]["files"]}
        | {str(relative_path(p)) for p in include_support or []}
    )
    support_listing = git_command(
        git, "ls-tree", "-rz", "--full-tree", commit, "--", *support_paths
    )
    present_support = []
    for entry in support_listing.split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            if metadata.decode().split()[1] != "blob":
                raise ValueError("support additions must name regular upstream files")
            present_support.append(name.decode())
    if not set(present_support) <= set(support_paths):
        raise ValueError("support additions must name individual files, not directory prefixes")
    if not set(include_support or []) <= set(present_support):
        raise ValueError("requested support addition is absent from the candidate commit")
    if old_lock["generator"]["path"] not in present_support:
        raise ValueError("upstream generator was removed; review its replacement contract first")
    wanted = [old_lock["canonical_path"], old_lock["claude_path"], *present_support]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pstack-candidate-", dir=destination.parent) as temp:
        staged = Path(temp) / "candidate"
        source = staged / "source"
        source.mkdir(parents=True)
        extract_git(git, commit, wanted, source)
        manifests = {
            "canonical": git_manifest(source, git, commit, old_lock["canonical_path"]),
            "claude": git_manifest(source, git, commit, old_lock["claude_path"]),
            "support": git_manifest(source, git, commit, ".", selected_paths=present_support),
        }
        version = read_json(source / old_lock["canonical_path"] / "plugin.json").get("version")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ValueError("candidate has an unsupported upstream version")
        lock = json.loads(json.dumps(old_lock))
        lock.update(
            commit=commit,
            version=version,
            canonical_tree=manifests["canonical"]["git_tree"],
            claude_tree=manifests["claude"]["git_tree"],
        )
        for name, manifest in manifests.items():
            lock["inputs"][name]["files"] = len(manifest["files"])
            if "git_tree" in manifest:
                lock["inputs"][name]["git_tree"] = manifest["git_tree"]
        generator = next(
            row for row in manifests["support"]["files"] if row["path"] == lock["generator"]["path"]
        )
        lock["generator"]["git_blob"] = generator["git_blob"]
        verify_inputs(source, lock, manifests)
        integration = staged / "integrations/pstack"
        (integration / "source-manifests").mkdir(parents=True)
        (integration / "upstream.lock.json").write_bytes(json_bytes(lock))
        for name, manifest in manifests.items():
            (integration / f"source-manifests/{name}.json").write_bytes(json_bytes(manifest))
        # Maintainers explicitly rebase these two reviewed records before apply.
        (integration / "projection.json").write_bytes(json_bytes(old_projection))
        shutil.copyfile(
            root / "integrations/pstack/requirements.json", integration / "requirements.json"
        )
        changes = update_changes(old_manifests, manifests)
        if active_update_state(root) != base_state:
            raise ValueError("active inputs changed while preparing the update; prepare again")
        identity = candidate_digest(lock, manifests, old_lock["commit"], base_state)
        report = {
            "schema_version": 1,
            "candidate_sha256": identity,
            "base_commit": old_lock["commit"],
            "upstream_commit": commit,
            "base_state": base_state,
            "old_version": old_lock["version"],
            "new_version": version,
            "changes": changes,
            "consumed_inputs_unchanged": not changes,
            "semantic_review": "Required for changed canonical/support files; hashes do not prove behavior.",
            "upstream_generator_check": "Deferred until the reviewed candidate is applied; prepare does not execute new upstream code.",
            "claude_policy": "Complete exact replacement; no downstream merges or patches.",
            "instructions": "Review every required decision, rebase requirements and projection pins, then apply. No active files have changed.",
        }
        (staged / "report.json").write_bytes(json_bytes(report))
        review = {
            "schema_version": 1,
            "candidate_sha256": identity,
            "decisions": [
                {
                    "input": row["input"],
                    "path": row["path"],
                    "decision": "unreviewed",
                    "requirements": [],
                    "reason": "",
                }
                for row in changes
                if row["input"] != "claude"
            ],
        }
        (staged / "review.json").write_bytes(json_bytes(review))
        staged.rename(destination)
    return {**report, "candidate_dir": str(destination)}


def validate_update_review(
    review: dict,
    identity: str,
    changes: list[dict],
    requirements: dict,
    commit: str,
    canonical: dict,
) -> None:
    if review.get("schema_version") != 1 or review.get("candidate_sha256") != identity:
        raise ValueError("review is not bound to this exact candidate")
    if requirements.get("upstream_commit") != commit:
        raise ValueError("requirements ledger must be rebased to the candidate commit")
    rows = requirements.get("requirements", [])
    ids = {row.get("id") for row in rows if isinstance(row, dict)}
    if not rows or None in ids or len(ids) != len(rows):
        raise ValueError("candidate requirement identities must be nonempty and unique")
    cited = {path for row in rows for path in row.get("source_paths", [])}
    for record in canonical["files"]:
        path = canonical["path"] + "/" + record["path"]
        if not any(
            path == citation.rstrip("/") or path.startswith(citation.rstrip("/") + "/")
            for citation in cited
        ):
            raise ValueError(f"candidate source has no reviewed requirement mapping: {path}")
    expected = {(row["input"], row["path"]) for row in changes if row["input"] != "claude"}
    seen = set()
    for decision in review.get("decisions", []):
        key = (decision.get("input"), decision.get("path"))
        if key in seen or key not in expected:
            raise ValueError("update review contains duplicate or unrelated decisions")
        seen.add(key)
        if decision.get("decision") != "accept" or not decision.get("reason", "").strip():
            raise ValueError(f"upstream change still requires semantic review: {key}")
        linked = decision.get("requirements")
        if not isinstance(linked, list) or not linked or not set(linked) <= ids:
            raise ValueError(f"review must link actual candidate requirements: {key}")
    if seen != expected:
        raise ValueError("update review does not classify every changed canonical/support path")


def apply_candidate(root: Path, candidate_dir: Path, *, cache_dir: Path | None = None) -> dict:
    root = root.resolve()
    candidate = candidate_dir.expanduser().resolve()
    with integration_mutex(root):
        base_state = active_update_state(root)
        promotion_state = {**base_state, **adapter_update_state(root)}
        previous, _, old_manifests = integration_records(root)
        lock, projection, manifests = integration_records(candidate, check_projection=False)
        report = read_json(candidate / "report.json")
        if report.get("base_commit") != previous["commit"]:
            raise ValueError("candidate base is stale; prepare against the active lock again")
        if report.get("base_state") != base_state:
            raise ValueError(
                "candidate base metadata/output is stale; reprepare and rebase the review"
            )
        identity = candidate_digest(lock, manifests, previous["commit"], base_state)
        if report.get("candidate_sha256") != identity:
            raise ValueError("candidate inputs changed after preparation; prepare it again")
        changes = update_changes(old_manifests, manifests)
        if report.get("changes") != changes:
            raise ValueError("candidate change report differs from its exact inputs")
        if not changes:
            return {
                "upstream_version": previous["version"],
                "upstream_commit": previous["commit"],
                "observed_upstream_commit": lock["commit"],
                "bundle_version": read_json(root / "integrations/pstack/projection.json")[
                    "package"
                ]["version"],
                "changed": False,
                "changes": [],
                "candidate_sha256": identity,
            }
        validate_projection(projection, lock)
        requirements = read_json(candidate / "integrations/pstack/requirements.json")
        review = read_json(candidate / "review.json")
        validate_update_review(
            review,
            identity,
            changes,
            requirements,
            lock["commit"],
            manifests["canonical"],
        )
        # Retain the validated values, rather than rereading external candidate
        # files after the potentially slow generator and adapter checks.
        reviewed_metadata = {
            "report.json": report,
            "review.json": review,
            "integrations/pstack/upstream.lock.json": lock,
            "integrations/pstack/projection.json": projection,
            "integrations/pstack/requirements.json": requirements,
            **{
                f"integrations/pstack/source-manifests/{name}.json": value
                for name, value in manifests.items()
            },
        }

        def check_candidate_metadata():
            if any(
                read_json(candidate / path) != value for path, value in reviewed_metadata.items()
            ):
                raise ValueError("candidate metadata changed during apply; review it again")

        check_candidate_metadata()
        verify_inputs(candidate / "source", lock, manifests)
        source = retain_source(candidate / "source", cache_path(root, cache_dir), lock, manifests)
        check_upstream_generator(source, lock, manifests)
        with tempfile.TemporaryDirectory(prefix=".pstack-stage-", dir=root) as temp:
            stage = Path(temp)
            output = stage / "pstack"
            replacements = [(output, root / "packages/pstack")]
            validation_root = stage / "reviewed"
            for path, value in reviewed_metadata.items():
                frozen = validation_root / path
                frozen.parent.mkdir(parents=True, exist_ok=True)
                frozen.write_bytes(json_bytes(value))
            for name in ("upstream.lock.json", "projection.json", "requirements.json"):
                proposed = validation_root / "integrations/pstack" / name
                replacements.append((proposed, root / "integrations/pstack" / name))
            replacements.append(
                (
                    validation_root / "integrations/pstack/source-manifests",
                    root / "integrations/pstack/source-manifests",
                )
            )
            # Keep the accepted evidence with the projection instead of inventing a sync database.
            projection = {
                **projection,
                "upstream_review": {
                    "base_commit": previous["commit"],
                    "candidate_sha256": identity,
                    "decisions": review["decisions"],
                },
            }
            # The accepted projection is part of generated provenance.
            bundle = render_bundle(
                root,
                source,
                output,
                lock,
                projection,
                manifests,
                validation_root=validation_root,
                requirements=requirements,
            )
            verify_inputs(source, lock, manifests)
            (validation_root / "integrations/pstack/projection.json").write_bytes(
                json_bytes(projection)
            )
            check_candidate_metadata()
            replace_transaction(root, replacements, expected=promotion_state)
        return {
            "upstream_version": lock["version"],
            "upstream_commit": lock["commit"],
            "bundle_version": bundle["version"],
            "changed": True,
            "changes": changes,
            "candidate_sha256": identity,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS
    )
    parser.add_argument("--source", type=Path, help="Existing immutable upstream snapshot")
    parser.add_argument("--git-dir", type=Path, help="Existing Git object store (read only)")
    parser.add_argument("--cache-dir", type=Path, help="Retained inputs outside the repository")
    parser.add_argument(
        "--fetch", action="store_true", help="Fetch the exact lock commit if absent"
    )
    parser.add_argument(
        "--check", action="store_true", help="Compare deterministic output without replacing it"
    )
    parser.add_argument("--report", type=Path, help="Write the complete source/output diff report")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--prepare-update",
        metavar="COMMIT",
        help="Prepare a reviewed update candidate; active files stay unchanged",
    )
    operation.add_argument(
        "--apply-candidate",
        type=Path,
        help="Apply a fully reviewed candidate with rollback on failure",
    )
    operation.add_argument(
        "--recover",
        action="store_true",
        help="Recover an abandoned local promotion after checking original identities",
    )
    parser.add_argument(
        "--candidate-dir", type=Path, help="New external output directory for --prepare-update"
    )
    parser.add_argument(
        "--include-support",
        action="append",
        default=[],
        metavar="PATH",
        help="Include a new upstream dependency file in a prepared update's reviewed input closure",
    )
    args = parser.parse_args(argv)
    try:
        if args.recover:
            if (
                args.source
                or args.git_dir
                or args.check
                or args.fetch
                or args.candidate_dir
                or args.include_support
            ):
                raise ValueError("recover cannot be combined with source/generation options")
            result = recover_transaction(args.root)
        elif args.prepare_update:
            if args.candidate_dir is None or args.source or args.check:
                raise ValueError(
                    "prepare-update needs --candidate-dir and cannot use --source/--check"
                )
            result = prepare_update(
                args.root,
                args.prepare_update,
                args.candidate_dir,
                git_dir=args.git_dir,
                cache_dir=args.cache_dir,
                allow_fetch=args.fetch,
                include_support=args.include_support,
            )
        elif args.apply_candidate:
            if (
                args.source
                or args.git_dir
                or args.check
                or args.fetch
                or args.candidate_dir
                or args.include_support
            ):
                raise ValueError("apply-candidate accepts only --cache-dir/--report")
            result = apply_candidate(args.root, args.apply_candidate, cache_dir=args.cache_dir)
        else:
            if args.candidate_dir or args.include_support:
                raise ValueError("candidate-dir/include-support requires --prepare-update")
            result = generate(
                args.root,
                source_root=args.source,
                git_dir=args.git_dir,
                cache_dir=args.cache_dir,
                check=args.check,
                allow_fetch=args.fetch,
            )
        if args.report:
            args.report.write_bytes(json_bytes(result))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "upstream_version",
                    "upstream_commit",
                    "bundle_version",
                    "changed",
                    "candidate_dir",
                    "old_version",
                    "new_version",
                    "consumed_inputs_unchanged",
                    "recovered",
                    "state",
                    "paths",
                )
                if key in result
            },
            indent=2,
        )
    )
    return 0
