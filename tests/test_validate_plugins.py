from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

from release_fixtures import commit_all, git, init_repository, isolate_git, write_marketplace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_plugins.py"
SCHEMA = ROOT / "schemas" / "agent-plugins" / "1.0.0" / "plugin.schema.json"
SCHEMA_SHA256 = "0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_plugins", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ValidatePluginsTests(unittest.TestCase):
    def setUp(self) -> None:
        isolate_git(self)
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        schema_target = self.root / self.module.SCHEMA_RELATIVE_PATH
        schema_target.parent.mkdir(parents=True)
        shutil.copy2(SCHEMA, schema_target)
        (self.root / "packages").mkdir()
        self.plugin = self.add_plugin("demo-plugin")
        write_marketplace(self.root)

    def manifest(self, name: str) -> dict:
        return {
            "$schema": self.module.CANONICAL_SCHEMA,
            "name": name,
            "version": "1.0.0",
            "description": f"Portable {name} plugin.",
            "author": {"name": "Test Author", "url": "https://example.com/author"},
            "homepage": "https://example.com/plugins",
            "repository": "https://example.com/repository",
            "license": "MIT",
            "keywords": ["portable", "test"],
        }

    def add_plugin(self, name: str) -> pathlib.Path:
        plugin = self.root / "packages" / name
        skill = plugin / "skills" / name
        skill.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            json.dumps(self.manifest(name), indent=2) + "\n",
            encoding="utf-8",
        )
        (plugin / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        (plugin / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (skill / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: Use when the user needs {name} for a test.\n"
            "license: MIT\n"
            "---\n\n"
            f"# {name}\n",
            encoding="utf-8",
        )
        return plugin

    def write_manifest(self, plugin: pathlib.Path, data: object) -> None:
        (plugin / "plugin.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def repository_errors(self) -> list[str]:
        _roots, errors = self.module.validate_repository(self.root)
        return errors

    def plugin_errors(self, plugin: pathlib.Path | None = None) -> list[str]:
        validator, schema_errors = self.module._load_schema(self.root / self.module.SCHEMA_RELATIVE_PATH)
        self.assertEqual(schema_errors, [])
        assert validator is not None
        return self.module.validate_plugin_root(
            plugin or self.plugin,
            validator,
            report_root=self.root,
        )

    def test_vendored_schema_is_exact_canonical_snapshot(self) -> None:
        digest = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        self.assertEqual(digest, SCHEMA_SHA256)

    def test_valid_repository_and_focused_plugin_pass(self) -> None:
        roots, errors = self.module.validate_repository(self.root)
        self.assertEqual([root.name for root in roots], ["demo-plugin"])
        self.assertEqual(errors, [])
        self.assertEqual(self.plugin_errors(), [])

    def test_cli_accepts_multiple_explicit_plugin_roots(self) -> None:
        second = self.add_plugin("second-plugin")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.module.main([str(self.plugin), str(second)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("validated 2 Agent Plugins v1 package(s)", stdout.getvalue())

    def test_repository_requires_vendored_schema(self) -> None:
        (self.root / self.module.SCHEMA_RELATIVE_PATH).unlink()
        errors = self.repository_errors()
        self.assertTrue(any("missing vendored Agent Plugins schema" in error for error in errors))

    def test_repository_requires_at_least_one_plugin_root(self) -> None:
        shutil.rmtree(self.plugin)
        errors = self.repository_errors()
        self.assertIn("packages: no plugin roots found", errors)

    def test_every_package_directory_must_have_a_manifest(self) -> None:
        empty = self.root / "packages" / "empty-plugin"
        empty.mkdir()
        errors = self.repository_errors()
        self.assertTrue(any("packages/empty-plugin/plugin.json: missing" in error for error in errors))

    def test_plugin_root_cannot_resolve_outside_repository(self) -> None:
        shutil.rmtree(self.plugin)
        external_temp = tempfile.TemporaryDirectory()
        self.addCleanup(external_temp.cleanup)
        external = pathlib.Path(external_temp.name) / "demo-plugin"
        external.mkdir()
        (self.root / "packages" / "demo-plugin").symlink_to(external, target_is_directory=True)
        errors = self.repository_errors()
        self.assertTrue(any("plugin root resolves outside the repository" in error for error in errors))

    def test_root_plugin_and_root_skills_are_forbidden(self) -> None:
        (self.root / "plugin.json").write_text("{}\n", encoding="utf-8")
        (self.root / "skills").mkdir()
        errors = self.repository_errors()
        self.assertTrue(any("plugin.json: root plugin" in error for error in errors))
        self.assertTrue(any("skills: root plugin" in error for error in errors))
        self.assertTrue(any("allowed only at packages/*/plugin.json" in error for error in errors))

    def test_non_v1_root_surfaces_are_forbidden(self) -> None:
        for relative in [".agents", ".opencode", "commands"]:
            (self.root / relative).mkdir()
        (self.root / "skillshare-hub.json").write_text("{}\n", encoding="utf-8")
        (self.root / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")
        errors = self.repository_errors()
        for relative in [".agents", ".opencode", "commands", "skillshare-hub.json"]:
            self.assertTrue(any(error.startswith(relative) for error in errors), relative)
        self.assertIn(
            ".claude-plugin/plugin.json: only marketplace.json is allowed in .claude-plugin",
            errors,
        )

    def test_manifest_must_be_valid_json_object(self) -> None:
        (self.plugin / "plugin.json").write_text("{not json}\n", encoding="utf-8")
        errors = self.plugin_errors()
        self.assertTrue(any("invalid JSON" in error for error in errors))

        self.write_manifest(self.plugin, [])
        errors = self.plugin_errors()
        self.assertTrue(any("is not of type 'object'" in error for error in errors))

    def test_package_readme_and_license_are_required_regular_files(self) -> None:
        (self.plugin / "README.md").unlink()
        (self.plugin / "LICENSE").unlink()
        (self.plugin / "LICENSE").mkdir()
        errors = self.plugin_errors()
        self.assertTrue(any("README.md: missing required package file" in error for error in errors))
        self.assertTrue(
            any("LICENSE: required package file must be a regular file" in error for error in errors)
        )

    def test_schema_rejects_wrong_schema_unknown_field_and_invalid_name(self) -> None:
        cases = [
            ("wrong schema", {"$schema": "https://example.com/schema", "name": "demo-plugin"}),
            (
                "unknown field",
                {**self.manifest("demo-plugin"), "skills": "./skills"},
            ),
            (
                "invalid name",
                {**self.manifest("demo-plugin"), "name": "Demo_Plugin"},
            ),
        ]
        expected = ["was expected", "Additional properties", "does not match"]
        for (label, manifest), needle in zip(cases, expected, strict=True):
            with self.subTest(label=label):
                self.write_manifest(self.plugin, manifest)
                errors = self.plugin_errors()
                self.assertTrue(any(needle in error for error in errors), errors)

    def test_schema_closes_author_and_extensions_values(self) -> None:
        manifest = self.manifest("demo-plugin")
        manifest["author"] = {"name": "Test", "company": "Nope"}
        manifest["extensions"] = {"com.example.client": True}
        self.write_manifest(self.plugin, manifest)
        errors = self.plugin_errors()
        self.assertTrue(any("Additional properties" in error and "company" in error for error in errors))
        self.assertTrue(any("is not of type 'object'" in error for error in errors))

    def test_manifest_name_must_match_package_directory(self) -> None:
        manifest = self.manifest("other-plugin")
        self.write_manifest(self.plugin, manifest)
        errors = self.plugin_errors()
        self.assertTrue(any("must match plugin directory 'demo-plugin'" in error for error in errors))

    def test_release_metadata_must_be_complete_and_semver(self) -> None:
        manifest = self.manifest("demo-plugin")
        manifest.update(
            {
                "version": "2026.8.10.1",
                "description": " ",
                "author": {},
                "homepage": "",
                "repository": "",
                "license": "",
                "keywords": ["duplicate", "duplicate"],
            }
        )
        self.write_manifest(self.plugin, manifest)
        errors = self.plugin_errors()
        for needle in [
            "version must be MAJOR.MINOR.PATCH semantic versioning",
            "description must be a non-empty string",
            "author.name must be a non-empty string",
            "author.url must be a non-empty string",
            "homepage must be a non-empty string",
            "repository must be a non-empty string",
            "license must be a non-empty string",
            "keywords must not contain duplicates",
        ]:
            self.assertTrue(any(needle in error for error in errors), needle)

    def test_versions_must_be_plain_semver(self) -> None:
        manifest = self.manifest("demo-plugin")
        for version in ["0.1.0", "12.3.45"]:
            with self.subTest(version=version):
                manifest["version"] = version
                self.write_manifest(self.plugin, manifest)
                self.assertEqual(self.plugin_errors(), [])
        for version in ["1.0", "01.0.0", "1.0.0-beta", "2026.8.10.1", "２.0.0"]:
            with self.subTest(version=version):
                manifest["version"] = version
                self.write_manifest(self.plugin, manifest)
                errors = self.plugin_errors()
                self.assertTrue(any("semantic versioning" in error for error in errors), errors)

    def test_extension_namespaces_must_be_reverse_domain_style(self) -> None:
        manifest = self.manifest("demo-plugin")
        manifest["extensions"] = {"openai": {}, "com.example.client": {}}
        self.write_manifest(self.plugin, manifest)
        errors = self.plugin_errors()
        self.assertTrue(any("extension namespace 'openai'" in error for error in errors))
        self.assertFalse(any("com.example.client" in error for error in errors))

    def test_skills_must_be_a_contained_directory(self) -> None:
        shutil.rmtree(self.plugin / "skills")
        (self.plugin / "skills").write_text("not a directory\n", encoding="utf-8")
        errors = self.plugin_errors()
        self.assertTrue(any("skills must resolve to a directory" in error for error in errors))

    def test_requires_exactly_one_same_name_immediate_skill(self) -> None:
        extra = self.plugin / "skills" / "extra-skill"
        extra.mkdir()
        (extra / "SKILL.md").write_text(
            "---\nname: extra-skill\ndescription: Use when testing.\n---\n",
            encoding="utf-8",
        )
        errors = self.plugin_errors()
        self.assertTrue(any("expected exactly one immediate skill directory" in error for error in errors))

    def test_official_agent_skills_validation_is_enforced(self) -> None:
        skill_file = self.plugin / "skills" / "demo-plugin" / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: demo-plugin\n"
            "description: Use when testing.\n"
            "user-invocable: true\n"
            "---\n",
            encoding="utf-8",
        )
        errors = self.plugin_errors()
        self.assertTrue(any("Unexpected fields in frontmatter: user-invocable" in error for error in errors))

    def test_skills_directory_cannot_escape_plugin_root(self) -> None:
        outside = self.root / "outside-skills"
        outside_skill = outside / "demo-plugin"
        outside_skill.mkdir(parents=True)
        (outside_skill / "SKILL.md").write_text(
            "---\nname: demo-plugin\ndescription: Use when testing.\n---\n",
            encoding="utf-8",
        )
        shutil.rmtree(self.plugin / "skills")
        (self.plugin / "skills").symlink_to(outside, target_is_directory=True)
        errors = self.plugin_errors()
        self.assertTrue(any("skills directory resolves outside" in error for error in errors))

    def test_skill_file_cannot_escape_plugin_root(self) -> None:
        outside = self.root / "outside-SKILL.md"
        outside.write_text(
            "---\nname: demo-plugin\ndescription: Use when testing.\n---\n",
            encoding="utf-8",
        )
        skill_file = self.plugin / "skills" / "demo-plugin" / "SKILL.md"
        skill_file.unlink()
        skill_file.symlink_to(outside)
        errors = self.plugin_errors()
        self.assertTrue(any("SKILL.md resolves outside" in error for error in errors))

    def test_any_package_symlink_cannot_escape_plugin_root(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        (self.plugin / "resource.txt").symlink_to(outside)
        errors = self.plugin_errors()
        self.assertTrue(any("resource.txt: symlink resolves outside" in error for error in errors))

    def test_nested_skill_and_plugin_manifests_are_rejected(self) -> None:
        references = self.plugin / "skills" / "demo-plugin" / "references"
        references.mkdir()
        (references / "SKILL.md").write_text("nested\n", encoding="utf-8")
        (references / "plugin.json").write_text("{}\n", encoding="utf-8")
        errors = self.plugin_errors()
        self.assertTrue(any("unexpected additional SKILL.md" in error for error in errors))
        self.assertTrue(any("unexpected nested plugin manifest" in error for error in errors))

    def test_mcp_and_non_v1_package_surfaces_are_rejected(self) -> None:
        (self.plugin / "mcp.json").write_text("{}\n", encoding="utf-8")
        (self.plugin / "tool.json").write_text("{}\n", encoding="utf-8")
        (self.plugin / ".claude-plugin").mkdir()
        (self.plugin / "skills" / "demo-plugin" / "agents").mkdir()
        errors = self.plugin_errors()
        for needle in [
            "mcp.json is not allowed",
            "tool.json: surface is not part",
            ".claude-plugin: surface is not part",
            "agents directory",
        ]:
            self.assertTrue(any(needle in error for error in errors), needle)

    def test_forbidden_artifacts_are_reported(self) -> None:
        (self.plugin / ".env").write_text("EXAMPLE=true\n", encoding="utf-8")
        (self.plugin / ".venv").mkdir()
        (self.plugin / "capture.mp4").write_bytes(b"not real media")
        errors = self.plugin_errors()
        self.assertTrue(any(".env: forbidden local artifact file" in error for error in errors))
        self.assertTrue(any(".venv: forbidden local artifact directory" in error for error in errors))
        self.assertTrue(any("capture.mp4: forbidden local artifact file" in error for error in errors))

    def test_repository_hygiene_honors_gitignore_but_focused_validation_is_strict(self) -> None:
        init_repository(self.root)
        (self.root / ".gitignore").write_text(".ruff_cache/\n", encoding="utf-8")
        ignored_cache = self.plugin / ".ruff_cache"
        ignored_cache.mkdir()
        (ignored_cache / "cache.bin").write_bytes(b"cache")

        self.assertEqual(self.repository_errors(), [])
        self.assertTrue(
            any(".ruff_cache: forbidden local artifact directory" in error for error in self.plugin_errors())
        )

    def test_secret_scan_reports_only_the_path(self) -> None:
        secret = "gsk_" + ("s" * 16)
        path = self.plugin / "secret.txt"
        path.write_text(secret + "\n", encoding="utf-8")
        errors = self.plugin_errors()
        joined = "\n".join(errors)
        self.assertIn("secret.txt: possible secret value found", joined)
        self.assertNotIn(secret, joined)

    def release_demo(self) -> str:
        init_repository(self.root)
        sha = commit_all(self.root, "Release demo-plugin 1.0.0")
        git(self.root, "tag", "demo-plugin--v1.0.0")
        return sha

    def demo_entry(self, sha: str, version: str = "1.0.0", **changes: object) -> dict:
        entry = {
            "name": "demo-plugin",
            "description": "Portable demo-plugin plugin.",
            "version": version,
            "source": {
                "source": "git-subdir",
                "url": "https://github.com/heyNag/charms.git",
                "path": "packages/demo-plugin",
                "ref": f"demo-plugin--v{version}",
                "sha": sha,
            },
        }
        entry.update(changes)
        return entry

    def assert_error_containing(self, needle: str, errors: list[str]) -> None:
        self.assertTrue(any(needle in error for error in errors), f"{needle!r} not in {errors}")

    def test_marketplace_manifest_is_required(self) -> None:
        shutil.rmtree(self.root / ".claude-plugin")
        self.assertIn(
            ".claude-plugin/marketplace.json: missing marketplace manifest for Claude Code and "
            "Codex installs",
            self.repository_errors(),
        )

    def test_marketplace_top_level_shape_is_closed(self) -> None:
        path = write_marketplace(self.root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update({"name": "other", "owner": {"name": "Test", "email": "test@example.com"}, "extra": 1})
        del data["metadata"]
        path.write_text(json.dumps(data), encoding="utf-8")
        errors = self.repository_errors()
        for needle in [
            "top-level keys must be exactly",
            "name must be 'charms'",
            "owner must contain only a non-empty name",
            "metadata must contain only a non-empty description",
        ]:
            self.assert_error_containing(needle, errors)

    def test_released_entry_pinned_to_its_tag_passes(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        self.assertEqual(self.repository_errors(), [])

    def test_marketplace_entries_must_be_pinned_git_subdir_sources(self) -> None:
        sha = self.release_demo()
        pinned = self.demo_entry(sha)
        cases = [
            ("relative source", self.demo_entry(sha, source="./packages/demo-plugin"), "source.sha must be"),
            ("abbreviated sha", self.demo_entry(sha[:12]), "source.sha must be"),
            (
                "moving ref",
                self.demo_entry(sha, source={**pinned["source"], "ref": "main"}),
                "source must be",
            ),
            ("client-specific key", {**pinned, "policy": {}}, "entry keys must be exactly"),
            ("unknown plugin", self.demo_entry(sha, name="ghost-plugin"), "'ghost-plugin' is not a plugin"),
            ("duplicate", [pinned, pinned], "sorted by name without duplicates"),
        ]
        for label, entry, needle in cases:
            with self.subTest(label=label):
                write_marketplace(self.root, entry if isinstance(entry, list) else [entry])
                self.assert_error_containing(needle, self.repository_errors())

    def test_marketplace_entry_name_must_be_a_package_string(self) -> None:
        write_marketplace(
            self.root,
            [{"name": ["demo-plugin"], "description": "x", "version": "1.0.0", "source": {}}],
        )
        self.assert_error_containing("['demo-plugin'] is not a plugin under packages/", self.repository_errors())

    def test_marketplace_directory_ignores_gitignored_files(self) -> None:
        init_repository(self.root)
        (self.root / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
        (self.root / ".claude-plugin" / ".DS_Store").write_bytes(b"finder")
        self.assertEqual(self.repository_errors(), [])

        (self.root / ".claude-plugin" / "notes.txt").write_text("not allowed\n", encoding="utf-8")
        self.assertIn(
            ".claude-plugin/notes.txt: only marketplace.json is allowed in .claude-plugin",
            self.repository_errors(),
        )

    def test_marketplace_pins_are_checked_against_release_tags(self) -> None:
        sha = self.release_demo()
        later = commit_all(self.root, "Later change")

        write_marketplace(self.root, [self.demo_entry(later)])
        self.assert_error_containing(f"demo-plugin--v1.0.0 points at {sha}, not {later}", self.repository_errors())

        write_marketplace(self.root, [self.demo_entry(sha, description="Changed.")])
        self.assert_error_containing("version and description must match", self.repository_errors())

        manifest = self.manifest("demo-plugin")
        manifest["version"] = "1.1.0"
        self.write_manifest(self.plugin, manifest)
        write_marketplace(self.root, [self.demo_entry(sha, "1.1.0")])
        self.assert_error_containing(
            "release tag demo-plugin--v1.1.0 is not available locally; run `git fetch --tags`",
            self.repository_errors(),
        )

    def test_package_version_cannot_fall_below_its_release(self) -> None:
        sha = self.release_demo()
        manifest = self.manifest("demo-plugin")
        manifest["version"] = "0.9.0"
        self.write_manifest(self.plugin, manifest)
        write_marketplace(self.root, [self.demo_entry(sha)])
        self.assert_error_containing(
            "released version 1.0.0 is newer than packages/demo-plugin/plugin.json version 0.9.0",
            self.repository_errors(),
        )


if __name__ == "__main__":
    unittest.main()
