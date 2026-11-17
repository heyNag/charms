"""Release behavior across the bundle's two independently versioned host roots."""

import base64
import datetime
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from release_fixtures import (
    commit_all, git, init_repository, isolate_git, write_json, write_marketplace,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pstack_release  # noqa: E402
import plugin_release  # noqa: E402


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def records(path):
    return [
        {"path": p.relative_to(path).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
         "mode": "100755" if p.stat().st_mode & 0o111 else "100644", "size": p.stat().st_size}
        for p in sorted(path.rglob("*")) if p.is_file()
    ]


def digest(value):
    return hashlib.sha256(pstack_release.canonical_bytes(value)).hexdigest()


class PstackReleaseTests(unittest.TestCase):
    def setUp(self):
        isolate_git(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        init_repository(self.root)
        write_marketplace(self.root)
        write_json(self.root / pstack_release.PUBLISHED_PATH, {"schema_version": 1, "release": None})
        self.update = script("update-marketplace.py")
        self.plan = script("plan-plugin-release.py")
        self.bump = script("bump-plugin-version.py")

    def bundle(self, version="2026.11.0", claude="0.15.43", text="Original Claude body.", tag=True):
        package = self.root / "packages/pstack"
        targets = {}
        for host, native_version in [("claude-code", claude), ("codex", version)]:
            target = package / host
            write_json(target / "plugin.json", {
                "name": "pstack", "version": native_version, "description": f"Pstack for {host}.",
            })
            (target / "worker.md").write_text(text if host == "claude-code" else "Codex worker.")
            payload = target / "payload-manifest.json"
            if host == "codex":
                payload.unlink(missing_ok=True)
                files = records(target)
                write_json(payload, {"schema_version": 1, "files": files, "tree_sha256": digest(files)})
            targets[host] = {"path": host, "version": native_version, "tree_sha256": digest(records(target))}
            if host == "codex":
                targets[host]["payload_manifest_sha256"] = hashlib.sha256(payload.read_bytes()).hexdigest()
        write_json(package / "bundle.json", {
            "schema_version": 1, "name": "pstack", "version": version,
            "upstream": {"commit": "a" * 40, "version": claude,
                         "repository": "https://github.com/cursor/plugins",
                         "canonical_tree": "b" * 40, "claude_tree": "c" * 40},
            "adapter": {"sha256": "d" * 64}, "targets": targets,
        })
        write_json(self.root / "integrations/pstack/projection.json", {
            "schema_version": 1, "package": {"name": "pstack", "version": version},
        })
        sha = commit_all(self.root, "Bundle fixture")
        if tag:
            git(self.root, "tag", f"pstack--v{version}")
        return sha

    def promote(self, sha, checksum="f" * 64):
        return self.update.update_marketplace(self.root, "pstack", sha, archive_sha256=checksum)

    def data(self, path):
        return json.loads((self.root / path).read_text())

    def test_plan_and_bump_use_bundle_version_without_rewriting_claude(self):
        sha = self.bundle(tag=False)
        plan = self.plan.plan_release(self.root, "pstack", sha, datetime.date(2026, 11, 17))
        self.assertEqual(plan["version"], "2026.11.0")
        before = (self.root / "packages/pstack/claude-code/plugin.json").read_bytes()
        result = self.bump.update_package(self.root, "pstack", datetime.date(2026, 11, 17), True)
        self.assertEqual(result, "2026.11.0")
        self.assertEqual((self.root / "packages/pstack/claude-code/plugin.json").read_bytes(), before)

    def test_promotion_preserves_native_entries_and_separates_host_versions(self):
        native = plugin_release.marketplace_entry("watch-video", "1.3.2", "Video.", "9" * 40)
        write_marketplace(self.root, [native])
        sha = self.bundle()
        entry, changed = self.promote(sha)
        self.assertTrue(changed)
        self.assertEqual(entry["version"], "0.15.43")
        self.assertEqual(entry["source"]["ref"], "pstack--v2026.11.0")
        published = self.data(pstack_release.PUBLISHED_PATH)["release"]
        self.assertEqual(published["version"], "2026.11.0")
        for host, path in pstack_release.CATALOG_PATHS.items():
            entries = self.data(path)["plugins"]
            self.assertEqual(next(e for e in entries if e["name"] == "watch-video"), native)
            pstack = next(e for e in entries if e["name"] == "pstack")
            self.assertEqual(pstack["source"]["sha"], sha)
            self.assertEqual(pstack["source"]["path"], f"packages/pstack/{host}")
        self.assertEqual(pstack_release.validate_pstack_catalogs(self.root), [])
        before = {p: (self.root / p).read_bytes() for p in pstack_release.TRANSACTION_PATHS}
        self.assertFalse(self.promote(sha)[1])
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_tagless_lookup_reads_published_bundle_not_claude_native_version(self):
        sha = self.bundle()
        self.promote(sha)
        git(self.root, "tag", "-d", "pstack--v2026.11.0")
        self.assertEqual(plugin_release.marketplace_version(self.root, "pstack"), "2026.11.0")
        self.assertEqual(plugin_release.known_releases(self.root, "pstack"), ["2026.11.0"])

    def test_bump_delegates_atomic_projection_and_output_to_sync(self):
        sha = self.bundle()
        self.promote(sha)
        path = self.root / "integrations/pstack/projection.json"
        before = path.read_bytes()
        with mock.patch("pstack_sync.generate", side_effect=RuntimeError("generation failed")) as generate:
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                self.bump.update_package(self.root, "pstack", datetime.date(2026, 11, 17), False)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(generate.call_args.kwargs["projection_override"]["package"]["version"], "2026.11.1")
        self.assertEqual(generate.call_args.kwargs["expected_projection_sha256"],
                         hashlib.sha256(before).hexdigest())

    def test_native_update_keeps_complete_codex_catalog_and_pstack_pin(self):
        sha = self.bundle()
        self.promote(sha)
        previous = pstack_release.expected_pstack_catalog_entries(self.root)
        write_json(self.root / "packages/watch-video/plugin.json", {
            "name": "watch-video", "version": "2026.11.0", "description": "Video.",
        })
        native_sha = commit_all(self.root)
        git(self.root, "tag", "watch-video--v2026.11.0")
        entry, changed = self.update.update_marketplace(self.root, "watch-video", native_sha)
        self.assertTrue(changed)
        for host, path in pstack_release.CATALOG_PATHS.items():
            self.assertEqual(self.data(path)["plugins"], [previous[host], entry])
        self.assertEqual(pstack_release.validate_pstack_catalogs(self.root), [])

    def test_same_claude_bytes_allow_adapter_only_release(self):
        first = self.bundle()
        self.promote(first)
        second = self.bundle("2026.11.1")
        self.assertTrue(self.promote(second)[1])
        self.assertEqual(pstack_release.read_published(self.root)["version"], "2026.11.1")
        with self.assertRaisesRegex(ValueError, "newer or same-version"):
            self.promote(first)

    def test_changed_same_version_claude_and_downgrade_block_promotion(self):
        self.promote(self.bundle())
        changed = self.bundle("2026.11.1", text="Changed despite same upstream version.")
        with self.assertRaisesRegex(ValueError, "version/cache transition is uncertified"):
            self.promote(changed)
        downgrade = self.bundle("2026.11.2", claude="0.15.42")
        with self.assertRaisesRegex(ValueError, "version/cache transition is uncertified"):
            self.promote(downgrade)
        self.assertEqual(pstack_release.read_published(self.root)["version"], "2026.11.0")

    def test_missing_tag_digest_or_bad_committed_target_cannot_promote(self):
        sha = self.bundle(tag=False)
        with self.assertRaisesRegex(ValueError, "verified archive"):
            self.update.update_marketplace(self.root, "pstack", sha)
        with self.assertRaisesRegex(ValueError, "missing or does not point"):
            self.promote(sha)
        (self.root / "packages/pstack/claude-code/worker.md").write_text("Tampered source")
        tampered = commit_all(self.root)
        git(self.root, "tag", "pstack--v2026.11.0")
        with self.assertRaisesRegex(ValueError, "bytes/modes differ"):
            self.promote(tampered)
        self.assertIsNone(pstack_release.read_published(self.root))

    def test_failed_second_catalog_write_restores_all_files(self):
        sha = self.bundle()
        before = {p: (self.root / p).read_bytes() if (self.root / p).exists() else None
                  for p in pstack_release.TRANSACTION_PATHS}
        actual = pstack_release._replace_bytes
        failed = False

        def fail_once(path, data):
            nonlocal failed
            if path == self.root / pstack_release.CODEX_MARKETPLACE_PATH and not failed:
                failed = True
                raise OSError("disk failure")
            actual(path, data)

        with mock.patch.object(pstack_release, "_replace_bytes", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.promote(sha)
        after = {p: (self.root / p).read_bytes() if (self.root / p).exists() else None for p in before}
        self.assertEqual(before, after)
        self.assertTrue(self.promote(sha)[1])

    def interrupted_journal(self):
        relative = str(pstack_release.PUBLISHED_PATH)
        original = (self.root / relative).read_bytes()
        journal = pstack_release._git_state_path(self.root, "charms-catalog-transaction.json")
        write_json(self.root / relative, {"partial": True})
        changed = (self.root / relative).read_bytes()
        write_json(journal, {"schema_version": 2,
            "checkout": pstack_release._checkout_identity(self.root),
            "before": {relative: base64.b64encode(original).decode()},
            "identities": {relative: {
                "before": hashlib.sha256(original).hexdigest(),
                "after": hashlib.sha256(changed).hexdigest(),
            }},
        })
        return journal, original

    def test_next_writer_recovers_an_interrupted_local_transaction(self):
        journal, original = self.interrupted_journal()
        with pstack_release.catalog_transaction(self.root):
            self.assertEqual((self.root / pstack_release.PUBLISHED_PATH).read_bytes(), original)
        self.assertFalse(journal.exists())

    def test_recovery_preserves_operator_edits_and_journal(self):
        journal, _ = self.interrupted_journal()
        changed = self.root / pstack_release.PUBLISHED_PATH
        changed.write_text("operator repaired this record\n")
        with self.assertRaisesRegex(ValueError, "outside the interrupted transaction"):
            with pstack_release.catalog_transaction(self.root):
                self.fail("must not proceed")
        self.assertEqual(changed.read_text(), "operator repaired this record\n")
        self.assertTrue(journal.exists())

    def test_recovery_rejects_different_checkout_before_writing(self):
        journal, _ = self.interrupted_journal()
        changed = self.root / pstack_release.PUBLISHED_PATH
        previous = changed.read_bytes()
        data = json.loads(journal.read_text())
        data["checkout"]["head"] = "b" * 40
        write_json(journal, data)
        with self.assertRaisesRegex(ValueError, "checkout changed"):
            with pstack_release.catalog_transaction(self.root):
                self.fail("must not proceed")
        self.assertEqual(changed.read_bytes(), previous)
        self.assertTrue(journal.exists())

    def test_symlink_catalog_and_lost_native_entries_are_rejected(self):
        self.promote(self.bundle())
        codex = self.root / pstack_release.CODEX_MARKETPLACE_PATH
        data = self.data(pstack_release.CODEX_MARKETPLACE_PATH)
        data["plugins"].append({"name": "surprise", "version": "1.0.0"})
        write_json(codex, data)
        self.assertIn("preserve every native", pstack_release.validate_pstack_catalogs(self.root)[0])
        outside = self.root / "outside.json"
        outside.write_text("untouched")
        codex.unlink()
        codex.symlink_to(outside)
        self.assertIn("symlinks", pstack_release.validate_pstack_catalogs(self.root)[0])
        self.assertEqual(outside.read_text(), "untouched")

    def test_unreleased_bundle_never_appears_in_catalogs(self):
        self.bundle(tag=False)
        self.assertEqual(pstack_release.expected_pstack_catalog_entries(self.root), {})
        self.assertEqual(pstack_release.validate_pstack_catalogs(self.root), [])
        write_marketplace(self.root, [{"name": "pstack", "version": "0.15.43"}])
        self.assertIn("unreleased", pstack_release.validate_pstack_catalogs(self.root)[0])

    def test_codex_catalog_uses_the_shared_metadata_contract(self):
        self.bundle(tag=False)
        valid = self.data(plugin_release.MARKETPLACE_PATH)
        target = self.root / pstack_release.CODEX_MARKETPLACE_PATH
        for bad in ({**valid, "name": "other"},
                    {key: value for key, value in valid.items() if key != "owner"},
                    {**valid, "metadata": {"description": " "}},
                    {**valid, "extra": True}):
            write_json(target, bad)
            self.assertTrue(pstack_release.validate_pstack_catalogs(self.root))
        write_json(target, valid)
        self.assertEqual(pstack_release.validate_pstack_catalogs(self.root), [])

    def test_planning_rejects_native_transition_before_tag_or_publication(self):
        self.promote(self.bundle())
        for version, native in [("2026.11.1", "0.15.43"), ("2026.11.1", "0.15.42")]:
            sha = self.bundle(version=version, claude=native, text="Changed Claude bytes", tag=False)
            with self.assertRaisesRegex(ValueError, "version/cache transition"):
                self.plan.plan_release(self.root, "pstack", sha, datetime.date(2026, 11, 17))
            self.assertIsNone(plugin_release.tag_commit(self.root, "pstack--v2026.11.1"))
        sha = self.bundle(version="2026.11.1", tag=False)
        self.assertEqual(self.plan.plan_release(self.root, "pstack", sha,
                                               datetime.date(2026, 11, 17))["version"], "2026.11.1")


if __name__ == "__main__":
    unittest.main()
