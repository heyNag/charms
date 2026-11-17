"""Validate real assembled bundle structure and hostile drift, without network."""

from __future__ import annotations

import contextlib
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pstack_bundle as bundle  # noqa: E402
from plugin_archive import extract_archive  # noqa: E402


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def native_manifest(version: str) -> dict:
    return {
        "name": "pstack",
        "version": version,
        "description": "A workflow suite.",
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "author": {"name": "Upstream"},
        "license": "MIT",
        "homepage": "https://example.com",
        "repository": "https://example.com",
        "keywords": ["workflow"],
    }


def source_manifest(source: Path, commit: str, path: str) -> dict:
    rows = bundle.tree_records(source)
    for row in rows:
        data = (source / row["path"]).read_bytes()
        row["git_blob"] = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
    return {
        "schema_version": 1,
        "commit": commit,
        "path": path,
        "git_tree": bundle.git_tree_digest(source),
        "files": rows,
    }


def refresh_codex(root: Path) -> None:
    package = root / "packages/pstack"
    metadata = json.loads((package / "bundle.json").read_text())
    codex = package / "codex"
    files = bundle.tree_records(codex, exclude=frozenset({"payload-manifest.json"}))
    payload = {
        "schema_version": 1,
        "upstream": {k: metadata["upstream"][k] for k in ("commit", "version")},
        "bundle_version": metadata["version"],
        "files": files,
        "tree_sha256": bundle.tree_digest(files),
    }
    write_json(codex / "payload-manifest.json", payload)
    metadata["targets"]["codex"].update(
        {
            "tree_sha256": bundle.tree_digest(bundle.tree_records(codex)),
            "payload_manifest_sha256": hashlib.sha256(
                (codex / "payload-manifest.json").read_bytes()
            ).hexdigest(),
        }
    )
    write_json(package / "bundle.json", metadata)


