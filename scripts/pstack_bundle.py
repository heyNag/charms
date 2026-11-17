"""Repository-owned validation for the pstack two-target release container.

The exception is selected by this module and its integration lock, never by a
field supplied in an arbitrary plugin manifest. Source fixture exceptions are
limited to exact pinned files; secrets and unsafe filesystem entries still fail.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata

from plugin_release import parse_version


BUNDLE_NAME = "pstack"
INTEGRATION_PATH = Path("integrations/pstack")
BUNDLE_PATH = Path("packages/pstack")
HOSTS = ("claude-code", "codex")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_object(path: Path) -> dict:
    _regular_file(path)
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def _regular_file(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"{path}: must be a regular file, not a symlink or special file")


def _directory(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"{path}: must be a real directory, not a symlink")


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid relative resource path: {value!r}")
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"invalid relative resource path: {value!r}")
    if any(unicodedata.category(c) in {"Cc", "Cf"} for c in value):
        raise ValueError(f"control character in resource path: {value!r}")
    return value


def _sha(value: object, pattern: re.Pattern, label: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label}: invalid digest")


def file_record(path: Path, relative: str) -> dict:
    _regular_file(path)
    content = path.read_bytes()
    return {
        "path": safe_relative(relative),
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": "100755" if path.stat().st_mode & 0o111 else "100644",
        "size": len(content),
    }


def tree_records(directory: Path, *, exclude: frozenset[str] = frozenset()) -> list[dict]:
    _directory(directory)
    records = []
    names = set()
    for current, dirs, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        for name in sorted(dirs):
            _directory(current_path / name)
        for name in sorted(files):
            path = current_path / name
            relative = safe_relative(path.relative_to(directory).as_posix())
            _regular_file(path)
            normalized = unicodedata.normalize("NFC", relative).casefold()
            if normalized in names:
                raise ValueError(f"portable path collision: {relative}")
            names.add(normalized)
            if relative not in exclude:
                records.append(file_record(path, relative))
    return sorted(records, key=lambda row: row["path"])


def tree_digest(records: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def manifest_records(data: dict, label: str) -> list[dict]:
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{label}: files must be a nonempty list")
    seen = set()
    rows = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(f"{label}: file record must be an object")
        path = safe_relative(entry.get("path"))
        if path in seen:
            raise ValueError(f"{label}: duplicate source path {path}")
        seen.add(path)
        _sha(entry.get("sha256"), HEX64, f"{label}/{path}")
        if entry.get("mode") not in {"100644", "100755"}:
            raise ValueError(f"{label}/{path}: unsupported Git mode")
        if type(entry.get("size")) is not int or entry["size"] < 0:
            raise ValueError(f"{label}/{path}: invalid file size")
        rows.append({key: entry[key] for key in ("path", "sha256", "mode", "size")})
    return sorted(rows, key=lambda row: row["path"])


def _source_manifest(root: Path, name: str, lock: dict) -> dict:
    info = lock.get("inputs", {}).get(name)
    if not isinstance(info, dict):
        raise ValueError(f"upstream lock: missing {name} input")
    relative = safe_relative(info.get("manifest"))
    if relative != f"source-manifests/{name}.json":
        raise ValueError(f"upstream lock: unexpected {name} manifest path")
    data = read_object(root / INTEGRATION_PATH / relative)
    if data.get("schema_version") != 1 or data.get("commit") != lock.get("commit"):
        raise ValueError(f"{name} source manifest: mismatched schema or upstream commit")
    expected_path = lock.get(f"{name}_path")
    expected_tree = lock.get(f"{name}_tree")
    if data.get("path") != expected_path or data.get("git_tree") != expected_tree:
        raise ValueError(f"{name} source manifest: mismatched source path/tree")
    _sha(expected_tree, HEX40, f"{name} Git tree")
    rows = manifest_records(data, name)
    if info.get("files") != len(rows) or info.get("git_tree") != expected_tree:
        raise ValueError(f"{name} source manifest: input count/tree disagrees with lock")
    return data


def trusted_integration(root: Path) -> tuple[dict, dict, dict]:
    """Read only the one repository-owned integration profile."""
    _directory(root / "integrations")
    _directory(root / INTEGRATION_PATH)
    _directory(root / INTEGRATION_PATH / "source-manifests")
    lock = read_object(root / INTEGRATION_PATH / "upstream.lock.json")
    if (
        lock.get("schema_version") != 1
        or lock.get("repository") != "https://github.com/cursor/plugins"
    ):
        raise ValueError("pstack requires the repository-owned cursor/plugins upstream lock")
    _sha(lock.get("commit"), HEX40, "upstream commit")
    parse_version(lock.get("version"))
    if (
        lock.get("canonical_path") != "pstack"
        or lock.get("claude_path") != "harness/pstack/claude-code"
    ):
        raise ValueError("pstack upstream source paths may not be redirected")
    return lock, _source_manifest(root, "canonical", lock), _source_manifest(root, "claude", lock)


def git_tree_digest(directory: Path) -> str:
    """Compute the Git tree identity without a checkout, index or Git writes."""

    def object_hash(kind: bytes, data: bytes) -> bytes:
        return hashlib.sha1(kind + b" " + str(len(data)).encode() + b"\0" + data).digest()

    def visit(path: Path) -> bytes:
        _directory(path)
        entries = []
        for child in path.iterdir():
            if child.is_symlink():
                raise ValueError(f"{child}: symlinks are forbidden")
            if child.is_dir():
                mode, digest, order = "40000", visit(child), child.name + "/"
            else:
                _regular_file(child)
                mode = "100755" if child.stat().st_mode & 0o111 else "100644"
                digest, order = object_hash(b"blob", child.read_bytes()), child.name
            entries.append(
                (order.encode(), mode.encode() + b" " + child.name.encode() + b"\0" + digest)
            )
        return object_hash(b"tree", b"".join(data for _, data in sorted(entries)))

    return visit(directory).hex()


def _scan_artifacts(package: Path, canonical: dict, claude: dict) -> None:
    # Import only the central policy constants; importing this module does not
    # run validation or require the optional schema/skills dependencies.
    from validate_plugins import (
        FORBIDDEN_DIRECTORY_NAMES,
        SECRET_RE,
        _is_forbidden_file_name,
    )

    source_rows = {
        "claude-code": {r["path"]: r for r in claude["files"]},
        "codex": {r["path"]: r for r in canonical["files"]},
    }
    for current, directories, files in os.walk(package, followlinks=False):
        for name in directories:
            if name in FORBIDDEN_DIRECTORY_NAMES:
                raise ValueError(f"{Path(current) / name}: forbidden local artifact directory")
        for name in files:
            path = Path(current) / name
            _regular_file(path)
            relative = path.relative_to(package)
            allowed_fixture = False
            if len(relative.parts) > 1 and relative.parts[0] in HOSTS:
                resource = "/".join(relative.parts[1:])
                if re.fullmatch(
                    r"skills/statechart/scripts/test/corpus/[^/]+/report\.md", resource
                ):
                    expected = source_rows[relative.parts[0]].get(resource)
                    allowed_fixture = expected is not None and file_record(path, resource) == {
                        key: expected[key] for key in ("path", "sha256", "mode", "size")
                    }
            if _is_forbidden_file_name(name) and not allowed_fixture:
                raise ValueError(f"{relative}: forbidden local artifact file")
            content = path.read_bytes()
            if SECRET_RE.search(content) or re.search(
                rb"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----", content
            ):
                raise ValueError(f"{relative}: possible secret value found")


def _equal_records(actual: list[dict], expected: list[dict], label: str) -> None:
    actual_by_path = {r["path"]: r for r in actual}
    expected_by_path = {r["path"]: r for r in expected}
    missing = sorted(expected_by_path.keys() - actual_by_path.keys())
    extra = sorted(actual_by_path.keys() - expected_by_path.keys())
    changed = sorted(
        k
        for k in actual_by_path.keys() & expected_by_path.keys()
        if actual_by_path[k] != expected_by_path[k]
    )
    if missing or extra or changed:
        raise ValueError(
            f"{label}: source closure mismatch; missing={missing[:8]}, "
            f"extra={extra[:8]}, changed bytes/modes={changed[:8]}"
        )


def _read_skill(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"{path}: missing skill frontmatter")
    if not re.search(r"(?m)^description:\s*\S", match[1]):
        raise ValueError(f"{path}: missing operative description")
    body = text[match.end() :]
    if len(body) > 20_000 or len(text.splitlines()) > 500:
        raise ValueError(f"{path}: exceeds standard skill instruction size budget")
    return match[1], body


def _validate_projection(codex: Path, canonical: dict, bundle: dict) -> None:
    report = read_object(codex / "adapters/codex/projection.json")
    if (
        report.get("schema_version") != 1
        or report.get("source_commit") != bundle["upstream"]["commit"]
        or report.get("source_version") != bundle["upstream"]["version"]
        or report.get("bundle_version") != bundle["version"]
    ):
        raise ValueError("Codex projection: mixed source or bundle identity")
    sources = {"pstack/" + row["path"]: row for row in canonical["files"]}
    mapping = report.get("source_mapping")
    if not isinstance(mapping, list) or len(mapping) != len(sources):
        raise ValueError("Codex projection must account for every canonical source path")
    seen, outputs = set(), set()
    for entry in mapping:
        if not isinstance(entry, dict) or entry.get("source") not in sources:
            raise ValueError("Codex projection contains an unknown source path")
        source = entry["source"]
        if source in seen or entry.get("source_sha256") != sources[source]["sha256"]:
            raise ValueError("Codex projection: duplicate source or changed source fingerprint")
        seen.add(source)
        transforms = entry.get("transforms")
        if not isinstance(transforms, list) or any(
            not isinstance(t, str) or not t for t in transforms
        ):
            raise ValueError("Codex projection requires named transforms")
        output = entry.get("output")
        if output is None:
            if source != "pstack/.cursor-plugin/plugin.json" or transforms != [
                "host-manifest-overlay"
            ]:
                raise ValueError(f"Codex projection may not omit required source: {source}")
            continue
        output = safe_relative(output)
        if output in outputs:
            raise ValueError(f"Codex projection output collision: {output}")
        outputs.add(output)
        row = file_record(codex / output, output)
        if row["mode"] != sources[source]["mode"]:
            raise ValueError(f"Codex source resource executable mode changed: {output}")
        if not transforms and row["sha256"] != entry["source_sha256"]:
            raise ValueError(f"Codex resource changed without a named transform: {output}")
    provenance = read_object(codex / "UPSTREAM.json")
    if (
        provenance.get("upstream") != bundle["upstream"]
        or provenance.get("bundle_version") != bundle["version"]
        or provenance.get("adapter", {}).get("sha256") != bundle["adapter"]["sha256"]
    ):
        raise ValueError("Codex provenance disagrees with its bundle binding")
    if provenance.get("projection") != report:
        raise ValueError("Codex provenance disagrees with the complete source projection")


def _validate_codex_manifests(codex: Path, version: str) -> None:
    portable = read_object(codex / "plugin.json")
    string_fields = {
        "$schema",
        "name",
        "version",
        "description",
        "homepage",
        "repository",
        "license",
    }
    allowed = string_fields | {"author", "keywords", "extensions"}
    if set(portable) - allowed:
        raise ValueError("Codex portable manifest: unsupported fields")
    if portable.get("$schema") != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json":
        raise ValueError("Codex portable manifest: incorrect schema")
    for field in string_fields:
        if not isinstance(portable.get(field), str) or not portable[field].strip():
            raise ValueError(f"Codex portable manifest: missing/invalid {field}")
    author = portable.get("author")
    if (
        not isinstance(author, dict)
        or set(author) - {"name", "email", "url"}
        or not isinstance(author.get("name"), str)
        or not author["name"].strip()
        or any(not isinstance(value, str) for value in author.values())
    ):
        raise ValueError("Codex portable manifest: invalid upstream author attribution")
    keywords = portable.get("keywords")
    if not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
        raise ValueError("Codex portable manifest: invalid keywords")
    extensions = portable.get("extensions", {})
    if not isinstance(extensions, dict) or any(
        not isinstance(value, dict) for value in extensions.values()
    ):
        raise ValueError("Codex portable manifest: invalid extensions")
    if portable.get("name") != "pstack" or portable.get("version") != version:
        raise ValueError("Codex portable manifest: wrong selected identity/version")
    native = read_object(codex / ".codex-plugin/plugin.json")
    expected = {key: portable[key] for key in ("name", "version", "description", "keywords")}
    expected["skills"] = "./skills"
    if native != expected:
        raise ValueError("Codex native manifest: unsupported fields or unbound skill root")


def _validate_codex(codex: Path, canonical: dict, bundle: dict) -> list[dict]:
    manifest = read_object(codex / "payload-manifest.json")
    if manifest.get("schema_version") != 1:
        raise ValueError("Codex payload: unsupported manifest schema")
    if manifest.get("upstream") != {k: bundle["upstream"][k] for k in ("version", "commit")}:
        raise ValueError("Codex payload: mixed upstream identity")
    if manifest.get("bundle_version") != bundle["version"]:
        raise ValueError("Codex payload: mismatched bundle version")
    recorded = manifest_records(manifest, "Codex payload")
    if any(row["path"] == "payload-manifest.json" for row in recorded):
        raise ValueError("Codex payload manifest must not hash itself")
    actual = tree_records(codex, exclude=frozenset({"payload-manifest.json"}))
    _equal_records(actual, recorded, "Codex payload")
    if manifest.get("tree_sha256") != tree_digest(recorded):
        raise ValueError("Codex payload: incorrect content digest")
    _validate_projection(codex, canonical, bundle)
    sources = {r["path"]: r for r in canonical["files"]}
    names = sorted(p.split("/")[1] for p in sources if re.fullmatch(r"skills/[^/]+/SKILL\.md", p))
    if len(names) != 58 or any(SKILL_NAME.fullmatch(n) is None for n in names):
        raise ValueError("pstack profile requires the reviewed 58 upstream skill identities")
    descriptors = sorted(p.relative_to(codex).as_posix() for p in codex.rglob("SKILL.md"))
    expected = sorted(f"skills/{n}/SKILL.md" for n in names)
    if descriptors != expected:
        raise ValueError(
            "Codex discovery must contain exactly 58 top-level skills; dormant skills may not register"
        )
    index = read_object(codex / "skills/index.json")
    # The index is not a second discovery root; it binds hidden/manual siblings.
    entries = index.get("skills", index)
    if not isinstance(entries, dict) or sorted(entries) != names:
        raise ValueError("Codex skill index must map every upstream skill exactly once")
    for name in names:
        descriptor = codex / f"skills/{name}/SKILL.md"
        frontmatter, _ = _read_skill(descriptor)
        if not re.search(
            rf"(?m)^name:\s*(?:{re.escape(name)}|\"{re.escape(name)}\")\s*$", frontmatter
        ):
            raise ValueError(f"{name}: descriptor name disagrees with directory")
        _read_skill(codex / f"skills/{name}/instructions.md")
        policy = (codex / f"skills/{name}/agents/openai.yaml").read_text(encoding="utf-8")
        values = re.findall(r"(?m)^\s+allow_implicit_invocation:\s*(true|false)\s*$", policy)
        if values != ["true" if name == "setup-pstack" else "false"]:
            raise ValueError(f"{name}: incorrect native Codex invocation policy")
        row = entries[name]
        if not isinstance(row, dict):
            raise ValueError(f"{name}: skill index entry must be an object")
        for field, suffix in [("descriptor", "SKILL.md"), ("instructions", "instructions.md")]:
            if row.get(field) != f"skills/{name}/{suffix}":
                raise ValueError(f"{name}: {field} points outside its bound skill")
        if row.get("source_path") != f"pstack/skills/{name}/SKILL.md":
            raise ValueError(f"{name}: source instruction path mismatch")
        if row.get("source_sha256") != sources[f"skills/{name}/SKILL.md"]["sha256"]:
            raise ValueError(f"{name}: source instruction fingerprint mismatch")
        if row.get("allow_implicit_invocation") is not (name == "setup-pstack"):
            raise ValueError(f"{name}: skill index invocation policy mismatch")
    for required in [
        "README.md",
        "LICENSE",
        "UPSTREAM.json",
        "skills/poteto-mode/worker.md",
        "agents/poteto-agent.md",
        "agents/comment-sicko.md",
        "dependencies/cursor-team-kit/LICENSE",
        "dependencies/cursor-team-kit/deslop.md",
        "dependencies/cursor-team-kit/control-ui.md",
        "dependencies/cursor-team-kit/control-cli.md",
    ]:
        _regular_file(codex / required)
    _validate_codex_manifests(codex, bundle["version"])
    return tree_records(codex)


def require_valid_bundle(
    root: Path,
    package_dir: Path | None = None,
    *,
    projection: dict | None = None,
) -> dict:
    """Validate a checked-in or staged candidate against repository-owned inputs.

    A caller validating a stage must pass the trusted repository explicitly. The
    public plugin validator only enables this route for its own packages/pstack.
    """
    root = root.absolute()
    package = (package_dir or root / BUNDLE_PATH).absolute()
    if package_dir is None:
        _directory(root / "packages")
    _directory(package)
    lock, canonical, claude = trusted_integration(root)
    bundle = read_object(package / "bundle.json")
    if bundle.get("schema_version") != 1 or bundle.get("name") != BUNDLE_NAME:
        raise ValueError("invalid pstack bundle identity/schema")
    parse_version(bundle.get("version"))
    projection = projection or read_object(root / INTEGRATION_PATH / "projection.json")
    if projection.get("package", {}).get("version") != bundle["version"]:
        raise ValueError("bundle version disagrees with maintained projection")
    if bundle.get("upstream") != {
        k: lock[k] for k in ("repository", "commit", "version", "canonical_tree", "claude_tree")
    }:
        raise ValueError("bundle upstream identity disagrees with locked inputs")
    _sha(bundle.get("adapter", {}).get("sha256"), HEX64, "adapter identity")
    if set(bundle.get("targets", {})) != set(HOSTS):
        raise ValueError("bundle must contain exactly the Claude and Codex targets")
    if {p.name for p in package.iterdir()} != {"bundle.json", "README.md", "LICENSE", *HOSTS}:
        raise ValueError("bundle container must contain only metadata, notices and its two targets")
    for relative in ["README.md", "LICENSE"]:
        _regular_file(package / relative)
    claude_rows = tree_records(package / "claude-code")
    _equal_records(claude_rows, manifest_records(claude, "Claude source"), "Claude target")
    if git_tree_digest(package / "claude-code") != lock["claude_tree"]:
        raise ValueError("Claude target: actual Git tree differs from locked upstream tree")
    for native in ["plugin.json", ".claude-plugin/plugin.json"]:
        data = read_object(package / "claude-code" / native)
        if data.get("name") != "pstack" or data.get("version") != lock["version"]:
            raise ValueError("Claude native version/identity must match the upstream input")
    codex_rows = _validate_codex(package / "codex", canonical, bundle)
    for host, rows, version in [
        ("claude-code", claude_rows, lock["version"]),
        ("codex", codex_rows, bundle["version"]),
    ]:
        target = bundle["targets"][host]
        if (
            not isinstance(target, dict)
            or target.get("path") != host
            or target.get("version") != version
        ):
            raise ValueError(f"{host}: incorrect selected target path/version")
        if target.get("tree_sha256") != tree_digest(rows):
            raise ValueError(f"{host}: selected tree digest mismatch")
    payload_sha = hashlib.sha256((package / "codex/payload-manifest.json").read_bytes()).hexdigest()
    if bundle["targets"]["codex"].get("payload_manifest_sha256") != payload_sha:
        raise ValueError("Codex payload manifest digest mismatch")
    _scan_artifacts(package, canonical, claude)
    return bundle


def validate_bundle(root: Path, package_dir: Path | None = None) -> list[str]:
    try:
        require_valid_bundle(root, package_dir)
        return []
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return [f"packages/pstack: {exc}"]


def bundle_archive_inputs(
    root: Path, target: str | None = None
) -> tuple[str, list[tuple[Path, str]]]:
    bundle = require_valid_bundle(root)
    if target is not None and target not in HOSTS:
        raise ValueError(f"unsupported pstack target: {target!r}")
    selected = root / BUNDLE_PATH
    if target is not None:
        selected /= target
    # The Agents API ZIP contract requires one enclosing plugin folder.
    prefix = "pstack/"
    entries = [(selected / row["path"], prefix + row["path"]) for row in tree_records(selected)]
    return bundle["version"], entries


def approved_fixture(root: Path, path: Path) -> bool:
    """Permit only hash-identical upstream Statechart report fixtures by path."""
    try:
        relative = path.absolute().relative_to((root / BUNDLE_PATH).absolute())
        host, *parts = relative.parts
        resource = "/".join(parts)
        if host not in HOSTS or not re.fullmatch(
            r"skills/statechart/scripts/test/corpus/[^/]+/report\.md", resource
        ):
            return False
        lock, canonical, claude = trusted_integration(root)
        manifest = claude if host == "claude-code" else canonical
        row = next((r for r in manifest["files"] if r["path"] == resource), None)
        return row is not None and file_record(path, resource) == {
            k: row[k] for k in ("path", "sha256", "mode", "size")
        }
    except (OSError, ValueError, TypeError, KeyError):
        return False
