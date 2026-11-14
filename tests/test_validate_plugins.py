from __future__ import annotations

import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from release_fixtures import commit_all, git, init_repository, isolate_git, write_marketplace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_plugins.py"
SCHEMA = ROOT / "schemas" / "agent-plugins" / "1.0.0" / "plugin.schema.json"
SCHEMA_SHA256 = "0a4aad95ce337878ad38802ebf0daa3fde76abe3f65400c86bcbb1ec0b3ab883"
# The watch-video plugin's own record of what a run creates.
PRUNE_RUNS = ROOT / "packages/watch-video/skills/watch-video/scripts/prune_runs.py"
IGNORE_REASON = "Git must ignore every local artifact the validator forbids"
# The fixtures hold versions of March 2027, so the checks are given a day in it.
TODAY = datetime.date(2027, 3, 15)
RUN_HELPER = "; run `python3 scripts/bump-plugin-version.py demo-plugin`"


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
        self.enterContext(mock.patch.object(self.module, "utc_today", return_value=TODAY))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        schema_target = self.root / self.module.SCHEMA_RELATIVE_PATH
        schema_target.parent.mkdir(parents=True)
        shutil.copy2(SCHEMA, schema_target)
        (self.root / "packages").mkdir()
        self.plugin = self.add_plugin("demo-plugin")
        write_marketplace(self.root)
        self.ignore_file = self.root / ".gitignore"
        self.ignore_file.write_text("\n".join(self.module.ignore_rules()) + "\n", encoding="utf-8")

    def manifest(self, name: str) -> dict:
        return {
            "$schema": self.module.CANONICAL_SCHEMA,
            "name": name,
            "version": "2027.3.0",
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
        with (self.root / "README.md").open("a", encoding="utf-8") as readme:
            readme.write(f"| `{name}` | Portable {name} plugin. | `packages/{name}/` |\n")
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

    def test_release_metadata_must_be_complete(self) -> None:
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
            "version must be YEAR.MONTH.RELEASE, three plain numbers such as 2026.11.0",
            "description must be a non-empty string",
            "author.name must be a non-empty string",
            "author.url must be a non-empty string",
            "homepage must be a non-empty string",
            "repository must be a non-empty string",
            "license must be a non-empty string",
            "keywords must not contain duplicates",
        ]:
            self.assertTrue(any(needle in error for error in errors), needle)

    def test_a_plugin_version_must_be_three_plain_numbers(self) -> None:
        manifest = self.manifest("demo-plugin")
        # A plugin checked on its own may be a 1.x release from before CalVer.
        for version in ["2027.3.0", "2026.11.12", "1.3.2"]:
            with self.subTest(version=version):
                manifest["version"] = version
                self.write_manifest(self.plugin, manifest)
                self.assertEqual(self.plugin_errors(), [])
        for version in ["2027.3", "2027.03.0", "2027.3.0-beta", "2026.8.10.1", "２027.3.0"]:
            with self.subTest(version=version):
                manifest["version"] = version
                self.write_manifest(self.plugin, manifest)
                errors = self.plugin_errors()
                self.assertTrue(any("version must be YEAR.MONTH.RELEASE" in error for error in errors), errors)

    def version_errors(self, version: str) -> list[str]:
        manifest = self.manifest("demo-plugin")
        manifest["version"] = version
        self.write_manifest(self.plugin, manifest)
        prefix = "packages/demo-plugin/plugin.json: version "
        return [error for error in self.repository_errors() if error.startswith(prefix)]

    def test_a_plugin_never_released_starts_a_month_at_release_zero(self) -> None:
        # Set this month, or in an earlier one and not released yet.
        for version in ["2027.3.0", "2027.2.0", "2026.11.0"]:
            with self.subTest(version=version):
                self.assertEqual(self.version_errors(version), [])
        cases = [
            ("1.0.0", "version is not YEAR.MONTH.RELEASE, such as 2026.11.0: '1.0.0'"),
            ("2027.3.15", "version 2027.3.15 must be 2027.3.0: the third number counts the releases "
             "the plugin has already made in that month"),
            ("2027.4.0", "version 2027.4.0 names a month after 2027.3, the current month in UTC"),
        ]
        for version, message in cases:
            with self.subTest(version=version):
                self.assertEqual(
                    self.version_errors(version),
                    [f"packages/demo-plugin/plugin.json: {message}{RUN_HELPER}"],
                )

    def test_a_version_waiting_for_release_must_follow_the_latest_release(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        # Between releases the manifest holds the version of the latest one.
        self.assertEqual(self.repository_errors(), [])

        self.assertEqual(self.version_errors("2027.3.1"), [])
        cases = [
            ("2027.3.2", "version 2027.3.2 must be 2027.3.1: the third number counts"),
            ("2027.2.9", "version 2027.2.9 must be greater than the latest release 2027.3.0"),
            ("2027.4.0", "version 2027.4.0 names a month after 2027.3"),
            ("2.0.0", "version is not YEAR.MONTH.RELEASE"),
        ]
        for version, message in cases:
            with self.subTest(version=version):
                errors = self.version_errors(version)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(message, errors[0])
                self.assertTrue(errors[0].endswith(RUN_HELPER), errors[0])

    def test_a_1_x_version_stays_valid_until_the_plugin_is_bumped(self) -> None:
        manifest = self.manifest("demo-plugin")
        manifest["version"] = "1.3.2"
        self.write_manifest(self.plugin, manifest)
        init_repository(self.root)
        sha = commit_all(self.root, "Release demo-plugin 1.3.2")
        for tag in ["demo-plugin--v1.3.1", "demo-plugin--v1.3.2"]:
            git(self.root, "tag", tag)
        write_marketplace(self.root, [self.demo_entry(sha, "1.3.2")])
        self.assertEqual(self.repository_errors(), [])

        # Its next version is CalVer. Another 1.x version is not.
        self.assertEqual(self.version_errors("2027.3.0"), [])
        for version in ["1.3.3", "1.4.0", "2.0.0"]:
            with self.subTest(version=version):
                self.assertEqual(
                    self.version_errors(version),
                    [
                        "packages/demo-plugin/plugin.json: version is not YEAR.MONTH.RELEASE, "
                        f"such as 2026.11.0: {version!r}{RUN_HELPER}"
                    ],
                )
        # A branch cut before the latest release still holds an older one, so this
        # check accepts it. The marketplace check reports a manifest that fell behind.
        self.assertEqual(self.version_errors("1.3.1"), [])
        self.assert_error_containing(
            "released version 1.3.2 is newer than packages/demo-plugin/plugin.json version 1.3.1",
            self.repository_errors(),
        )

    def test_versions_follow_the_marketplace_where_git_has_no_tags_to_read(self) -> None:
        listed = {"name": "demo-plugin", "version": "2027.3.4"}
        write_marketplace(self.root, [listed])

        def check() -> None:
            self.assertEqual(self.version_errors("2027.3.4"), [])
            self.assertEqual(self.version_errors("2027.3.5"), [])
            self.assertEqual(
                self.version_errors("2027.3.6"),
                [
                    "packages/demo-plugin/plugin.json: version 2027.3.6 must be 2027.3.5: the third "
                    f"number counts the releases the plugin has already made in that month{RUN_HELPER}"
                ],
            )

        # The fixture is a plain directory, where Git cannot list tags.
        ceiling = {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}
        with mock.patch.dict(os.environ, ceiling):
            with self.assertRaises(RuntimeError):
                self.module.known_releases(self.root, "demo-plugin")
            check()
        # Git is not installed.
        missing = FileNotFoundError(2, "No such file or directory", "git")
        with mock.patch.object(self.module, "known_releases", side_effect=missing):
            check()
        # A checkout whose tags were not fetched.
        init_repository(self.root)
        self.assertEqual(self.module.known_releases(self.root, "demo-plugin"), ["2027.3.4"])
        check()

    def test_versions_are_not_checked_for_a_plugin_validated_on_its_own(self) -> None:
        # A release archive is checked this way, away from the tags and the marketplace.
        manifest = self.manifest("demo-plugin")
        manifest["version"] = "2027.4.9"
        self.write_manifest(self.plugin, manifest)
        self.assertEqual(self.plugin_errors(), [])
        self.assertNotEqual(self.repository_errors(), [])

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

    def test_skill_instructions_must_stay_within_the_recommended_size(self) -> None:
        skill_file = self.plugin / "skills" / "demo-plugin" / "SKILL.md"
        frontmatter = (
            "---\nname: demo-plugin\n"
            "description: Use when the user needs demo-plugin for a test.\n---\n"
        )

        # The frontmatter is not counted as instructions, and the limits themselves pass.
        at_the_limit = "x" * self.module.SKILL_MAX_BODY_CHARACTERS
        skill_file.write_text(frontmatter + at_the_limit, encoding="utf-8")
        self.assertEqual(self.plugin_errors(), [])
        skill_file.write_text(
            frontmatter + "\n" * (self.module.SKILL_MAX_LINES - 4), encoding="utf-8"
        )
        self.assertEqual(self.plugin_errors(), [])

        skill_file.write_text(frontmatter + at_the_limit + "x", encoding="utf-8")
        self.assertEqual(
            self.plugin_errors(),
            [
                "packages/demo-plugin/skills/demo-plugin/SKILL.md: the instructions are 20001 "
                "characters, over the limit of 20000 (about 5,000 tokens); "
                "move detail into files under references/"
            ],
        )

        skill_file.write_text(
            frontmatter + "\n" * (self.module.SKILL_MAX_LINES - 3), encoding="utf-8"
        )
        self.assertEqual(
            self.plugin_errors(),
            [
                "packages/demo-plugin/skills/demo-plugin/SKILL.md: 501 lines, over the limit of "
                "500; move detail into files under references/"
            ],
        )

    def test_the_plugins_in_this_repository_keep_their_instructions_short(self) -> None:
        for skill_file in sorted(ROOT.glob("packages/*/skills/*/SKILL.md")):
            with self.subTest(skill=skill_file.parent.name):
                self.assertEqual(self.module._validate_skill_size(skill_file, ROOT), [])

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
        (self.plugin / "local.env").write_text("WATCH_VIDEO_LOCAL_API_KEY=private-fixture\n", encoding="utf-8")
        (self.plugin / ".venv").mkdir()
        (self.plugin / "capture.mp4").write_bytes(b"not real media")
        errors = self.plugin_errors()
        self.assertTrue(any(".env: forbidden local artifact file" in error for error in errors))
        self.assertTrue(any("local.env: forbidden local artifact file" in error for error in errors))
        self.assertTrue(any(".venv: forbidden local artifact directory" in error for error in errors))
        self.assertTrue(any("capture.mp4: forbidden local artifact file" in error for error in errors))

    def test_what_a_watch_video_run_creates_is_reported(self) -> None:
        run = self.plugin / "runs" / "20261114-101500-video-0a1b2c3d"
        for folder in ("audio_chunks", "local_analysis/chunks", "media", "videos"):
            (run / folder).mkdir(parents=True)
        (run / "local_analysis" / "chunks" / "chunk-0001.json").write_text("{}\n", encoding="utf-8")
        (run / "media" / "video.info.json").write_text("{}\n", encoding="utf-8")
        files = ("analysis.json", "evidence.json", "native_captions.json", "CUE_0001_00-00-30.JPG")
        for name in files:
            (run / name).write_text("{}\n", encoding="utf-8")
        (run / "notes.txt").write_text("not something a run creates\n", encoding="utf-8")

        where = "packages/demo-plugin/runs/20261114-101500-video-0a1b2c3d"
        self.assertEqual(
            [error for error in self.plugin_errors() if "forbidden local artifact" in error],
            sorted(
                [f"{where}/{name}: forbidden local artifact file" for name in files]
                + [
                    f"{where}/{name}: forbidden local artifact directory"
                    for name in ("audio_chunks", "local_analysis", "media", "videos")
                ]
            ),
        )

    def test_everything_a_watch_video_run_creates_is_forbidden(self) -> None:
        spec = importlib.util.spec_from_file_location("watch_video_prune_runs", PRUNE_RUNS)
        assert spec is not None and spec.loader is not None
        prune_runs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prune_runs)
        self.assertIn("metadata.json", prune_runs.RUN_FILES)
        self.assertIn("frames", prune_runs.RUN_FOLDERS)

        allowed_files = sorted(
            name for name in prune_runs.RUN_FILES if not self.module._is_forbidden_file_name(name)
        )
        self.assertEqual(allowed_files, [], "add these run files to FORBIDDEN_FILE_NAMES")
        allowed_folders = sorted(prune_runs.RUN_FOLDERS - self.module.FORBIDDEN_DIRECTORY_NAMES)
        self.assertEqual(allowed_folders, [], "add these run folders to FORBIDDEN_DIRECTORY_NAMES")

    def test_gitignore_must_hold_a_line_for_every_forbidden_artifact(self) -> None:
        rules = self.module.ignore_rules()
        for rule in (".env", "*.mp4", "cue_*.jpg", "evidence.json", "media/"):
            self.assertIn(rule, rules)

        # Only the whole line counts: not a comment, an exception or a longer path.
        kept = [rule for rule in rules if rule not in {"cue_*.jpg", "media/"}]
        others = ["# media/", "!media/", "docs/media/", "cue_*.jpg.bak", ""]
        self.ignore_file.write_text("\n".join([*kept, *others]) + "\n", encoding="utf-8")
        self.assertEqual(
            self.repository_errors(),
            [
                f'.gitignore: missing the line "cue_*.jpg"; {IGNORE_REASON}',
                f'.gitignore: missing the line "media/"; {IGNORE_REASON}',
            ],
        )

        # Git drops the spaces that end a line.
        self.ignore_file.write_text("".join(f"{rule}  \n" for rule in rules), encoding="utf-8")
        self.assertEqual(self.repository_errors(), [])

        self.ignore_file.unlink()
        self.assertEqual(self.repository_errors(), [f".gitignore: missing; {IGNORE_REASON}"])
        self.assertEqual(self.plugin_errors(), [])

    def test_git_ignores_everything_the_rules_name(self) -> None:
        init_repository(self.root)
        folder = self.root / "work" / "nested"
        lists = self.module
        samples = [
            *(folder / name / "inside.txt" for name in lists.FORBIDDEN_DIRECTORY_NAMES),
            *(folder / name for name in lists.FORBIDDEN_FILE_NAMES),
            *(folder / f"sample{suffix}" for suffix in lists.FORBIDDEN_SUFFIXES),
            *(folder / pattern.replace("*", "0001") for pattern in lists.FORBIDDEN_FILE_PATTERNS),
        ]
        for sample in [*samples, folder / "kept.txt"]:
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_text("sample\n", encoding="utf-8")

        self.assertEqual(len(samples), len(self.module.ignore_rules()))
        self.assertEqual(
            git(self.root, "ls-files", "--others", "--exclude-standard", "--", "work"),
            "work/nested/kept.txt",
        )
        self.assertEqual(self.repository_errors(), [])

    def test_an_artifact_added_by_force_is_still_reported(self) -> None:
        init_repository(self.root)
        info = self.plugin / "media" / "video.info.json"
        info.parent.mkdir()
        info.write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.repository_errors(), [])

        git(self.root, "add", "--force", str(info))
        self.assertEqual(
            self.repository_errors(),
            ["packages/demo-plugin/media: forbidden local artifact directory"],
        )

    def test_readme_must_describe_each_plugin_in_its_manifest_words(self) -> None:
        readme = self.root / "README.md"
        row = "| `demo-plugin` | Portable demo-plugin plugin. | `packages/demo-plugin/` |"
        wanted = (
            "README.md: describe demo-plugin in its manifest's words; "
            "its table row must start: | `demo-plugin` | Portable demo-plugin plugin. |"
        )
        for text in (
            "# Demo\n",
            row.replace("Portable", "A portable") + "\n",
            row.replace("`demo-plugin`", "demo-plugin", 1) + "\n",
            row.replace("`demo-plugin`", "`other-plugin`", 1) + "\n",
            "Text before the row. " + row + "\n",
        ):
            with self.subTest(text=text):
                readme.write_text(text, encoding="utf-8")
                self.assertEqual(self.repository_errors(), [wanted])

        # Cells may be padded, as in a table whose columns are lined up.
        padded = "|  `demo-plugin`   |   Portable demo-plugin plugin.    |\n"
        readme.write_text("| Plugin | Purpose |\n| --- | --- |\n" + padded, encoding="utf-8")
        self.assertEqual(self.repository_errors(), [])

        self.add_plugin("second-plugin")
        readme.write_text(padded, encoding="utf-8")
        self.assertEqual(self.repository_errors(), [wanted.replace("demo-plugin", "second-plugin")])

    def test_readme_row_may_escape_a_pipe_in_the_description(self) -> None:
        manifest = self.manifest("demo-plugin")
        manifest["description"] = "Fetch | search bookmarks."
        self.write_manifest(self.plugin, manifest)
        readme = self.root / "README.md"

        readme.write_text("| `demo-plugin` | Fetch | search bookmarks. |\n", encoding="utf-8")
        self.assertEqual(
            self.repository_errors(),
            [
                "README.md: describe demo-plugin in its manifest's words; "
                "its table row must start: | `demo-plugin` | Fetch \\| search bookmarks. |"
            ],
        )

        readme.write_text("| `demo-plugin` | Fetch \\| search bookmarks. |\n", encoding="utf-8")
        self.assertEqual(self.repository_errors(), [])

    def test_readme_is_required_only_for_the_repository(self) -> None:
        (self.root / "README.md").unlink()
        self.assertEqual(
            self.repository_errors(), ["README.md: missing; its table describes each plugin"]
        )
        self.assertEqual(self.plugin_errors(), [])

    def test_repository_hygiene_honors_gitignore_but_focused_validation_is_strict(self) -> None:
        init_repository(self.root)
        ignored_cache = self.plugin / ".ruff_cache"
        ignored_cache.mkdir()
        (ignored_cache / "cache.bin").write_bytes(b"cache")

        self.assertEqual(self.repository_errors(), [])
        self.assertTrue(
            any(".ruff_cache: forbidden local artifact directory" in error for error in self.plugin_errors())
        )

    def test_secret_scan_reports_only_the_path(self) -> None:
        path = self.plugin / "secret.txt"
        # Built here, so that this file holds nothing the scan would report.
        for secret in ("gsk_" + ("s" * 16), "AIza" + ("s" * 35)):
            with self.subTest(kind=secret[:4]):
                path.write_text(f"KEY={secret}\n", encoding="utf-8")
                errors = self.plugin_errors()
                joined = "\n".join(errors)
                self.assertIn("secret.txt: possible secret value found", joined)
                self.assertNotIn(secret, joined)

        # A Google API key is AIza and 35 more characters. Anything shorter is not one.
        path.write_text("KEY=" + "AIza" + ("s" * 34) + " and more\n", encoding="utf-8")
        self.assertEqual(self.plugin_errors(), [])

    def release_demo(self) -> str:
        init_repository(self.root)
        sha = commit_all(self.root, "Release demo-plugin 2027.3.0")
        git(self.root, "tag", "demo-plugin--v2027.3.0")
        return sha

    def demo_entry(self, sha: str, version: str = "2027.3.0", **changes: object) -> dict:
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
            [{"name": ["demo-plugin"], "description": "x", "version": "2027.3.0", "source": {}}],
        )
        self.assert_error_containing("['demo-plugin'] is not a plugin under packages/", self.repository_errors())

    def test_marketplace_directory_ignores_gitignored_files(self) -> None:
        init_repository(self.root)
        with self.ignore_file.open("a", encoding="utf-8") as rules:
            rules.write(".DS_Store\n")
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
        self.assert_error_containing(f"demo-plugin--v2027.3.0 points at {sha}, not {later}", self.repository_errors())

        write_marketplace(self.root, [self.demo_entry(sha, description="Changed.")])
        self.assert_error_containing("version and description must match", self.repository_errors())

        manifest = self.manifest("demo-plugin")
        manifest["version"] = "2027.3.1"
        self.write_manifest(self.plugin, manifest)
        write_marketplace(self.root, [self.demo_entry(sha, "2027.3.1")])
        self.assert_error_containing(
            "release tag demo-plugin--v2027.3.1 is not available locally; run `git fetch --tags`",
            self.repository_errors(),
        )

    def test_marketplace_alone_is_checked_without_the_development_dependencies(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        # None makes the import fail, as it does where the packages are not installed.
        with mock.patch.dict(sys.modules, {"jsonschema": None, "skills_ref": None}):
            module = load_module()
            self.assertEqual(module.validate_marketplace(self.root), [])

            write_marketplace(self.root, [self.demo_entry(sha, description="Changed.")])
            self.assert_error_containing(
                "version and description must match", module.validate_marketplace(self.root)
            )
            with self.assertRaises(ImportError):
                module.validate_repository(self.root)

    def test_marketplace_alone_reports_what_the_repository_check_reports_for_it(self) -> None:
        sha = self.release_demo()
        pinned = self.demo_entry(sha)
        for entries in (
            [pinned],
            [self.demo_entry(sha[:12])],
            [self.demo_entry(sha, name="ghost-plugin")],
            [pinned, pinned],
            [{**pinned, "policy": {}}],
        ):
            with self.subTest(entries=entries):
                path = write_marketplace(self.root, entries)
                self.assertEqual(self.module.validate_marketplace(self.root), self.repository_errors())

                path.write_text("{not json", encoding="utf-8")
                self.assertEqual(self.module.validate_marketplace(self.root), self.repository_errors())

    def test_marketplace_alone_leaves_the_plugins_to_the_repository_check(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        (self.plugin / "skills" / "demo-plugin" / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")

        self.assertNotEqual(self.repository_errors(), [])
        self.assertEqual(self.module.validate_marketplace(self.root), [])

    def test_marketplace_alone_needs_the_packages_it_lists(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        shutil.rmtree(self.root / "packages")

        self.assertEqual(
            self.module.validate_marketplace(self.root),
            [".claude-plugin/marketplace.json[plugins][0]: 'demo-plugin' is not a plugin under packages/"],
        )

    def test_cli_marketplace_option_checks_this_repository_only(self) -> None:
        sha = self.release_demo()
        write_marketplace(self.root, [self.demo_entry(sha)])
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(self.module, "REPOSITORY_ROOT", self.root):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main(["--marketplace"])
            self.assertEqual((code, stdout.getvalue(), stderr.getvalue()), (0, "validated the marketplace manifest\n", ""))

            write_marketplace(self.root, [self.demo_entry(sha[:12])])
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main(["--marketplace"])
            self.assertEqual((code, stdout.getvalue()), (1, ""))
            self.assertEqual(
                stderr.getvalue(),
                "error: .claude-plugin/marketplace.json[plugins][0]: source.sha must be the full "
                "40-character release commit SHA\n",
            )

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as refused:
                self.module.main(["--marketplace", str(self.plugin)])
            self.assertEqual(refused.exception.code, 2)
            self.assertIn("--marketplace takes no plugin roots", stderr.getvalue())

    def test_package_version_cannot_fall_below_its_release(self) -> None:
        sha = self.release_demo()
        manifest = self.manifest("demo-plugin")
        manifest["version"] = "2027.2.4"
        self.write_manifest(self.plugin, manifest)
        write_marketplace(self.root, [self.demo_entry(sha)])
        self.assert_error_containing(
            "released version 2027.3.0 is newer than packages/demo-plugin/plugin.json version 2027.2.4",
            self.repository_errors(),
        )


if __name__ == "__main__":
    unittest.main()