def make_bundle(root: Path) -> Path:
    package = root / "packages/pstack"
    claude = package / "claude-code"
    codex = package / "codex"
    canonical = root / "source/pstack"
    integration = root / "integrations/pstack"
    names = sorted(
        ["setup-pstack", "poteto-mode", "statechart", "ketchup", "ketchup-video"]
        + [f"skill-{n}" for n in range(53)]
    )
    index = {}
    for name in names:
        text = f"---\nname: {name}\ndescription: Use {name}.\n---\n\nPerform the task.\n"
        write(canonical / f"skills/{name}/SKILL.md", text)
        write(codex / f"skills/{name}/SKILL.md", text)
        write(codex / f"skills/{name}/instructions.md", text)
        implicit = name == "setup-pstack"
        write(
            codex / f"skills/{name}/agents/openai.yaml",
            f"policy:\n  allow_implicit_invocation: {str(implicit).lower()}\n",
        )
        index[name] = {
            "descriptor": f"skills/{name}/SKILL.md",
            "instructions": f"skills/{name}/instructions.md",
            "source_path": f"pstack/skills/{name}/SKILL.md",
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "allow_implicit_invocation": implicit,
        }
    for host, version, overlay in [
        (claude, "0.15.43", ".claude-plugin"),
        (codex, "2026.11.0", ".codex-plugin"),
    ]:
        write_json(host / "plugin.json", native_manifest(version))
        native = native_manifest(version)
        if host == codex:
            native = {key: native[key] for key in ("name", "version", "description", "keywords")}
            native["skills"] = "./skills"
        write_json(host / overlay / "plugin.json", native)
        write(host / "README.md", "# pstack\n")
        write(host / "LICENSE", "MIT\n")
    fixture = "skills/statechart/scripts/test/corpus/Counter/report.md"
    for host in [canonical, claude, codex]:
        write(host / fixture, "Pinned upstream fixture.\n")
    executable = claude / "skills/statechart/scripts/run.sh"
    write(executable, "#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    for resource in [
        "skills/poteto-mode/worker.md",
        "agents/poteto-agent.md",
        "agents/comment-sicko.md",
        "dependencies/cursor-team-kit/LICENSE",
        "dependencies/cursor-team-kit/deslop.md",
        "dependencies/cursor-team-kit/control-ui.md",
        "dependencies/cursor-team-kit/control-cli.md",
    ]:
        write(codex / resource, "Resource.\n")
    write_json(codex / "skills/index.json", {"skills": index})
    write_json(codex / "UPSTREAM.json", {"commit": "a" * 40})
    commit = "a" * 40
    canonical_manifest = source_manifest(canonical, commit, "pstack")
    claude_manifest = source_manifest(claude, commit, "harness/pstack/claude-code")
    lock = {
        "schema_version": 1,
        "repository": "https://github.com/cursor/plugins",
        "commit": commit,
        "version": "0.15.43",
        "canonical_path": "pstack",
        "claude_path": "harness/pstack/claude-code",
        "canonical_tree": canonical_manifest["git_tree"],
        "claude_tree": claude_manifest["git_tree"],
        "inputs": {},
    }
    for name, manifest in [("canonical", canonical_manifest), ("claude", claude_manifest)]:
        lock["inputs"][name] = {
            "manifest": f"source-manifests/{name}.json",
            "files": len(manifest["files"]),
            "path": manifest["path"],
            "git_tree": manifest["git_tree"],
        }
        write_json(integration / f"source-manifests/{name}.json", manifest)
    write_json(integration / "upstream.lock.json", lock)
    write_json(integration / "projection.json", {"package": {"version": "2026.11.0"}})
    metadata = {
        "schema_version": 1,
        "name": "pstack",
        "version": "2026.11.0",
        "upstream": {
            k: lock[k] for k in ("repository", "commit", "version", "canonical_tree", "claude_tree")
        },
        "adapter": {"sha256": "b" * 64},
        "targets": {
            "claude-code": {
                "path": "claude-code",
                "version": "0.15.43",
                "tree_sha256": bundle.tree_digest(bundle.tree_records(claude)),
            },
            "codex": {"path": "codex", "version": "2026.11.0"},
        },
    }
    mapping = []
    for row in canonical_manifest["files"]:
        is_skill = row["path"].endswith("/SKILL.md")
        mapping.append(
            {
                "source": "pstack/" + row["path"],
                "source_sha256": row["sha256"],
                "output": row["path"].replace("/SKILL.md", "/instructions.md")
                if is_skill
                else row["path"],
                "transforms": ["operative-body-dispatch"] if is_skill else [],
            }
        )
    projection = {
        "schema_version": 1,
        "source_commit": commit,
        "source_version": lock["version"],
        "bundle_version": metadata["version"],
        "source_mapping": mapping,
    }
    write_json(codex / "adapters/codex/projection.json", projection)
    write_json(
        codex / "UPSTREAM.json",
        {
            "schema_version": 1,
            "upstream": metadata["upstream"],
            "bundle_version": metadata["version"],
            "adapter": metadata["adapter"],
            "projection": projection,
        },
    )
    write_json(package / "bundle.json", metadata)
    write(package / "README.md", "# pstack bundle\n")
    write(package / "LICENSE", "MIT\n")
    refresh_codex(root)
    return package


class PstackBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = make_bundle(self.root)

    def assert_invalid(self, text: str):
        errors = bundle.validate_bundle(self.root)
        self.assertTrue(any(text in error for error in errors), errors)

    def test_intact_bundle_and_pinned_fixture_are_accepted(self):
        self.assertEqual(bundle.validate_bundle(self.root), [])
        path = self.package / "claude-code/skills/statechart/scripts/test/corpus/Counter/report.md"
        self.assertTrue(bundle.approved_fixture(self.root, path))
        path.write_text("Changed fixture.\n")
        self.assertFalse(bundle.approved_fixture(self.root, path))
        self.assert_invalid("Claude target: source closure mismatch")

    def test_changed_claude_bytes_modes_missing_and_extra_paths_fail(self):
        for mutation in ["bytes", "mode", "missing", "extra"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package = make_bundle(root)
                path = package / "claude-code/skills/statechart/scripts/run.sh"
                if mutation == "bytes":
                    path.write_text("changed\n")
                if mutation == "mode":
                    path.chmod(0o644)
                if mutation == "missing":
                    path.unlink()
                if mutation == "extra":
                    write(package / "claude-code/stale.md", "stale\n")
                self.assertTrue(bundle.validate_bundle(root))

    def test_editing_manifest_and_target_digests_cannot_forge_the_locked_claude_tree(self):
        write(self.package / "claude-code/README.md", "changed\n")
        manifest_path = self.root / "integrations/pstack/source-manifests/claude.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"] = bundle.tree_records(self.package / "claude-code")
        write_json(manifest_path, manifest)
        metadata = json.loads((self.package / "bundle.json").read_text())
        metadata["targets"]["claude-code"]["tree_sha256"] = bundle.tree_digest(manifest["files"])
        write_json(self.package / "bundle.json", metadata)
        self.assert_invalid("actual Git tree differs")

    def test_payload_tamper_and_missing_worker_fail(self):
        (self.package / "codex/skills/poteto-mode/worker.md").unlink()
        self.assert_invalid("Codex payload: source closure mismatch")
        refresh_codex(self.root)
        self.assert_invalid("worker.md")

    def test_manual_policy_cannot_be_relaxed_by_rehashing_payload(self):
        write(
            self.package / "codex/skills/skill-1/agents/openai.yaml",
            "policy:\n  allow_implicit_invocation: true\n",
        )
        refresh_codex(self.root)
        self.assert_invalid("incorrect native Codex invocation policy")

    def test_dormant_skill_cannot_be_registered(self):
        write(
            self.package / "codex/automations/benny/skills/setup-benny/SKILL.md",
            "---\nname: benny\n---\n",
        )
        refresh_codex(self.root)
        self.assert_invalid("exactly 58 top-level skills")

    def test_metadata_cannot_escape_to_sibling_or_parent(self):
        index_path = self.package / "codex/skills/index.json"
        index = json.loads(index_path.read_text())
        index["skills"]["skill-1"]["instructions"] = "../claude-code/skills/skill-1/SKILL.md"
        write_json(index_path, index)
        refresh_codex(self.root)
        self.assert_invalid("points outside its bound skill")

    def test_mixed_upstream_and_circular_payload_fail(self):
        path = self.package / "codex/payload-manifest.json"
        data = json.loads(path.read_text())
        data["upstream"]["commit"] = "c" * 40
        write_json(path, data)
        self.assert_invalid("mixed upstream identity")

    def test_native_manifest_cannot_register_arbitrary_roles_or_sibling_roots(self):
        path = self.package / "codex/.codex-plugin/plugin.json"
        data = json.loads(path.read_text())
        data["skills"] = "../claude-code/skills"
        data["agents"] = "./agents"
        write_json(path, data)
        refresh_codex(self.root)
        self.assert_invalid("unsupported fields or unbound skill root")

    def add_codex_artwork(self):
        codex = self.package / "codex"
        interface = {"logo": "./assets/pstack.svg", "composerIcon": "./assets/pstack.svg"}
        portable = json.loads((codex / "plugin.json").read_text())
        portable["extensions"] = {"com.openai": {"interface": interface}}
        write_json(codex / "plugin.json", portable)
        native = json.loads((codex / ".codex-plugin/plugin.json").read_text())
        native["interface"] = interface
        write_json(codex / ".codex-plugin/plugin.json", native)
        write(codex / "assets/pstack.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"/>')
        refresh_codex(self.root)

    def test_matching_packaged_artwork_is_accepted(self):
        self.add_codex_artwork()
        self.assertEqual(bundle.validate_bundle(self.root), [])

    def test_native_artwork_must_match_portable_manifest(self):
        self.add_codex_artwork()
        path = self.package / "codex/.codex-plugin/plugin.json"
        native = json.loads(path.read_text())
        native["interface"]["logo"] = "./assets/other.svg"
        write_json(path, native)
        refresh_codex(self.root)
        self.assert_invalid("unsupported fields or unbound skill root")

    def test_rehashed_payload_cannot_hide_missing_artwork(self):
        self.add_codex_artwork()
        (self.package / "codex/assets/pstack.svg").unlink()
        refresh_codex(self.root)
        self.assert_invalid("logo artwork is not a packaged file")

    def test_artwork_cannot_reference_files_outside_the_package(self):
        self.add_codex_artwork()
        codex = self.package / "codex"
        for reference in ("../claude-code/README.md", str(self.package / "claude-code/README.md")):
            with self.subTest(reference=reference):
                portable = json.loads((codex / "plugin.json").read_text())
                interface = portable["extensions"]["com.openai"]["interface"]
                interface["logo"] = reference
                write_json(codex / "plugin.json", portable)
                native = json.loads((codex / ".codex-plugin/plugin.json").read_text())
                native["interface"] = interface
                write_json(codex / ".codex-plugin/plugin.json", native)
                refresh_codex(self.root)
                self.assert_invalid("invalid relative resource path")

    def test_deleted_source_cannot_be_hidden_by_removing_it_from_payload_manifest(self):
        path = self.package / "codex/skills/statechart/scripts/test/corpus/Counter/report.md"
        path.unlink()
        refresh_codex(self.root)
        self.assert_invalid("report.md")

    def test_source_manifest_path_traversal_and_duplicate_json_are_rejected(self):
        path = self.root / "integrations/pstack/upstream.lock.json"
        data = json.loads(path.read_text())
        data["inputs"]["claude"]["manifest"] = "../../attacker.json"
        write_json(path, data)
        self.assert_invalid("invalid relative resource path")
        path.write_text('{"schema_version":1,"schema_version":1}')
        self.assert_invalid("duplicate JSON key")

    def test_secret_and_unpinned_report_rejected_even_after_rehash(self):
        for name, content in [
            ("report.md", "generated report"),
            ("notes.md", "sk-" + "x" * 32),
            ("private-key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package = make_bundle(root)
                write(package / "codex" / name, content)
                refresh_codex(root)
                self.assertTrue(bundle.validate_bundle(root))

    def test_symlink_and_special_file_are_not_followed(self):
        path = self.package / "codex/link"
        path.symlink_to(self.root / "source")
        self.assert_invalid("symlink")
        path.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(path)
            self.assert_invalid("regular file")

    def test_external_plugin_cannot_select_profile_with_bundle_json(self):
        validator = load_script("validate_plugins")
        external = self.root / "untrusted/pstack"
        shutil.copytree(self.package, external)
        schema, errors = validator._load_schema(ROOT / validator.SCHEMA_RELATIVE_PATH)
        self.assertEqual(errors, [])
        errors = validator.validate_plugin_root(external, schema, report_root=self.root)
        self.assertTrue(any("missing Agent Plugins manifest" in e for e in errors), errors)

    def test_staging_requires_explicit_repository_and_valid_projection_override(self):
        stage = self.root / "candidate"
        shutil.copytree(self.package, stage)
        self.assertEqual(bundle.require_valid_bundle(self.root, stage)["version"], "2026.11.0")
        with self.assertRaisesRegex(ValueError, "disagrees with maintained projection"):
            bundle.require_valid_bundle(
                self.root, stage, projection={"package": {"version": "2026.11.1"}}
            )

    def test_complete_and_selected_root_archives_are_distinct_and_deterministic(self):
        archive = load_script("build-plugin-archive")
        output = self.root / "artifacts"
        combined = archive.build_archive(self.root, "pstack", output)
        before = combined.archive.read_bytes()
        self.assertEqual(
            before, archive.build_archive(self.root, "pstack", output).archive.read_bytes()
        )
        codex = archive.build_archive(self.root, "pstack", output, "codex")
        claude = archive.build_archive(self.root, "pstack", output, "claude-code")
        self.assertEqual(
            len(
                {
                    hashlib.sha256(r.archive.read_bytes()).hexdigest()
                    for r in [combined, codex, claude]
                }
            ),
            3,
        )
        with zipfile.ZipFile(combined.archive) as z:
            self.assertIn(
                "pstack/claude-code/skills/statechart/scripts/test/corpus/Counter/report.md",
                z.namelist(),
            )
            self.assertIn("pstack/codex/skills/index.json", z.namelist())
        with zipfile.ZipFile(codex.archive) as z:
            self.assertEqual({name.split("/")[0] for name in z.namelist()}, {"pstack"})
            self.assertIn("pstack/.codex-plugin/plugin.json", z.namelist())
            self.assertNotIn("pstack/codex/plugin.json", z.namelist())
        with zipfile.ZipFile(claude.archive) as z:
            self.assertIn("pstack/.claude-plugin/plugin.json", z.namelist())
            self.assertNotIn("pstack/bundle.json", z.namelist())
            mode = z.getinfo("pstack/skills/statechart/scripts/run.sh").external_attr >> 16
            self.assertEqual(mode & 0o777, 0o755)
        with self.assertRaisesRegex(ValueError, "outside the plugin root"):
            archive.build_archive(self.root, "pstack", self.package / "artifacts")

    def test_release_workflow_build_extract_and_trusted_staged_validation(self):
        archive = load_script("build-plugin-archive")
        validator = load_script("validate_plugins")
        result = archive.build_archive(self.root, "pstack", self.root / "artifacts")
        extracted = self.root / "extracted"
        extracted.mkdir()
        extract_archive(result.archive, extracted)
        staged = extracted / "pstack"
        self.assertEqual(bundle.require_valid_bundle(self.root, staged)["version"], "2026.11.0")
        self.assertEqual(
            (staged / "claude-code/skills/statechart/scripts/run.sh").stat().st_mode & 0o777, 0o755
        )
        with (
            mock.patch.object(validator, "REPOSITORY_ROOT", self.root),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(validator.main(["--pstack-bundle", str(staged)]), 0)
        (staged / "claude-code/skills/statechart/scripts/run.sh").chmod(0o644)
        with (
            mock.patch.object(validator, "REPOSITORY_ROOT", self.root),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(validator.main(["--pstack-bundle", str(staged)]), 1)

    def test_archive_extraction_rejects_traversal_links_and_collisions_before_writing(self):
        cases = [
            [("../escape", stat.S_IFREG | 0o644)],
            [("/absolute", stat.S_IFREG | 0o644)],
            [("pstack/link", stat.S_IFLNK | 0o777)],
            [("pstack/pipe", stat.S_IFIFO | 0o644)],
            [("pstack/one", stat.S_IFREG | 0o644), ("PSTACK/ONE", stat.S_IFREG | 0o644)],
            [("pstack/one", stat.S_IFREG | 0o644), ("pstack/one/two", stat.S_IFREG | 0o644)],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                archive = root / "bad.zip"
                with zipfile.ZipFile(archive, "w") as zipped:
                    for name, mode in entries:
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = mode << 16
                        zipped.writestr(info, b"unsafe")
                output = root / "output"
                output.mkdir()
                with self.assertRaises(ValueError):
                    extract_archive(archive, output)
                self.assertEqual(list(output.iterdir()), [])
                self.assertFalse((root / "escape").exists())

    def test_corrupt_zip_never_publishes_partial_extraction(self):
        archive = self.root / "corrupt.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr("pstack/one", b"unique payload for CRC checking")
        archive.write_bytes(
            archive.read_bytes().replace(
                b"unique payload for CRC checking", b"forged payload for CRC checking"
            )
        )
        output = self.root / "output"
        output.mkdir()
        with self.assertRaises(zipfile.BadZipFile):
            extract_archive(archive, output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual(list(self.root.glob(".plugin-extract-*")), [])

    def test_extraction_does_not_overwrite_existing_output_or_follow_output_symlink(self):
        builder = load_script("build-plugin-archive")
        archive = builder.build_archive(self.root, "pstack", self.root / "artifacts").archive
        output = self.root / "output"
        write(output / "keep.txt", "keep")
        with self.assertRaisesRegex(ValueError, "absent or empty"):
            extract_archive(archive, output)
        link = self.root / "linked-output"
        link.symlink_to(output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            extract_archive(archive, link)
        self.assertEqual((output / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
