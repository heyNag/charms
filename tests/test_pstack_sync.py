"""Input identity, source-update review and failure atomicity for pstack sync."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pstack_sync as sync


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)


def dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sync.json_bytes(value))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "charms"
        self.root.mkdir()
        self.source = self.base / "upstream"
        self.source.mkdir()
        self.cache = self.base / "cache"
        self.integration = self.root / "integrations/pstack"
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        self.git("config", "user.name", "Fixture Maintainer")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.seed_source()
        self.commit = self.commit_source("initial")
        self.lock, self.projection, self.manifests = self.install_inputs(self.commit)

    def git(self, *args):
        return (
            subprocess.check_output(["git", "-C", str(self.source), *args], stderr=subprocess.PIPE)
            .decode()
            .strip()
        )

    def seed_source(self):
        for prefix in ("pstack", "harness/pstack/claude-code"):
            dump(self.source / prefix / "plugin.json", {"name": "pstack", "version": "0.15.43"})
            write(self.source / prefix / "LICENSE", "MIT fixture\n")
            write(self.source / prefix / "skills/a/SKILL.md", "old source\n")
            write(self.source / prefix / "skills/a/run.sh", "#!/bin/sh\nexit 0\n", True)
        write(self.source / "scripts/generate-pstack-harness-trees.mjs", "process.exit(0);\n")
        write(self.source / "harness/pstack/README.md", "Generated fixture\n")
        for path in (
            "cursor-team-kit/LICENSE",
            "cursor-team-kit/skills/deslop/SKILL.md",
            "cursor-team-kit/skills/control-ui/SKILL.md",
            "cursor-team-kit/skills/control-cli/SKILL.md",
        ):
            write(self.source / path, "pinned support\n")

    def commit_source(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def install_inputs(self, commit):
        support = [
            "scripts/generate-pstack-harness-trees.mjs",
            "harness/pstack/README.md",
            "cursor-team-kit/LICENSE",
            "cursor-team-kit/skills/deslop/SKILL.md",
            "cursor-team-kit/skills/control-ui/SKILL.md",
            "cursor-team-kit/skills/control-cli/SKILL.md",
        ]
        manifests = {
            "canonical": sync.git_manifest(self.source, self.source, commit, "pstack"),
            "claude": sync.git_manifest(
                self.source, self.source, commit, "harness/pstack/claude-code"
            ),
            "support": sync.git_manifest(
                self.source, self.source, commit, ".", selected_paths=support
            ),
        }
        inputs = {}
        for name, manifest in manifests.items():
            dump(self.integration / f"source-manifests/{name}.json", manifest)
            inputs[name] = {
                "path": manifest["path"],
                "manifest": f"source-manifests/{name}.json",
                "files": len(manifest["files"]),
            }
            if "git_tree" in manifest:
                inputs[name]["git_tree"] = manifest["git_tree"]
        lock = {
            "schema_version": 1,
            "repository": sync.REPOSITORY,
            "commit": commit,
            "version": "0.15.43",
            "canonical_path": "pstack",
            "canonical_tree": manifests["canonical"]["git_tree"],
            "claude_path": "harness/pstack/claude-code",
            "claude_tree": manifests["claude"]["git_tree"],
            "inputs": inputs,
            "generator": {
                "path": support[0],
                "git_blob": next(
                    r["git_blob"] for r in manifests["support"]["files"] if r["path"] == support[0]
                ),
                "command": ["node", support[0], "--check"],
            },
        }
        projection = {
            "schema_version": 1,
            "package": {"name": "pstack", "version": "2026.11.0"},
            "reviewed_upstream_commit": commit,
            "targets": {
                "claude-code": {
                    "source": "claude",
                    "path": "claude-code",
                    "transform": "exact-copy",
                },
                "codex": {
                    "source": "canonical",
                    "path": "codex",
                    "transform": "canonical-to-codex",
                },
            },
        }
        dump(self.integration / "upstream.lock.json", lock)
        dump(self.integration / "projection.json", projection)
        dump(
            self.integration / "requirements.json",
            {
                "schema_version": 1,
                "upstream_commit": commit,
                "requirements": [{"id": "fixture/one", "source_paths": ["pstack"]}],
            },
        )
        return lock, projection, manifests

    def render(self, root, source, output, lock, projection, manifests, **kwargs):
        output.mkdir()
        shutil.copytree(source / lock["claude_path"], output / "claude-code")
        write(output / "codex/body.txt", (source / "pstack/skills/a/SKILL.md").read_text())
        bundle = {"version": projection["package"]["version"], "targets": {}}
        dump(output / "bundle.json", bundle)
        return bundle

    def generate(self, **kwargs):
        if kwargs.get("projection_override") is not None:
            kwargs.setdefault(
                "expected_projection_sha256",
                sync.sha256((self.integration / "projection.json").read_bytes()),
            )
        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator"),
        ):
            return sync.generate(self.root, source_root=self.source, cache_dir=self.cache, **kwargs)

    def prepare(self, commit):
        destination = self.base / "candidate"
        report = sync.prepare_update(
            self.root, commit, destination, git_dir=self.source, cache_dir=self.cache
        )
        return destination, report

    def accept(self, candidate, commit):
        integration = candidate / "integrations/pstack"
        projection = sync.read_json(integration / "projection.json")
        projection["reviewed_upstream_commit"] = commit
        dump(integration / "projection.json", projection)
        requirements = sync.read_json(integration / "requirements.json")
        requirements["upstream_commit"] = commit
        dump(integration / "requirements.json", requirements)
        review = sync.read_json(candidate / "review.json")
        for decision in review["decisions"]:
            decision.update(
                decision="accept", requirements=["fixture/one"], reason="Fixture semantics reviewed"
            )
        dump(candidate / "review.json", review)

    def cli(self, *args, root=None, env=None):
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(sync.__file__).with_name("sync-pstack.py")),
                "--root",
                str(root or self.root),
                *map(str, args),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, **(env or {})},
        )

    def test_cli_recover_without_journal_reports_exact_idempotent_result(self):
        before = sync.tree_records(self.root)
        report = self.base / "recovery-report.json"
        expected = {"recovered": False, "state": "no transaction"}
        for _ in range(2):
            result = self.cli("--recover", "--report", report)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual(report.read_bytes(), sync.json_bytes(expected))
            self.assertEqual(sync.tree_records(self.root), before)

    def test_cli_recovers_abandoned_journal_without_touching_unrelated_files(self):
        root = self.base / "cli-abandoned"
        self.kill_transaction(root, 2, 5)
        write(root / "operator-note.txt", "preserve unrelated work")
        report = self.base / "abandoned-report.json"
        result = self.cli("--recover", "--report", report, root=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {"recovered": True, "state": "prepared", "paths": 2}
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(report.read_bytes(), sync.json_bytes(expected))
        self.assertEqual((root / "live/0/payload").read_text(), "old")
        self.assertEqual((root / "live/1").read_text(), "old")
        self.assertEqual((root / "operator-note.txt").read_text(), "preserve unrelated work")
        self.assertFalse((root / sync.TRANSACTION_NAME).exists())
        self.assertFalse((root / ".pstack-sync.lock").exists())

    def test_cli_recovery_refuses_to_overwrite_intervening_operator_edits(self):
        root = self.base / "cli-edited"
        self.kill_transaction(root, 2, 5)
        write(root / "live/1", "operator edit")
        before = sync.tree_records(root)
        report = self.base / "existing-report.json"
        write(report, "previous report")
        result = self.cli("--recover", "--report", report, root=root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error:", result.stderr)
        self.assertRegex(result.stderr, "recovery data|changed after interruption")
        self.assertEqual(sync.tree_records(root), before)
        self.assertEqual(report.read_text(), "previous report")

    def test_cli_invalid_operation_options_fail_before_mutation_or_external_tools(self):
        marker = self.base / "external-tool-was-invoked"
        fake_bin = self.base / "trapped-tools"
        for tool in ("git", "node"):
            write(
                fake_bin / tool,
                '#!/bin/sh\nprintf "called\\n" > "$PSTACK_TEST_TOOL_MARKER"\nexit 99\n',
                True,
            )
        env = {"PATH": str(fake_bin), "PSTACK_TEST_TOOL_MARKER": str(marker)}
        candidate = self.base / "must-not-exist"
        report = self.base / "must-not-report.json"
        before = sync.tree_records(self.root)
        incompatible = (
            ("--source", self.source),
            ("--git-dir", self.source),
            ("--check",),
            ("--fetch",),
            ("--candidate-dir", candidate),
            ("--include-support", "new-dependency"),
        )
        cases = (
            [(("--recover", *options), "recover cannot be combined") for options in incompatible]
            + [
                (("--apply-candidate", candidate, *options), "apply-candidate accepts only")
                for options in incompatible
            ]
            + [
                (("--prepare-update", self.commit), "prepare-update needs --candidate-dir"),
                (
                    ("--prepare-update", self.commit, "--candidate-dir", candidate, "--check"),
                    "prepare-update needs --candidate-dir",
                ),
                (
                    (
                        "--prepare-update",
                        self.commit,
                        "--candidate-dir",
                        candidate,
                        "--source",
                        self.source,
                    ),
                    "prepare-update needs --candidate-dir",
                ),
                (("--candidate-dir", candidate), "requires --prepare-update"),
                (("--include-support", "new-dependency"), "requires --prepare-update"),
                (("--recover", "--apply-candidate", candidate), "not allowed with argument"),
            ]
        )
        for options, message in cases:
            with self.subTest(options=options):
                result = self.cli(*options, "--report", report, env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(sync.tree_records(self.root), before)
                self.assertFalse(candidate.exists())
                self.assertFalse(report.exists())
                self.assertFalse(marker.exists())

    def test_cli_prepare_report_records_exact_inputs_and_apply_requires_review(self):
        dependency = "cursor-team-kit/skills/new-dependency/SKILL.md"
        write(self.source / dependency, "new consumed dependency")
        commit = self.commit_source("add dependency")
        before = sync.tree_records(self.root)
        candidate = self.base / "cli-candidate"
        report = self.base / "prepared-report.json"
        result = self.cli(
            "--prepare-update",
            commit,
            "--candidate-dir",
            candidate,
            "--git-dir",
            self.source,
            "--cache-dir",
            self.cache,
            "--include-support",
            dependency,
            "--report",
            report,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = sync.read_json(candidate / "report.json")
        complete = {**prepared, "candidate_dir": str(candidate)}
        self.assertEqual(report.read_bytes(), sync.json_bytes(complete))
        self.assertEqual(
            json.loads(result.stdout),
            {
                key: complete[key]
                for key in (
                    "upstream_commit",
                    "candidate_dir",
                    "old_version",
                    "new_version",
                    "consumed_inputs_unchanged",
                )
            },
        )
        self.assertEqual(prepared["base_commit"], self.commit)
        self.assertEqual(prepared["upstream_commit"], commit)
        self.assertEqual(
            prepared["changes"],
            [
                {
                    "input": "support",
                    "path": dependency,
                    "change": "added",
                    "before": None,
                    "after": {
                        "path": dependency,
                        "sha256": hashlib.sha256(b"new consumed dependency").hexdigest(),
                        "mode": "100644",
                        "size": 23,
                        "git_blob": self.git("rev-parse", f"{commit}:{dependency}"),
                    },
                }
            ],
        )
        lock, _, manifests = sync.integration_records(candidate, check_projection=False)
        sync.verify_inputs(candidate / "source", lock, manifests)
        self.assertEqual(sync.tree_records(self.root), before)
        applied = self.cli(
            "--apply-candidate", candidate, "--cache-dir", self.cache, "--report", report
        )
        self.assertEqual(applied.returncode, 1)
        self.assertIn("has not reviewed", applied.stderr)
        self.assertEqual(sync.tree_records(self.root), before)
        self.assertEqual(report.read_bytes(), sync.json_bytes(complete))

    def test_cli_generation_rejects_source_tamper_without_overwriting_output(self):
        self.generate()
        before = sync.tree_records(self.root)
        write(self.source / "pstack/skills/a/SKILL.md", "unreviewed edit")
        result = self.cli("--source", self.source, "--cache-dir", self.cache, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical upstream input differs", result.stderr)
        self.assertEqual(sync.tree_records(self.root), before)

    def test_exact_inputs_include_modes_and_deleted_paths(self):
        sync.verify_inputs(self.source, self.lock, self.manifests)
        (self.source / "pstack/skills/a/run.sh").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "canonical upstream input differs"):
            sync.verify_inputs(self.source, self.lock, self.manifests)

    def test_source_content_tamper_is_rejected(self):
        write(self.source / "pstack/skills/a/SKILL.md", "changed without reviewed lock")
        with self.assertRaisesRegex(ValueError, "canonical upstream input differs"):
            self.generate()
        self.assertFalse((self.root / "packages/pstack").exists())

    def test_generated_tree_is_replaced_not_overlaid(self):
        self.generate()
        stale = self.root / "packages/pstack/claude-code/deleted-upstream.md"
        write(stale, "must not survive")
        result = self.generate()
        self.assertTrue(result["changed"])
        self.assertFalse(stale.exists())
        self.assertFalse(self.generate(check=True)["changed"])

    def test_check_detects_content_and_modes_without_replacing(self):
        self.generate()
        output = self.root / "packages/pstack/codex/body.txt"
        write(output, "manual edit")
        with self.assertRaisesRegex(ValueError, "generated pstack drift"):
            self.generate(check=True)
        self.assertEqual(output.read_text(), "manual edit")

    def test_retained_inputs_work_offline(self):
        self.generate()
        shutil.rmtree(self.source)
        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator"),
            patch.object(sync, "acquire_git", side_effect=AssertionError("network/store touched")),
        ):
            result = sync.generate(self.root, cache_dir=self.cache, check=True)
        self.assertFalse(result["changed"])

    def test_corrupted_cache_is_not_silently_replaced(self):
        self.generate()
        path = self.cache / "sources" / self.commit / "pstack/LICENSE"
        write(path, "tampered")
        with self.assertRaisesRegex(ValueError, "canonical upstream input differs"):
            self.generate()
        self.assertEqual(path.read_text(), "tampered")

    def test_failed_generation_keeps_old_bundle_and_projection(self):
        self.generate()
        before = sync.tree_records(self.root / "packages/pstack")
        original_projection = (self.integration / "projection.json").read_bytes()
        override = {**self.projection, "package": {"name": "pstack", "version": "2026.11.1"}}
        with (
            patch.object(sync, "render_bundle", side_effect=ValueError("unknown transform anchor")),
            patch.object(sync, "check_upstream_generator"),
        ):
            with self.assertRaisesRegex(ValueError, "unknown transform anchor"):
                sync.generate(
                    self.root,
                    cache_dir=self.cache,
                    projection_override=override,
                    expected_projection_sha256=sync.sha256(original_projection),
                )
        self.assertEqual(sync.tree_records(self.root / "packages/pstack"), before)
        self.assertEqual((self.integration / "projection.json").read_bytes(), original_projection)
        self.assertFalse((self.root / ".pstack-sync.lock").exists())

    def test_projection_bump_and_bundle_move_together(self):
        self.generate()
        override = {**self.projection, "package": {"name": "pstack", "version": "2026.11.1"}}
        self.generate(projection_override=override)
        self.assertEqual(
            sync.read_json(self.integration / "projection.json")["package"]["version"], "2026.11.1"
        )
        self.assertEqual(
            sync.read_json(self.root / "packages/pstack/bundle.json")["version"], "2026.11.1"
        )

    def test_transaction_rolls_back_prior_moves(self):
        first, second = self.root / "first", self.root / "second"
        write(first, "old one")
        write(second, "old two")
        proposed = self.root / "proposed"
        write(proposed, "new one")
        with self.assertRaises(FileNotFoundError):
            sync.replace_transaction(
                self.root, [(proposed, first), (self.root / "missing", second)]
            )
        self.assertEqual(first.read_text(), "old one")
        self.assertEqual(second.read_text(), "old two")

    def test_symlink_and_escape_paths_fail(self):
        for value in ("../escape", "/absolute", "a/../b", "a//b", "a\\b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sync.relative_path(value)
        os.symlink(self.source / "pstack/LICENSE", self.source / "pstack/link")
        with self.assertRaisesRegex(ValueError, "non-regular"):
            sync.verify_inputs(self.source, self.lock, self.manifests)

    def test_cache_cannot_be_inside_repository(self):
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            sync.cache_path(self.root, self.root / ".cache")

    def test_mutex_does_not_erase_another_operation_lock(self):
        path = self.root / ".pstack-sync.lock"
        write(path, "another process")
        with self.assertRaisesRegex(ValueError, "another pstack sync"):
            self.generate()
        self.assertEqual(path.read_text(), "another process")

    def test_prepare_diffs_deletion_and_addition_without_touching_live(self):
        self.generate()
        before = sync.tree_records(self.root)
        (self.source / "pstack/skills/a/run.sh").unlink()
        write(self.source / "pstack/skills/a/new.md", "new behavior")
        commit = self.commit_source("next")
        with patch.object(
            sync, "check_upstream_generator", side_effect=AssertionError("must not execute")
        ):
            candidate, report = self.prepare(commit)
        self.assertEqual(sync.tree_records(self.root), before)
        changes = {(r["input"], r["path"], r["change"]) for r in report["changes"]}
        self.assertIn(("canonical", "skills/a/run.sh", "deleted"), changes)
        self.assertIn(("canonical", "skills/a/new.md", "added"), changes)
        self.assertTrue((candidate / "source/pstack/skills/a/new.md").exists())
        self.assertFalse((candidate / "source/pstack/skills/a/run.sh").exists())

    def test_unreviewed_update_cannot_advance_pin(self):
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        with self.assertRaisesRegex(ValueError, "has not reviewed"):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(
            sync.read_json(self.integration / "upstream.lock.json")["commit"], self.commit
        )

    def test_apply_reviewed_update_replaces_full_tree_and_pins(self):
        self.generate()
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        (self.source / "harness/pstack/claude-code/skills/a/run.sh").unlink()
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator"),
        ):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(sync.read_json(self.integration / "upstream.lock.json")["commit"], commit)
        self.assertEqual((self.root / "packages/pstack/codex/body.txt").read_text(), "new behavior")
        self.assertFalse((self.root / "packages/pstack/claude-code/skills/a/run.sh").exists())
        self.assertEqual(
            sync.read_json(self.integration / "projection.json")["upstream_review"]["base_commit"],
            self.commit,
        )

    def test_missing_decision_blocks_apply_even_with_new_pin(self):
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        review = sync.read_json(candidate / "review.json")
        review["decisions"] = []
        dump(candidate / "review.json", review)
        with self.assertRaisesRegex(ValueError, "does not classify"):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)

    def test_failed_new_generator_does_not_advance_input_or_output(self):
        self.generate()
        before = sync.tree_records(self.root)
        write(self.source / "scripts/generate-pstack-harness-trees.mjs", "process.exit(1);\n")
        commit = self.commit_source("bad generator")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        with patch.object(
            sync, "check_upstream_generator", side_effect=ValueError("generator drift")
        ):
            with self.assertRaisesRegex(ValueError, "generator drift"):
                sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(sync.tree_records(self.root), before)

    def test_changed_candidate_identity_is_rejected(self):
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        report = sync.read_json(candidate / "report.json")
        report["candidate_sha256"] = "0" * 64
        dump(candidate / "report.json", report)
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)

    def test_same_commit_projection_bump_makes_candidate_stale(self):
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        projection = sync.read_json(self.integration / "projection.json")
        projection["package"]["version"] = "2026.11.1"
        dump(self.integration / "projection.json", projection)
        with self.assertRaisesRegex(ValueError, "base metadata/output is stale"):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(
            sync.read_json(self.integration / "projection.json")["package"]["version"], "2026.11.1"
        )

    def test_same_commit_requirement_edit_makes_candidate_stale(self):
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        requirements = sync.read_json(self.integration / "requirements.json")
        requirements["new_note"] = "another accepted design change"
        dump(self.integration / "requirements.json", requirements)
        with self.assertRaisesRegex(ValueError, "base metadata/output is stale"):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(
            sync.read_json(self.integration / "requirements.json")["new_note"],
            "another accepted design change",
        )

    def test_unrelated_upstream_commit_is_a_noop(self):
        before = sync.tree_records(self.root)
        write(self.source / "unrelated/README.md", "different plugin")
        commit = self.commit_source("unrelated upstream change")
        candidate, report = self.prepare(commit)
        self.assertTrue(report["consumed_inputs_unchanged"])
        result = sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertFalse(result["changed"])
        self.assertEqual(result["upstream_commit"], self.commit)
        self.assertEqual(sync.tree_records(self.root), before)

    def test_update_tracks_added_and_removed_consumed_support(self):
        (self.source / "cursor-team-kit/skills/control-cli/SKILL.md").unlink()
        write(
            self.source / "cursor-team-kit/skills/replacement/SKILL.md", "new referenced dependency"
        )
        commit = self.commit_source("replace consumed dependency")
        candidate = self.base / "support-candidate"
        report = sync.prepare_update(
            self.root,
            commit,
            candidate,
            git_dir=self.source,
            cache_dir=self.cache,
            include_support=["cursor-team-kit/skills/replacement/SKILL.md"],
        )
        changes = {(r["input"], r["path"], r["change"]) for r in report["changes"]}
        self.assertIn(
            ("support", "cursor-team-kit/skills/control-cli/SKILL.md", "deleted"), changes
        )
        self.assertIn(("support", "cursor-team-kit/skills/replacement/SKILL.md", "added"), changes)
        review = sync.read_json(candidate / "review.json")
        self.assertEqual(len(review["decisions"]), 2)
        self.assertTrue(all(d["decision"] == "unreviewed" for d in review["decisions"]))
        self.accept(candidate, commit)
        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator"),
        ):
            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        support = sync.read_json(self.integration / "source-manifests/support.json")
        paths = {row["path"] for row in support["files"]}
        self.assertNotIn("cursor-team-kit/skills/control-cli/SKILL.md", paths)
        self.assertIn("cursor-team-kit/skills/replacement/SKILL.md", paths)
        lock = sync.read_json(self.integration / "upstream.lock.json")
        self.assertEqual(lock["commit"], commit)
        self.assertEqual(lock["inputs"]["support"]["files"], len(paths))

    def test_support_additions_must_name_existing_individual_files(self):
        for path in ("cursor-team-kit/skills", "../outside", "missing"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                sync.prepare_update(
                    self.root,
                    self.commit,
                    self.base / "bad-candidate",
                    git_dir=self.source,
                    cache_dir=self.cache,
                    include_support=[path],
                )

    def kill_transaction(self, root, count, stop_after):
        root.mkdir(parents=True)
        replacements = []
        for index in range(count):
            destination = root / "live" / str(index)
            proposal = root / "proposed" / str(index)
            if index == 0:
                write(destination / "payload", "old")
                write(proposal / "payload", "new")
            else:
                write(destination, "old")
                write(proposal, "new")
            replacements.append((str(proposal), str(destination)))
        source = str(Path(sync.__file__).parent)
        program = """
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import pstack_sync as s
root=Path(sys.argv[2]); pairs=[(Path(a),Path(b)) for a,b in json.loads(sys.argv[3])]
stop=int(sys.argv[4]); original=s.os.replace; calls=0
def interrupted(a,b):
    global calls
    original(a,b); calls+=1
    if calls==stop: os.kill(os.getpid(),signal.SIGKILL)
