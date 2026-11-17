"""Project reviewed canonical pstack inputs into one Codex plugin root."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"unsafe projection path: {value!r}")
    if path.as_posix() != value or value == ".":
        raise ValueError(f"noncanonical projection path: {value!r}")
    return value


def _files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"projection input is not a real directory: {root}")
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"symlink in projection input: {Path(directory) / name}")
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f"projection input is not a regular file: {path}")
            result.append(path)
    return sorted(result)


def split_skill(text: str) -> tuple[str, str, dict]:
    """Read the reviewed upstream scalar frontmatter without a runtime YAML dependency."""
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError("skill must begin with YAML frontmatter")
    lines = match.group(1).splitlines()
    values = {}
    for index, line in enumerate(lines):
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        key, separator, raw = line.partition(":")
        if not separator or key in values:
            raise ValueError("unsupported or duplicate skill frontmatter key")
        raw = raw.strip()
        if raw in {">", ">-", "|", "|-"}:
            continuation = []
            for following in lines[index + 1:]:
                if following and not following[0].isspace():
                    break
                continuation.append(following.strip())
            values[key] = (" " if raw.startswith(">") else "\n").join(continuation)
        elif raw.startswith('"'):
            values[key] = json.loads(raw)
        elif raw.startswith("'") and raw.endswith("'"):
            values[key] = raw[1:-1].replace("''", "'")
        elif raw in {"true", "false"}:
            values[key] = raw == "true"
        else:
            values[key] = raw
    if not isinstance(values.get("name"), str) or not isinstance(values.get("description"), str):
        raise ValueError("skill name and description must be text")
    return text[:match.end()], text[match.end():], values


def apply_edits(path: str, data: bytes, rule: dict | None) -> tuple[bytes, list[str]]:
    if rule is None:
        return data, []
    if _digest(data) != rule["source_sha256"]:
        raise ValueError(f"unreviewed upstream transform input: {path}")
    text = data.decode("utf-8")
    applied = []
    for edit in rule["edits"]:
        before, after = edit["before"], edit["after"]
        if not before or text.count(before) != edit["count"]:
            raise ValueError(f"changed transform anchor: {path}: {edit['id']}")
        text = text.replace(before, after)
        applied.append(edit["id"])
    return text.encode("utf-8"), applied


def _copy_bytes(path: Path, data: bytes, source: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if source and source.stat().st_mode & 0o111 else 0o644)


def _descriptor(name: str, description: str, template: str, context: dict) -> str:
    substitutions = {
        "{{skill}}": name,
        "{{upstream_commit}}": context["upstream_commit"],
        "{{upstream_version}}": context["upstream_version"],
        "{{bundle_version}}": context["bundle_version"],
    }
    for marker, value in substitutions.items():
        template = template.replace(marker, value)
    if "{{" in template:
        raise ValueError("unresolved descriptor template variable")
    return f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n{template}"


def project_codex(source_root: Path, output_root: Path, adapter_root: Path, context: dict) -> dict:
    """Generate into an empty staging root; never mutate canonical or adapter inputs.

    The caller owns the external upstream lock and final noncircular payload
    manifest. This function additionally fences every reviewed text transform.
    """
    source_root, output_root, adapter_root = (
        Path(source_root).resolve(), Path(output_root).absolute(), Path(adapter_root).resolve()
    )
    if output_root.is_symlink():
        raise ValueError("output root cannot be a symlink")
    output_root = output_root.resolve()
    for retained in (source_root, adapter_root):
        if output_root == retained or output_root.is_relative_to(retained):
            raise ValueError("projection output must be outside its immutable inputs")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("Codex projection requires an empty output directory")
    for field in ("upstream_commit", "upstream_version", "bundle_version"):
        if not isinstance(context.get(field), str):
            raise ValueError(f"missing projection context: {field}")
    if not re.fullmatch(r"[0-9a-f]{40}", context["upstream_commit"]):
        raise ValueError("upstream commit must be a complete Git SHA")
    for field in ("upstream_version", "bundle_version"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", context[field]):
            raise ValueError(f"invalid version: {field}")
    rules = _json(adapter_root / "transforms" / "rules.json")
    if rules["source_commit"] != context["upstream_commit"]:
        raise ValueError("transforms have not been reviewed for this upstream commit")
    source = source_root / "pstack"
    inputs = _files(source)
    input_paths = {p.relative_to(source).as_posix() for p in inputs}
    transforms = rules["files"]
    if set(transforms) - input_paths:
        raise ValueError("reviewed transform references a deleted upstream path")
    for relative in transforms:
        _relative(relative)
    skill_names = sorted(p.parent.name for p in inputs if p.match("*/skills/*/SKILL.md")
                         and len(p.relative_to(source).parts) == 3)
    if skill_names != rules["registered_skills"]:
        raise ValueError("upstream skill identities changed; review projection policy")
    descriptor_template = (adapter_root / "templates" / "descriptor.md").read_text("utf-8")
    binding = (adapter_root / "templates" / "operative-binding.md").read_text("utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    mapping = []
    index = {}
    for original in inputs:
        relative = original.relative_to(source).as_posix()
        data = original.read_bytes()
        record = {"source": f"pstack/{relative}", "source_sha256": _digest(data)}
        if relative == ".cursor-plugin/plugin.json":
            mapping.append({**record, "output": None, "transforms": ["host-manifest-overlay"]})
            continue
        if relative == "plugin.json":
            manifest = json.loads(data)
            if manifest["version"] != context["upstream_version"]:
                raise ValueError("source version differs from reviewed context")
            manifest["version"] = context["bundle_version"]
            if interface := rules.get("plugin_interface"):
                manifest.setdefault("extensions", {}).setdefault("com.openai", {}).setdefault(
                    "interface", {}
                ).update(interface)
            _write_json(output_root / relative, manifest)
            native = {key: manifest[key] for key in ("name", "version", "description", "keywords")}
            native["skills"] = "./skills"
            if interface := manifest.get("extensions", {}).get("com.openai", {}).get("interface"):
                native["interface"] = interface
            _write_json(output_root / ".codex-plugin" / "plugin.json", native)
            mapping.append({**record, "output": relative, "transforms": ["host-manifest-overlay"]})
            continue
        transformed, edits = apply_edits(relative, data, transforms.get(relative))
        parts = PurePosixPath(relative).parts
        is_skill = len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md"
        dormant = parts[:2] == ("automations", "benny") and parts[-1] == "SKILL.md"
        target = relative
        if is_skill:
            header, body, values = split_skill(transformed.decode("utf-8"))
            original_values = split_skill(data.decode("utf-8"))[2]
            name = parts[1]
            if values["name"] != name:
                raise ValueError(f"skill name differs from its directory: {relative}")
            implicit = not values.get("disable-model-invocation", False)
            if implicit != (name == "setup-pstack"):
                raise ValueError(f"unreviewed invocation policy: {relative}")
            target = f"skills/{name}/instructions.md"
            transformed = (header + "\n" + binding + body.lstrip("\n")).encode("utf-8")
            descriptor = _descriptor(name, original_values["description"], descriptor_template, context)
            _copy_bytes(output_root / relative, descriptor.encode("utf-8"))
            _copy_bytes(output_root / f"skills/{name}/agents/openai.yaml",
                        f"policy:\n  allow_implicit_invocation: {str(implicit).lower()}\n".encode())
            index[name] = {"descriptor": relative, "instructions": target,
                           "source_path": record["source"], "source_sha256": record["source_sha256"],
                           "allow_implicit_invocation": implicit}
            edits = ["operative-body-dispatch", "native-invocation-policy", *edits]
        elif dormant:
            target = str(PurePosixPath(relative).with_name("instructions.md"))
            edits = ["dormant-automation-resource", *edits]
        _copy_bytes(output_root / target, transformed, original)
        mapping.append({**record, "output": target, "transforms": edits})

    dependencies = []
    for item in rules["dependencies"]:
        original = source_root / _relative(item["source"])
        if original.is_symlink() or not original.is_file():
            raise ValueError(f"missing or unsafe canonical dependency: {item['source']}")
        data = original.read_bytes()
        if _digest(data) != item["sha256"]:
            raise ValueError(f"canonical dependency changed: {item['source']}")
        _copy_bytes(output_root / _relative(item["output"]), data, original)
        dependencies.append(item)

    for name in ("adapter.md", "compatibility.json"):
        original = adapter_root / name
        _copy_bytes(output_root / "adapters" / "codex" / name, original.read_bytes(), original)
    if not (adapter_root / "runtime" / "pstack_runtime.py").is_file():
        raise ValueError("Codex projection requires the complete runtime entry point")
    for item in rules.get("adapter_files", []):
        original = adapter_root / _relative(item["source"])
        if original.is_symlink() or not original.is_file():
            raise ValueError(f"missing adapter projection resource: {item['source']}")
        _copy_bytes(output_root / _relative(item["output"]), original.read_bytes(), original)
    for directory in ("runtime", "bridge", "providers", "schemas", "watch_pr"):
        root = adapter_root / directory
        if not root.exists():
            continue
        for original in _files(root):
            if "__pycache__" in original.parts or original.suffix == ".pyc":
                continue
            if directory == "watch_pr" and original.suffix in {".ts", ".in"}:
                continue
            target = output_root / "adapters" / "codex" / directory / original.relative_to(root)
            _copy_bytes(target, original.read_bytes(), original)
    readme = (adapter_root / "templates" / "codex-readme.md.in").read_text("utf-8")
    _copy_bytes(output_root / "README.md", readme.encode("utf-8"))
    # Retain the source README in place beneath the host-specific introduction;
    # its existing relative documentation/asset links still resolve at the root.
    with (output_root / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("\n---\n\n## Canonical upstream guide\n\n")
        readme_data, _ = apply_edits("README.md", (source / "README.md").read_bytes(),
                                    transforms.get("README.md"))
        handle.write(readme_data.decode("utf-8"))
    for record in mapping:
        if record["source"] == "pstack/README.md":
            record["transforms"].append("codex-installation-introduction")
    _write_json(output_root / "skills" / "index.json", {"schema_version": 1, "skills": index})
    report = {"schema_version": 1, "source_commit": context["upstream_commit"],
              "source_version": context["upstream_version"], "bundle_version": context["bundle_version"],
              "registered_skills": skill_names, "source_mapping": mapping,
              "dependencies": dependencies, "adapter_files": rules.get("adapter_files", []),
              "runtime_certification": "not_performed"}
    _write_json(output_root / "adapters" / "codex" / "projection.json", report)
    return report