s.os.replace=interrupted
with s.integration_mutex(root): s.replace_transaction(root,pairs)
"""
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                program,
                source,
                str(root),
                json.dumps(replacements),
                str(stop_after),
            ],
            capture_output=True,
        )
        self.assertEqual(result.returncode, -9, result.stderr.decode())
        return replacements

    def test_process_death_at_each_promotion_rename_recovers_whole_state(self):
        # Two paths cover a bump; six cover a larger lock/manifest/package update.
        # Include journal writes and prepromotion staging, not just live renames.
        for count in (2, 6):
            for boundary in range(1, 3 * count + 3):
                with self.subTest(paths=count, rename_boundary=boundary):
                    root = self.base / f"killed-{count}-{boundary}"
                    self.kill_transaction(root, count, boundary)
                    journal = sync.read_json(root / sync.TRANSACTION_NAME / "journal.json")
                    expected = "new" if journal["state"] == "committed" else "old"
                    sync.recover_transaction(root)
                    for index in range(count):
                        path = root / "live" / str(index)
                        if index == 0:
                            path /= "payload"
                        self.assertEqual(path.read_text(), expected)
                    self.assertFalse((root / sync.TRANSACTION_NAME).exists())
                    self.assertFalse((root / ".pstack-sync.lock").exists())

    def test_recovery_refuses_external_edits_before_restoring_any_path(self):
        root = self.base / "interrupted-with-edits"
        self.kill_transaction(root, 2, 5)
        write(root / "live/1", "user edit after interruption")
        before = sync.tree_records(root / "live")
        with self.assertRaisesRegex(ValueError, "recovery data|changed after interruption"):
            sync.recover_transaction(root)
        self.assertEqual(sync.tree_records(root / "live"), before)
        self.assertEqual((root / "live/1").read_text(), "user edit after interruption")

    def test_recovery_does_not_interrupt_a_live_operation(self):
        write(self.root / ".pstack-sync.lock", str(os.getpid()))
        with self.assertRaisesRegex(ValueError, "still running"):
            sync.recover_transaction(self.root)

    def test_recovery_cannot_delete_a_created_but_not_yet_written_active_lock(self):
        original = sync.os.fdopen

        def recover_before_pid_write(*args, **kwargs):
            with self.assertRaisesRegex(ValueError, "recovery is active"):
                sync.recover_transaction(self.root)
            return original(*args, **kwargs)

        with patch.object(sync.os, "fdopen", side_effect=recover_before_pid_write):
            with sync.integration_mutex(self.root):
                self.assertTrue((self.root / ".pstack-sync.lock").exists())

    def test_sync_losing_flock_race_preserves_recovery_lock(self):
        # Pause a real process after O_EXCL creation but before its flock. Recovery
        # can win this window; the losing creator must not unlink recovery's inode.
        program = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import pstack_sync as sync
original = sync.fcntl.flock
def pause_before_flock(fd, operation):
    print("created", flush=True)
    sys.stdin.readline()
    return original(fd, operation)
sync.fcntl.flock = pause_before_flock
try:
    with sync.integration_mutex(Path(sys.argv[2])):
        raise AssertionError("sync entered while recovery held its lock")
except ValueError as error:
    print(str(error), flush=True)
"""
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", program, str(Path(sync.__file__).parent), str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        recovery_fd = None
        try:
            self.assertTrue(
                select.select([child.stdout], [], [], 10)[0], "child did not create lock"
            )
            self.assertEqual(child.stdout.readline().strip(), "created")
            lock = self.root / ".pstack-sync.lock"
            recovery_fd = os.open(lock, os.O_RDWR)
            inode = os.fstat(recovery_fd).st_ino
            sync.fcntl.flock(recovery_fd, sync.fcntl.LOCK_EX | sync.fcntl.LOCK_NB)
            stdout, stderr = child.communicate("continue\n", timeout=10)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("being recovered", stdout)
            self.assertEqual(lock.stat().st_ino, inode)
            with self.assertRaisesRegex(ValueError, "another pstack sync"):
                with sync.integration_mutex(self.root):
                    self.fail("another sync bypassed the active recovery lock")
            os.close(recovery_fd)
            recovery_fd = None
            sync.recover_transaction(self.root)
            with sync.integration_mutex(self.root):
                self.assertTrue(lock.exists())
        finally:
            if recovery_fd is not None:
                os.close(recovery_fd)
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_recovery_preserves_a_replacement_lock_inode(self):
        lock = self.root / ".pstack-sync.lock"
        original = sync.recover_transaction
        replacement_fd = None

        def replace_lock(root, *, internal=False):
            nonlocal replacement_fd
            self.assertTrue(internal)
            lock.unlink()
            replacement_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            sync.fcntl.flock(replacement_fd, sync.fcntl.LOCK_EX | sync.fcntl.LOCK_NB)
            return {"recovered": False}

        try:
            with patch.object(sync, "recover_transaction", side_effect=replace_lock):
                with self.assertRaisesRegex(ValueError, "lock changed during recovery"):
                    original(self.root)
            self.assertEqual(lock.stat().st_ino, os.fstat(replacement_fd).st_ino)
        finally:
            if replacement_fd is not None:
                os.close(replacement_fd)

    def test_candidate_edits_during_apply_cannot_replace_validated_metadata(self):
        self.generate()
        before = sync.tree_records(self.root)
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        cases = (
            ("integrations/pstack/requirements.json", "requirements", "generator"),
            ("review.json", "decisions", "render"),
        )
        for relative, field, phase in cases:
            with self.subTest(input=relative, phase=phase):
                path = candidate / relative
                accepted = path.read_bytes()
                changed = sync.read_json(path)
                changed[field] = []

                def during_generator(*args):
                    if phase == "generator":
                        dump(path, changed)

                def during_render(*args, **kwargs):
                    frozen = kwargs["validation_root"]
                    self.assertEqual(sync.read_json(frozen / relative), json.loads(accepted))
                    if phase == "render":
                        dump(path, changed)
                    return self.render(*args, **kwargs)

                try:
                    with (
                        patch.object(
                            sync, "check_upstream_generator", side_effect=during_generator
                        ),
                        patch.object(sync, "render_bundle", side_effect=during_render),
                    ):
                        with self.assertRaisesRegex(ValueError, "candidate metadata changed"):
                            sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
                    self.assertEqual(sync.tree_records(self.root), before)
                    self.assertEqual(sync.read_json(path), changed)
                finally:
                    path.write_bytes(accepted)

    def test_adapter_edit_during_final_render_prevents_generation_promotion(self):
        adapter = self.integration / "codex/adapter.txt"
        write(adapter, "before")

        def render_and_edit(*args, **kwargs):
            bundle = self.render(*args, **kwargs)
            write(adapter, "maintainer edit during validation")
            return bundle

        with (
            patch.object(sync, "render_bundle", side_effect=render_and_edit),
            patch.object(sync, "check_upstream_generator"),
        ):
            with self.assertRaisesRegex(ValueError, "changed before promotion"):
                sync.generate(self.root, source_root=self.source, cache_dir=self.cache)
        self.assertFalse((self.root / "packages/pstack").exists())
        self.assertEqual(adapter.read_text(), "maintainer edit during validation")

    def test_adapter_can_change_during_review_but_not_during_apply(self):
        self.generate()
        before_bundle = sync.tree_records(self.root / "packages/pstack")
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)
        adapter = self.integration / "codex/adapter.txt"
        write(adapter, "new reviewed transformation")

        def render_and_edit(*args, **kwargs):
            bundle = self.render(*args, **kwargs)
            write(adapter, "later edit during validation")
            return bundle

        with (
            patch.object(sync, "render_bundle", side_effect=render_and_edit),
            patch.object(sync, "check_upstream_generator"),
        ):
            with self.assertRaisesRegex(ValueError, "changed before promotion"):
                sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(sync.tree_records(self.root / "packages/pstack"), before_bundle)
        self.assertEqual(adapter.read_text(), "later edit during validation")
        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator"),
        ):
            result = sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertTrue(result["changed"])
        self.assertEqual(sync.read_json(self.integration / "upstream.lock.json")["commit"], commit)

    def test_edit_during_candidate_generation_is_preserved(self):
        self.generate()
        before_bundle = sync.tree_records(self.root / "packages/pstack")
        write(self.source / "pstack/skills/a/SKILL.md", "new behavior")
        commit = self.commit_source("new")
        candidate, _ = self.prepare(commit)
        self.accept(candidate, commit)

        def concurrent_edit(*args):
            requirements = sync.read_json(self.integration / "requirements.json")
            requirements["concurrent_edit"] = "must survive"
            dump(self.integration / "requirements.json", requirements)

        with (
            patch.object(sync, "render_bundle", side_effect=self.render),
            patch.object(sync, "check_upstream_generator", side_effect=concurrent_edit),
        ):
            with self.assertRaisesRegex(ValueError, "changed before promotion"):
                sync.apply_candidate(self.root, candidate, cache_dir=self.cache)
        self.assertEqual(
            sync.read_json(self.integration / "requirements.json")["concurrent_edit"],
            "must survive",
        )
        self.assertEqual(sync.tree_records(self.root / "packages/pstack"), before_bundle)

    def test_projection_override_requires_same_read_identity_under_mutex(self):
        old = (self.integration / "projection.json").read_bytes()
        newer = {**self.projection, "package": {"name": "pstack", "version": "2026.11.1"}}
        dump(self.integration / "projection.json", newer)
        with self.assertRaisesRegex(ValueError, "projection override is stale"):
            sync.generate(
                self.root,
                source_root=self.source,
                cache_dir=self.cache,
                projection_override=self.projection,
                expected_projection_sha256=sync.sha256(old),
            )
        self.assertEqual(sync.read_json(self.integration / "projection.json"), newer)

    def test_generation_binds_metadata_identity_before_parsing_it(self):
        original = sync.integration_records
        newer = {**self.projection, "package": {"name": "pstack", "version": "2026.11.1"}}

        def edit_after_read(*args, **kwargs):
            records = original(*args, **kwargs)
            dump(self.integration / "projection.json", newer)
            return records

        with patch.object(sync, "integration_records", side_effect=edit_after_read):
            with self.assertRaisesRegex(ValueError, "changed before promotion"):
                self.generate()
        self.assertEqual(sync.read_json(self.integration / "projection.json"), newer)
        self.assertFalse((self.root / "packages/pstack").exists())

    def test_records_digest_is_canonical_and_not_mtime_dependent(self):
        path = self.source / "pstack/LICENSE"
        records = sync.tree_records(self.source / "pstack")
        os.utime(path, (1, 1))
        self.assertEqual(records, sync.tree_records(self.source / "pstack"))
        expected = hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        self.assertEqual(sync.records_digest(records), expected)


if __name__ == "__main__":
    unittest.main()
