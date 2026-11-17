"""Offline behavioral checks for the maintained pstack runtime adapter."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "integrations/pstack/codex/runtime"
sys.path.insert(0, str(RUNTIME))
try:
    import history as history_adapter
    import integrity
    import models
    import profiles
    import pstack_runtime
    import workers
finally:
    sys.path.remove(str(RUNTIME))


class _RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pstack-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "codex"
        self.root.mkdir()
        for name, text in {
            "skills/architect/SKILL.md": "descriptor",
            "skills/architect/instructions.md": "---\nname: architect\n---\nTwo shapes.",
            "skills/poteto-mode/worker.md": "You work for the operator. With no bar stated, preserve the base and pass its own tests.\n",
            "skills/poteto-mode/SKILL.md": "mode descriptor",
            "skills/poteto-mode/instructions.md": "Read current playbook.",
            "agents/poteto-agent.md": "Read the mode.",
            "agents/comment-sicko.md": "Review comments.",
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.reseal()

    def reseal(self):
        records = integrity.tree_records(self.root)
        self.manifest = {
            "schema_version": 1,
            "upstream": {"version": "0.15.43", "commit": "a" * 40},
            "bundle_version": "2026.11.0",
            "files": records,
            "tree_sha256": integrity.digest(integrity.canonical(records)),
        }
        self.write_json(self.root / "payload-manifest.json", self.manifest)
        self.pin = integrity.digest((self.root / "payload-manifest.json").read_bytes())

    def write_json(self, path, value):
        path.write_text(json.dumps(value, indent=2) + "\n")

    def verify(self, **kwargs):
        return integrity.verify_payload(self.root, expected_manifest=self.pin, **kwargs)

    def cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pstack_runtime.main(argv)
        return code, out.getvalue(), err.getvalue()


class RuntimeCase(_RuntimeFixture):
    def test_dangling_default_configuration_never_silently_falls_back(self):
        config = self.base / "config"
        config.mkdir()
        with mock.patch.object(pstack_runtime, "config_home", return_value=config):
            for name in ("config.toml", "models.mdc", "overrides.json"):
                with self.subTest(name=name):
                    path = config / name
                    path.symlink_to(config / "absent")
                    code, out, err = self.cli(["resolve", "architect", "--root", str(self.root)])
                    self.assertEqual(code, 2, (out, err))
                    self.assertEqual(out, "")
                    path.unlink()

    def test_exact_identity_and_direct_internal_resolution(self):
        verified = self.verify(expected_upstream="a" * 40, expected_version="2026.11.0")
        self.assertTrue(verified["origin_verified"])
        self.assertEqual(
            integrity.resolve_skill(self.root, "architect", verified=verified),
            integrity.resolve_skill(self.root, "architect", verified=verified),
        )
        self.assertEqual(
            integrity.verify_payload(self.root)["trust"], "installed_root_consistency_only"
        )

    def test_tamper_extra_deletion_modes_and_pins(self):
        path = self.root / "agents/poteto-agent.md"
        original = path.read_bytes()
        for mutation in [
            lambda: path.write_bytes(b"changed"),
            lambda: path.chmod(0o755),
            lambda: path.unlink(),
        ]:
            with self.subTest(mutation=mutation):
                mutation()
                with self.assertRaises(integrity.RuntimeErrorBase):
                    self.verify()
                path.write_bytes(original)
                path.chmod(0o644)
        extra = self.root / "unexpected"
        extra.write_text("extra")
        with self.assertRaises(integrity.RuntimeErrorBase):
            self.verify()
        extra.unlink()
        for options in [
            {"expected_manifest": "0" * 64},
            {"expected_version": "wrong"},
            {"expected_upstream": "b" * 40},
        ]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.verify_payload(self.root, **options)

    def test_invalid_manifest_records(self):
        original = json.loads(json.dumps(self.manifest))
        mutations = [
            lambda m: m.update(schema_version=2),
            lambda m: m.update(files=[]),
            lambda m: m.update(upstream={}),
            lambda m: m.update(tree_sha256="wrong"),
            lambda m: m["files"].append(m["files"][0]),
            lambda m: m["files"][0].update(mode="120000"),
            lambda m: m["files"][0].update(sha256="bad"),
            lambda m: m["files"][0].update(size=True),
            lambda m: m["files"][0].update(extra=1),
            lambda m: m["files"].reverse(),
            lambda m: m["files"][0].update(path="../escape"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = json.loads(json.dumps(original))
                mutate(value)
                self.write_json(self.root / "payload-manifest.json", value)
                with self.assertRaises(integrity.RuntimeErrorBase):
                    integrity.verify_payload(self.root)
        self.reseal()

    def test_symlinks_and_invalid_paths(self):
        link = self.root / "external"
        link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.tree_records(self.root)
        link.unlink()
        link.symlink_to(self.root / "agents/poteto-agent.md")
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.tree_records(self.root)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.contained(self.root, "external")
        for value in ["", "/absolute", "a//b", "a/../b", "a\\b", "a\n", None]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.safe_relative(value)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.resolve_skill(self.root, "../architect")

    def test_duplicate_json_and_bad_json(self):
        p = self.base / "input.json"
        for data in ['{"a":1,"a":2}', "{bad", "\xff"]:
            p.write_text(data)
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.load_json(p)

    def test_cloud_locator_and_conflicts(self):
        locator = self.base / "installation.json"
        data = {
            "schema_version": 1,
            "surface": "cloud",
            "runtime_root": str(self.root),
            "manifest_sha256": self.pin,
        }
        self.write_json(locator, data)
        self.assertEqual(integrity.resolve_locator(locator, surface="cloud")["root"], self.root)
        common = ["verify", "--surface", "cloud", "--locator", str(locator)]
        self.assertEqual(self.cli(common)[0], 0)
        self.assertEqual(self.cli(["verify", "--root", str(self.root), "--surface", "cloud"])[0], 2)
        self.assertEqual(self.cli(common + ["--expected-manifest", "1" * 64])[0], 2)
        self.assertEqual(self.cli(["verify"])[0], 2)
        for key, value in [
            ("schema_version", 2),
            ("surface", "desktop"),
            ("runtime_root", "relative"),
            ("manifest_sha256", "bad"),
        ]:
            changed = dict(data)
            changed[key] = value
            self.write_json(locator, changed)
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.resolve_locator(locator, surface="cloud")
        self.write_json(locator, data)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.resolve_locator(locator, surface="cloud", supplied_root=self.base)
        inside = self.root / "installation.json"
        self.write_json(inside, data)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.resolve_locator(inside, surface="cloud")

    def override(self):
        directory = self.base / "overrides"
        directory.mkdir()
        body = directory / "architect.md"
        body.write_text("Approved replacement")
        registry = directory / "registry.json"
        data = {
            "schema_version": 1,
            "payload_sha256": self.pin,
            "skills": {
                "architect": {
                    "base_sha256": integrity.digest(
                        (self.root / "skills/architect/instructions.md").read_bytes()
                    ),
                    "body_path": "architect.md",
                    "body_sha256": integrity.digest(body.read_bytes()),
                    "approval_id": "operator-decision-7",
                }
            },
        }
        self.write_json(registry, data)
        return registry, body, data

    def test_approved_override_and_stale_or_modified_rejection(self):
        registry, body, data = self.override()
        selected = integrity.resolve_skill(self.root, "architect", overrides=registry)
        self.assertEqual(selected["instructions"], str(body))
        for key, value in [
            ("base_sha256", "wrong"),
            ("body_sha256", "wrong"),
            ("approval_id", ""),
            ("body_path", "../architect.md"),
        ]:
            original = data["skills"]["architect"][key]
            data["skills"]["architect"][key] = value
            self.write_json(registry, data)
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.resolve_skill(self.root, "architect", overrides=registry)
            data["skills"]["architect"][key] = original
        for key, value in [("schema_version", 2), ("payload_sha256", "wrong"), ("skills", [])]:
            copy = dict(data)
            copy[key] = value
            self.write_json(registry, copy)
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.resolve_skill(self.root, "architect", overrides=registry)
        with self.assertRaises(integrity.RuntimeErrorBase):
            integrity.resolve_skill(self.root, "architect", overrides=self.root / "override.json")

    def test_cli_resolve_models_config_and_no_bytecode(self):
        config = self.base / "config.toml"
        config.write_text(profiles.DEFAULT_CONFIG)
        pref = self.base / "models.mdc"
        pref.write_text("# defaults: 3\n# budget: large (xhigh)\nfeature, refactoring: auto\n")
        args = [
            "resolve",
            "architect",
            "--root",
            str(self.root),
            "--models",
            str(pref),
            "--config",
            str(config),
        ]
        code, out, _ = self.cli(args)
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out)["model_preferences"]["roles"]["feature, refactoring"], ["auto"]
        )
        pref.unlink()
        config.unlink()
        self.assertEqual(json.loads(self.cli(args)[1])["deployment"]["status"], "not_configured")
        result = subprocess.run(
            [sys.executable, str(RUNTIME / "pstack_runtime.py"), "history"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "unavailable")
        self.assertFalse((RUNTIME / "__pycache__").exists())

    def test_ordinary_resolution_keeps_legacy_model_choices(self):
        pref = self.base / "models.mdc"
        original = "# defaults: 1\nfeature, refactoring: grok-4-high\n"
        pref.write_text(original)
        code, out, _ = self.cli(
            ["resolve", "architect", "--root", str(self.root), "--models", str(pref)]
        )
        self.assertEqual(code, 0)
        selected = json.loads(out)["model_preferences"]
        self.assertEqual(selected["roles"]["feature, refactoring"], ["grok-4-high"])
        self.assertEqual(selected["defaults"], 1)
        self.assertEqual(selected["changes"], [])
        self.assertEqual(selected["setup_reminder"]["frequency"], "once per conversation")
        self.assertEqual(pref.read_text(), original)

    def test_default_and_profile_overrides_apply_to_parent_and_worker(self):
        home = self.base / "config-home"
        home.mkdir()
        replacement = home / "mode.md"
        replacement.write_text("Approved revised mode.")
        registry = home / "overrides.json"
        self.write_json(
            registry,
            {
                "schema_version": 1,
                "payload_sha256": self.pin,
                "skills": {
                    "poteto-mode": {
                        "base_sha256": integrity.digest(
                            (self.root / "skills/poteto-mode/instructions.md").read_bytes()
                        ),
                        "body_path": "mode.md",
                        "body_sha256": integrity.digest(replacement.read_bytes()),
                        "approval_id": "approved-mode-change",
                    }
                },
            },
        )
        task = home / "task.txt"
        task.write_text("Fix the displayed price.")
        for explicit_profile in (False, True):
            config = home / "config.toml"
            if explicit_profile:
                config.write_text(profiles.DEFAULT_CONFIG + f'override_registry = "{registry}"\n')
            with mock.patch.object(pstack_runtime, "config_home", return_value=home):
                code, out, err = self.cli(["resolve", "poteto-mode", "--root", str(self.root)])
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["instructions"], str(replacement))
                code, out, err = self.cli(
                    ["worker", "--root", str(self.root), "--task-file", str(task)]
                )
                self.assertEqual(code, 0, err)
                self.assertIn(str(replacement), json.loads(out)["kickoff"])
                self.assertIn(str(registry), json.loads(out)["kickoff"])
        replacement.write_text("unapproved later modification")
        code, _, _ = self.cli(
            [
                "worker",
                "--root",
                str(self.root),
                "--task-file",
                str(task),
                "--overrides",
                str(registry),
            ]
        )
        self.assertEqual(code, 2)

    def test_override_resource_base_and_sibling_dispatch(self):
        helper = self.root / "skills/poteto-mode/playbooks/prototype.md"
        helper.parent.mkdir(parents=True)
        helper.write_text("Exercise the real interface.")
        self.reseal()
        registry, body, data = self.override()
        mode_body = registry.parent / "mode.md"
        mode_body.write_text("Read playbooks/prototype.md and ../architect/SKILL.md.")
        data["skills"]["poteto-mode"] = {
            "base_sha256": integrity.digest(
                (self.root / "skills/poteto-mode/instructions.md").read_bytes()
            ),
            "body_path": "mode.md",
            "body_sha256": integrity.digest(mode_body.read_bytes()),
            "approval_id": "accepted-mode-change",
        }
        self.write_json(registry, data)
        binding = integrity.resolve_skill(self.root, "poteto-mode", overrides=registry)
        self.assertEqual(binding["instructions"], str(mode_body))
        self.assertEqual(binding["resource_root"], str(self.root / "skills/poteto-mode"))
        result = integrity.resolve_resource(
            self.root, "poteto-mode", "playbooks/prototype.md#example", overrides=registry
        )
        self.assertEqual(result["path"], str(helper))
        self.assertEqual(result["fragment"], "example")
        sibling = integrity.resolve_resource(
            self.root, "poteto-mode", "../architect/SKILL.md", overrides=registry
        )
        self.assertEqual(sibling["path"], str(body))
        self.assertEqual(
            integrity.resolve_resource(self.root, "poteto-mode", "#heading", overrides=registry)[
                "path"
            ],
            str(mode_body),
        )
        brief = workers.worker_brief(self.root, "Continue the work.", overrides=registry)
        self.assertIn(str(mode_body), brief)
        self.assertIn(binding["resource_root"], brief)
        self.assertNotIn(
            f"Read the complete effective mode at {self.root}/skills/poteto-mode/instructions.md",
            brief,
        )
        self.assertIn("Do not replace it", brief)
        for relative in [
            "../../../outside",
            "/absolute",
            "https://example.com",
            "bad\\path",
            "bad\npath",
        ]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                integrity.resolve_resource(self.root, "poteto-mode", relative, overrides=registry)
        code, output, _ = self.cli(
            [
                "resource",
                "poteto-mode",
                "../architect/SKILL.md",
                "--root",
                str(self.root),
                "--overrides",
                str(registry),
                "--config",
                str(self.base / "absent"),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["path"], str(body))

    def test_worker_runtime_binding_survives_fresh_and_nested_resolution(self):
        home = self.base / "default-home"
        home.mkdir()
        (home / "config.toml").write_text(profiles.DEFAULT_CONFIG)
        registry, body, _ = self.override()
        config = self.base / "review profile.toml"
        config.write_text(
            'schema_version = 1\nactive_profile = "review"\n[profiles.review]\n'
            f'runtime_root = {json.dumps(str(self.root))}\n'
            f'override_registry = {json.dumps(str(registry))}\n'
        )
        deployment = profiles.load_profile(config)
        task = self.base / "task.txt"
        task.write_text("Investigate without editing files.")
        locator = self.base / "installation locator.json"
        self.write_json(
            locator,
            {
                "schema_version": 1,
                "surface": "all",
                "runtime_root": str(self.root),
                "manifest_sha256": self.pin,
            },
        )
        for surface in ("desktop", "cloud", "cli"):
            with self.subTest(surface=surface), mock.patch.object(
                pstack_runtime, "config_home", return_value=home
            ):
                arguments = [
                    "--root", str(self.root), "--config", str(config),
                    "--surface", surface, "--locator", str(locator),
                ]
                code, out, err = self.cli(
                    ["worker", "--task-file", str(task), *arguments]
                )
                self.assertEqual(code, 0, err)
                brief = json.loads(out)["kickoff"]
                self.assertTrue(brief.startswith(f"Read {self.root}/skills/poteto-mode/worker.md"))
                self.assertIn(deployment["profile_revision"], brief)
                flags = shlex.split(
                    next(line.removeprefix("Runtime arguments: ")
                         for line in brief.splitlines() if line.startswith("Runtime arguments: "))
                )
                self.assertEqual(flags[flags.index("--config") + 1], str(config))
                self.assertEqual(flags[flags.index("--surface") + 1], surface)
                self.assertEqual(flags[flags.index("--locator") + 1], str(locator))
                self.assertEqual(flags[flags.index("--expected-manifest") + 1], self.pin)
                # A fresh worker has a different default configuration; only the
                # emitted arguments preserve the selected profile and approved body.
                code, out, err = self.cli(["resolve", "architect", *flags])
                self.assertEqual(code, 0, err)
                resolved = json.loads(out)
                self.assertEqual(resolved["deployment"]["profile_id"], "review")
                self.assertEqual(resolved["instructions"], str(body))
                self.assertTrue(resolved["verification"]["origin_verified"])
                code, out, err = self.cli(
                    ["resource", "poteto-mode", "../architect/SKILL.md", *flags]
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["path"], str(body))
                code, out, err = self.cli(["worker", "--task-file", str(task), *flags])
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["kickoff"], brief)

    def test_unpinned_worker_does_not_claim_external_provenance(self):
        brief = workers.worker_brief(self.root, "Investigate.")
        self.assertNotIn("--expected-manifest", brief)
        with self.assertRaisesRegex(integrity.RuntimeErrorBase, "installation locator"):
            workers.worker_brief(self.root, "Investigate.", surface="cloud")

    def test_explicit_override_cannot_bypass_invalid_active_profile(self):
        registry, _, _ = self.override()
        config = self.base / "config.toml"
        config.write_text(
            profiles.DEFAULT_CONFIG.replace(
                'active_profile = "default"', 'active_profile = "missing"'
            )
        )
        task = self.base / "task.md"
        task.write_text("Do the authorized work.")
        for command in [
            ["resolve", "architect"],
            ["resource", "architect", "instructions.md"],
            ["worker", "--task-file", str(task)],
        ]:
            code, _, _ = self.cli(
                command
                + ["--root", str(self.root), "--config", str(config), "--overrides", str(registry)]
            )
            self.assertEqual(code, 2)
        config.write_text(profiles.DEFAULT_CONFIG + 'runtime_root = "/another/installation"\n')
        code, _, _ = self.cli(
            ["resolve", "architect", "--root", str(self.root), "--config", str(config)]
        )
        self.assertEqual(code, 2)

    def test_confirmed_model_write_cannot_mutate_plugin_cache(self):
        plan = models.model_plan("", ModelCase().catalog(), "large")
        plan_path = self.base / "accepted.json"
        self.write_json(plan_path, plan)
        destination = self.root / "preferences.mdc"
        code, _, error = self.cli(
            [
                "models",
                "write",
                "--plan",
                str(plan_path),
                "--approved-plan",
                plan["plan_sha256"],
                "--file",
                str(destination),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("outside installed plugin", error)
        self.assertFalse(destination.exists())
        self.assertEqual(
            self.cli(["init", "--config", str(self.root / "configuration.toml")])[0], 2
        )
        self.verify()
        external = self.base / "external.mdc"
        self.assertEqual(
            self.cli(
                [
                    "models",
                    "write",
                    "--plan",
                    str(plan_path),
                    "--approved-plan",
                    plan["plan_sha256"],
                    "--file",
                    str(external),
                ]
            )[0],
            0,
        )
        self.assertTrue(external.exists())

    def test_cli_initialize_and_worker(self):
        path = self.base / "external/config.toml"
        self.assertEqual(self.cli(["init", "--config", str(path)])[0], 0)
        self.assertEqual(self.cli(["init", "--config", str(path)])[0], 2)
        self.assertEqual(self.cli(["profile", "--config", str(path)])[0], 0)
        task = self.base / "task.txt"
        task.write_text("Fix the displayed price.")
        code, out, _ = self.cli(
            ["worker", "--root", str(self.root), "--task-file", str(task), "--policy", "benny"]
        )
        self.assertEqual(code, 0)
        self.assertIn("no PR creation", json.loads(out)["kickoff"])
        self.assertTrue(
            workers.worker_brief(self.root, "Work", role="generic").startswith("Read /")
        )
        self.assertIn(
            "comment-sicko.md", workers.worker_brief(self.root, "Work", role="comment-sicko")
        )
        for kwargs in [{"task": ""}, {"task": "Work", "role": "fake"}]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                workers.worker_brief(self.root, **kwargs)


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.toml"
        self.path.write_text(profiles.DEFAULT_CONFIG)

    def test_default_and_additional_profile_same_resolver(self):
        first = profiles.load_profile(self.path)
        self.path.write_text(
            profiles.DEFAULT_CONFIG
            + '\n[profiles.work]\nruntime_root = "/opt/pstack"\n[profiles.work.bridge]\nendpoint = "https://example.com/pstack"\ncredential_ref = "env:PSTACK_TOKEN"\n'
        )
        self.assertEqual(
            first["profile_revision"], profiles.load_profile(self.path)["profile_revision"]
        )
        work = profiles.load_profile(self.path, selected="work")
        self.assertEqual(work["capability_status"], "unverified")
        with self.assertRaises(integrity.RuntimeErrorBase):
            profiles.load_profile(self.path, selected="missing")

    def test_schema_duplicates_secret_and_endpoint_rejection(self):
        for text in [
            "schema_version=1\nschema_version=1",
            profiles.DEFAULT_CONFIG.replace("schema_version = 1", "schema_version = 2"),
            profiles.DEFAULT_CONFIG.replace("[profiles.default]", '[profiles."bad/name"]'),
        ]:
            self.path.write_text(text)
            with self.assertRaises(integrity.RuntimeErrorBase):
                profiles.load_profile(self.path)
        for value in [
            {"token": "rawsecret"},
            {"runtime_root": "relative"},
            {"providers": []},
            {"providers": {"bad/name": {}}},
            {"bridge": {"endpoint": "http://example.com"}},
            {"bridge": {"endpoint": "https://user:secret@example.com"}},
            {"bridge": {"endpoint": "https://example.com?token=secret"}},
            {"bridge": {"token": "secret"}},
            {"bridge": {"producer": 2}},
            {"credential_refs": {"bad/name": "env:X"}},
            {"credential_refs": {"good": "literal-token"}},
            {"credential_refs": []},
        ]:
            with self.subTest(value=value), self.assertRaises(integrity.RuntimeErrorBase):
                profiles.validate_profile(value)
        profiles.validate_profile(
            {
                "history": {
                    "producer": "original-export",
                    "credential_ref": "secret:project/history",
                },
                "credential_refs": {"bridge": "env:PSTACK_TOKEN"},
            }
        )

    def test_observed_binding_and_change_rejection(self):
        profile = profiles.load_profile(self.path)
        observation = {
            "account_id": "account",
            "workspace_id": "workspace",
            "surface": "cloud",
            "observer": "trusted-host",
            "evidence_id": "event-1",
            "capabilities": {"workers": "available", "history": "unavailable"},
        }

        def bind(obs=observation, auth=lambda _: True):
            return profiles.bind_run(
                profile,
                obs,
                repository="project",
                payload_sha256="a" * 64,
                authorization_scope=["read"],
                authenticate=auth,
            )

        with self.assertRaises(integrity.RuntimeErrorBase):
            bind(auth=lambda _: False)
        binding = bind()
        self.assertEqual(profiles.resume_binding(binding, binding), binding)
        profiles.require_capabilities(binding, ["workers"])
        with self.assertRaises(integrity.RuntimeErrorBase):
            profiles.require_capabilities(binding, ["history"])
        changed = bind({**observation, "account_id": "another"})
        with self.assertRaises(integrity.RuntimeErrorBase):
            profiles.resume_binding(binding, changed)
        binding["profile_id"] = "changed"
        with self.assertRaises(integrity.RuntimeErrorBase):
            profiles.validate_binding(binding)
        for obs in [
            {},
            {**observation, "surface": "other"},
            {**observation, "account_id": ""},
            {**observation, "capabilities": {"x": "true"}},
        ]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                bind(obs)


class ModelCase(unittest.TestCase):
    def catalog(self):
        entries = []
        for family, vendor, fast, maximum in [
            ("claude-opus-5-5", "anthropic", True, "xhigh"),
            ("claude-fable-5-2", "anthropic", False, "xhigh"),
            ("gemini-4-carbon", "google", False, "high"),
        ]:
            for effort in models.EFFORTS[: models.EFFORTS.index(maximum) + 1]:
                slug = f"{family}-{effort}" + ("-fast" if fast else "")
                entries.append(
                    {
                        "slug": slug,
                        "family": family,
                        "vendor": vendor,
                        "effort": effort,
                        "fast": fast,
                        "provider_model": family,
                    }
                )
        return {"schema_version": 1, "observation_id": "discovery-1", "models": entries}

    def test_native_catalog_names_and_vendor_aliases(self):
        cat = self.catalog()
        cat["models"].append(
            {
                "slug": "gpt-6.1",
                "family": "gpt-6.1",
                "vendor": "OpenAI",
                "effort": "xhigh",
                "fast": False,
                "provider_model": "gpt-6.1",
            }
        )
        plan = models.model_plan("# defaults: 3\nfeature, refactoring: gpt-6.1\n", cat, "large")
        self.assertEqual(plan["roles"]["feature, refactoring"], ["gpt-6.1"])
        self.assertFalse(any(row["role"] == "feature, refactoring" for row in plan["needs_choice"]))
        pool = ["claude-opus-5-5-high-fast"]
        for origin in ("anthropic", "Anthropic", " ANTHROPIC ", "Anthropic PBC", "unknown", ""):
            with self.assertRaises(integrity.RuntimeErrorBase):
                models.choose_judge(pool, cat, origin, workflow="show-me-your-work")
        self.assertEqual(
            models.choose_judge(pool, cat, "OpenAI", workflow="show-me-your-work")["vendor"],
            "anthropic",
        )
        self.assertEqual(models.vendor_id("Google DeepMind"), models.vendor_id("google"))

    def test_source_family_recovery_retains_prefix_rules_and_actual_model_policy(self):
        cat = {
            "schema_version": 1,
            "observation_id": "discovery-new-versions",
            "models": [
                {
                    "slug": "observed-sonnet",
                    "family": "claude-sonnet-5-3",
                    "vendor": "anthropic",
                    "effort": "high",
                    "fast": False,
                    "provider_model": "claude-sonnet-5-3",
                },
                {
                    "slug": "observed-gemini",
                    "family": "cursor-gemini-5",
                    "vendor": "google",
                    "effort": "high",
                    "fast": False,
                    "provider_model": "gemini-5",
                },
            ],
        }
        for requested, expected in (
            ("claude-opus-5-5-high-fast", "observed-sonnet"),
            ("cursor-claude-opus-5-5-high-fast", "observed-sonnet"),
            ("gemini-4-carbon-high", "observed-gemini"),
        ):
            with self.subTest(requested=requested):
                result = models.choose_judge([requested], cat, "openai", workflow="arena")
                self.assertEqual(result["model"], expected)
                self.assertTrue(result["fallback"])
                plan = models.model_plan(f"# defaults: 3\nbug-fix: {requested}\n", cat, "large")
                self.assertEqual(plan["roles"]["bug-fix"], [expected])
        # Longest prefix keeps Fable separate from all other Claude models.
        self.assertEqual(
            models.choose_judge(["cursor-claude-fable-5-2-high"], cat, "openai", workflow="arena")[
                "status"
            ],
            "unjudged",
        )
        # The chosen model's actual identity controls its fast requirement,
        # even when a native slug lacks any Cursor family/effort suffix.
        cat["models"][0].update(family="claude-opus-5-5", provider_model="claude-opus-5-5")
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.validate_catalog(cat)
        cat["models"][0]["fast"] = True
        self.assertEqual(models.validate_catalog(cat)["observed-sonnet"]["source_family"], "claude")

    def test_budget_prefers_observed_requested_model_identity_before_family_replacement(self):
        cat = self.catalog()
        cat["models"].append(
            {
                "slug": "claude-sonnet-5-3-medium",
                "family": "claude-sonnet-5-3",
                "vendor": "anthropic",
                "effort": "medium",
                "fast": False,
                "provider_model": "claude-sonnet-5-3",
            }
        )
        plan = models.model_plan("", cat, "small")
        self.assertEqual(plan["roles"]["bug-fix"], ["claude-opus-5-5-medium-fast"])

    def test_catalog_cannot_relabel_recognized_source_identity_or_semantics(self):
        source = {
            "slug": "claude-opus-5-5-xhigh-fast",
            "family": "claude-opus-5-5",
            "vendor": "anthropic",
            "effort": "xhigh",
            "fast": True,
            "provider_model": "claude-opus-5-5",
        }
        for mismatch in (
            {"family": "gpt-6.1", "provider_model": "gpt-6.1", "vendor": "openai", "fast": False},
            {"family": "claude-sonnet-5-3", "provider_model": "claude-sonnet-5-3"},
            {"family": "claude-fable-5-2"},
            {"provider_model": "claude-sonnet-5-3"},
            {"provider_model": "gemini-4-carbon"},
            {"vendor": "openai"},
            {"effort": "high"},
            {"fast": False},
        ):
            with self.subTest(mismatch=mismatch), self.assertRaises(integrity.RuntimeErrorBase):
                models.validate_catalog(
                    {
                        "schema_version": 1,
                        "observation_id": "actual-discovery",
                        "models": [{**source, **mismatch}],
                    }
                )
        # An actual native Claude name may omit source effort suffixes, but
        # its observed mapping still carries the selected model's constraints.
        source["slug"] = "claude-opus-5-5"
        self.assertTrue(
            models.validate_catalog(
                {"schema_version": 1, "observation_id": "actual-discovery", "models": [source]}
            )
        )
        source.update(
            slug="gemini-4-carbon-high",
            family="gemini-4-carbon",
            provider_model="gemini-4-carbon",
            vendor="google",
            effort="xhigh",
            fast=False,
        )
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.validate_catalog(
                {"schema_version": 1, "observation_id": "actual-discovery", "models": [source]}
            )

    def test_migration_known_old_defaults_and_retained_custom_choices(self):
        old = "# budget: unlimited (unlimited)\nfeature, refactoring: grok-old-high\njudgment and prose: grok-custom-high\narena runners: auto, grok-old-high, inherit-parent\narena cross-judge pool: gemini-4-carbon-high, claude-fable-5-2-high, claude-opus-5-5-high-fast\nhardest tasks: old\n"
        value = models.migrate_preferences(models.parse_preferences(old))
        self.assertEqual(value["budget"], "large")
        self.assertEqual(
            value["roles"]["feature, refactoring"], models.DEFAULTS["feature, refactoring"]
        )
        self.assertEqual(value["roles"]["judgment and prose"], ["grok-custom-high"])
        self.assertEqual(
            value["roles"]["arena runners"], ["auto", "claude-opus-5-5-high-fast", "inherit-parent"]
        )
        self.assertEqual(
            value["roles"]["arena cross-judge pool"], models.DEFAULTS["arena cross-judge pool"]
        )
        pair = models.migrate_preferences(
            models.parse_preferences("arena runners: grok-old-high, claude-opus-5-5-high-fast\n")
        )
        self.assertEqual(pair["roles"]["arena runners"], models.DEFAULTS["arena runners"])
        v2 = models.migrate_preferences(
            models.parse_preferences("# defaults: 2\nfeature, refactoring: grok-custom-high\n")
        )
        self.assertEqual(v2["roles"]["feature, refactoring"], ["grok-custom-high"])

    def test_model_budget_alias_cardinality_and_unavailable_choices(self):
        plan = models.model_plan(
            "arena runners: auto, inherit-parent, auto\n", self.catalog(), "medium"
        )
        self.assertEqual(plan["roles"]["arena runners"], ["auto", "inherit-parent", "auto"])
        self.assertEqual(plan["roles"]["feature, refactoring"], ["claude-opus-5-5-high-fast"])
        self.assertEqual(plan["roles"]["swarm workers"], ["claude-opus-5-5-medium-fast"])
        small = models.model_plan("", self.catalog(), "small")
        self.assertEqual(small["roles"]["arena runners"][0], "claude-fable-5-2-low")
        missing = models.model_plan("bug-fix: mystery\n", self.catalog(), "large")
        self.assertEqual(missing["status"], "needs_choice")
        empty = models.model_plan(
            "", {"schema_version": 1, "observation_id": "empty", "models": []}, "large"
        )
        self.assertEqual(empty["status"], "needs_choice")

    def test_parse_invalid_and_catalog_identity(self):
        for text in [
            "---\nno end",
            "# defaults: 4\n",
            "# defaults: 3\n# defaults: 3\n",
            "# budget: large\n# budget: small\n",
            "bug-fix: auto\nbug-fix: auto",
            "bug-fix: auto, auto",
            "arena runners: auto,",
        ]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                models.parse_preferences(text)
        parsed = models.parse_preferences(
            "---\ndescription: config\nalwaysApply: true\n---\n# defaults: 3\n"
        )
        self.assertEqual(parsed["defaults"], 3)
        for mutate in [
            lambda c: c.update(schema_version=2),
            lambda c: c.update(observation_id=""),
            lambda c: c["models"].append(c["models"][0]),
            lambda c: c["models"][0].update(effort="max"),
            lambda c: c["models"][0].update(vendor="proxy"),
            lambda c: c["models"][0].update(fast=False),
            lambda c: c["models"][0].update(provider_model=""),
        ]:
            cat = self.catalog()
            mutate(cat)
            with self.assertRaises(integrity.RuntimeErrorBase):
                models.validate_catalog(cat)

    def test_confirmed_write_and_stale_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.mdc"
            plan = models.model_plan("", self.catalog(), "large")
            with self.assertRaises(integrity.RuntimeErrorBase):
                models.write_preferences(path, plan, approved_plan="wrong")
            result = models.write_preferences(path, plan, approved_plan=plan["plan_sha256"])
            self.assertEqual(result["defaults"], 3)
            self.assertTrue(
                path.read_text().startswith("---\ndescription: pstack per-role model choices")
            )
            self.assertIn("\nalwaysApply: true\n---\n", path.read_text())
            self.assertEqual(len(models.parse_preferences(path.read_text())["roles"]), 9)
            with self.assertRaises(integrity.RuntimeErrorBase):
                models.write_preferences(path, plan, approved_plan=plan["plan_sha256"])

    def test_ordered_judge_recovery_uses_observed_family_and_avoids_rejected(self):
        catalog = self.catalog()
        catalog["models"] = [
            item
            for item in catalog["models"]
            if item["slug"]
            in {"claude-opus-5-5-medium-fast", "claude-opus-5-5-low-fast", "gemini-4-carbon-high"}
        ]
        pool = ["claude-opus-5-5-high-fast", "claude-opus-5-5-high-fast", "gemini-4-carbon-high"]
        result = models.choose_judge(pool, catalog, "OpenAI", workflow="arena")
        self.assertEqual(result["model"], "claude-opus-5-5-medium-fast")
        self.assertTrue(result["fallback"])
        result = models.choose_judge(
            pool, catalog, "openai", workflow="arena", rejected=["claude-opus-5-5-medium-fast"]
        )
        self.assertEqual(result["model"], "claude-opus-5-5-low-fast")
        result = models.choose_judge(
            pool,
            catalog,
            "openai",
            workflow="arena",
            rejected=["claude-opus-5-5-medium-fast", "claude-opus-5-5-low-fast"],
        )
        self.assertEqual(result["model"], "gemini-4-carbon-high")
        self.assertFalse(result["fallback"])
        self.assertEqual(
            models.choose_judge(pool, catalog, "Anthropic, PBC", workflow="arena")["vendor"],
            "google",
        )
        self.assertEqual(
            models.choose_judge(["unknown-native-id"], catalog, "openai", workflow="arena")[
                "status"
            ],
            "unjudged",
        )

    def test_other_vendor_caller_rules_and_fable_exception(self):
        cat = self.catalog()
        pool = ["auto", "claude-fable-5-2-high", "claude-opus-5-5-high-fast"]
        self.assertEqual(
            models.choose_judge(pool, cat, "anthropic", workflow="arena")["status"], "unjudged"
        )
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.choose_judge(pool, cat, "anthropic", workflow="show-me-your-work")
        self.assertEqual(
            models.choose_judge(pool, cat, "openai", workflow="show-me-your-work")["vendor"],
            "anthropic",
        )
        self.assertEqual(
            models.choose_judge(pool, cat, None, workflow="arena")["status"],
            "selected_vendor_unchecked",
        )
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.choose_judge(pool, cat, None, workflow="show-me-your-work")
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.choose_judge(pool, cat, "openai", workflow="shipping")
        failures = [
            {
                "attempt_id": str(i),
                "brief_sha256": "brief",
                "model_family": "claude-opus-5-5",
                "effort": "xhigh",
                "result": "failed",
                "check": "named-check",
                "evidence_id": str(i),
            }
            for i in range(2)
        ]
        self.assertFalse(
            models.permit_fable(
                in_panel=False, explicitly_named=False, brief_sha256="brief", failures=[]
            )
        )
        self.assertTrue(
            models.permit_fable(
                in_panel=False, explicitly_named=False, brief_sha256="brief", failures=failures
            )
        )
        self.assertFalse(
            models.permit_fable(
                in_panel=False, explicitly_named=False, brief_sha256="other", failures=failures
            )
        )
        self.assertTrue(
            models.permit_fable(
                in_panel=False, explicitly_named=True, brief_sha256="brief", failures=[]
            )
        )


class ProjectionCase(_RuntimeFixture):
    def test_projection_preserves_treatment_and_neutral_first_read(self):
        source = self.base / "source"
        source.mkdir()
        (source / "app.py").write_text("print('hello')\n")
        records = integrity.tree_records(source)
        pin = integrity.digest(integrity.canonical(records))
        dest = self.base / "project"
        result = workers.project_trial(
            payload_root=self.root,
            expected_manifest_sha256=self.pin,
            treatment_root=source,
            files=["app.py"],
            organic_request="Make the greeting clear.",
            destination=dest,
            expected_treatment_sha256=pin,
        )
        self.assertEqual((source / "app.py").read_bytes(), (dest / "app.py").read_bytes())
        self.assertTrue(
            result["kickoff"].startswith(
                f"Read {dest}/.instructions/worker.md before anything else."
            )
        )
        self.assertNotIn("tests", (dest / ".instructions/worker.md").read_text())
        self.assertFalse((dest / "payload-manifest.json").exists())
        self.assertEqual(result["parent_payload_sha256"], self.pin)
        self.assertEqual(result["parent_upstream"], self.manifest["upstream"])
        self.assertNotIn(self.pin, result["kickoff"])
        self.assertNotIn(self.pin, (dest / ".instructions/worker.md").read_text())
        with self.assertRaises(integrity.RuntimeErrorBase):
            workers.project_trial(
                payload_root=self.root,
                expected_manifest_sha256=self.pin,
                treatment_root=source,
                files=["app.py"],
                organic_request="Make the greeting clear.",
                destination=dest,
                expected_treatment_sha256=pin,
            )

    def test_no_silent_treatment_rewrite_or_meta_leak(self):
        source = self.base / "source"
        source.mkdir()
        (source / "app.py").write_text("score = 1\n")
        kwargs = dict(
            payload_root=self.root,
            expected_manifest_sha256=self.pin,
            treatment_root=source,
            files=["app.py"],
            organic_request="Fix display.",
            destination=self.base / "project",
            expected_treatment_sha256="wrong",
        )
        with self.assertRaises(integrity.RuntimeErrorBase):
            workers.project_trial(**kwargs)
        (source / "app.py").write_text("value = 1\n")
        with self.assertRaises(integrity.RuntimeErrorBase):
            workers.project_trial(**kwargs)
        for text in ["Run this experiment", "List the principles you applied", "/tmp/eval/app.py"]:
            with self.assertRaises(integrity.RuntimeErrorBase):
                workers.check_blind_text(text, label="input")
        self.assertFalse((self.base / "project").exists())

    def test_projection_requires_pinned_parent_and_rejects_changed_common_worker(self):
        source = self.base / "source"
        source.mkdir()
        (source / "app.py").write_text("print('hello')\n")
        kwargs = dict(
            payload_root=self.root,
            expected_manifest_sha256=self.pin,
            treatment_root=source,
            files=["app.py"],
            organic_request="Improve the greeting.",
            destination=self.base / "project",
            expected_treatment_sha256=integrity.digest(
                integrity.canonical(integrity.tree_records(source))
            ),
        )
        for pin in (None, "0" * 64):
            with self.subTest(pin=pin), self.assertRaises(integrity.RuntimeErrorBase):
                workers.project_trial(**{**kwargs, "expected_manifest_sha256": pin})
        worker = self.root / "skills/poteto-mode/worker.md"
        worker.write_text(worker.read_text() + "An unapproved instruction.\n")
        with self.assertRaises(integrity.RuntimeErrorBase):
            workers.project_trial(**kwargs)
        self.assertFalse((self.base / "project").exists())


class HistoryCase(unittest.TestCase):
    def packet(self):
        return {
            "schema_version": 1,
            "source_kind": "native_cloud",
            "account_id": "a",
            "workspace_id": "w",
            "conversation_id": "c",
            "cutoff_id": "end",
            "run_start_id": "start",
            "producer_id": "qualified-test-fixture",
            "provenance_id": "archive-1",
            "available_before_handoff": True,
            "gaps": [],
            "truncated": False,
            "whole_transcript": True,
            "selected_branch": "main",
            "complete_history_scopes": ["project:last-week"],
            "records": [
                {
                    "id": "start",
                    "previous_id": None,
                    "conversation_id": "c",
                    "original_text": "Do not publish",
                    "source_coordinate": "offset:1",
                },
                {
                    "id": "end",
                    "previous_id": "start",
                    "conversation_id": "c",
                    "original_text": "Original cutoff",
                    "source_coordinate": "offset:2",
                },
            ],
        }

    def inspect(self, packet, **kwargs):
        return history_adapter.inspect_history(
            packet,
            account_id="a",
            workspace_id="w",
            conversation_id="c",
            cutoff_id="end",
            workflow=kwargs.pop("workflow", "reflect"),
            authenticate=kwargs.pop("authenticate", lambda _: True),
            **kwargs,
        )

    def test_original_scope_and_authentication(self):
        packet = self.packet()
        result = self.inspect(packet)
        self.assertEqual(result["status"], "original_chronology_validated")
        self.assertFalse(result["work_verified"])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["record_ids"], ["start", "end"])
        self.assertEqual(
            self.inspect(packet, workflow="recall", required_history_scope="project:last-week")[
                "status"
            ],
            "original_chronology_validated",
        )
        self.assertEqual(
            self.inspect(packet, workflow="automate-me", required_history_scope="all-time")[
                "status"
            ],
            "partial",
        )
        with self.assertRaises(integrity.RuntimeErrorBase):
            self.inspect(packet, authenticate=lambda _: False)
        for key, value in [
            ("source_kind", "managed_api"),
            ("account_id", "other"),
            ("producer_id", ""),
            ("available_before_handoff", False),
            ("records", []),
        ]:
            copy = self.packet()
            copy[key] = value
            with self.assertRaises(integrity.RuntimeErrorBase):
                self.inspect(copy)

    def test_missing_original_regions_stay_partial(self):
        for key, value in [
            ("whole_transcript", False),
            ("gaps", ["prefix"]),
            ("truncated", True),
            ("run_start_id", "uncaptured"),
            ("selected_branch", None),
            ("unresolved_revisions", ["v2"]),
        ]:
            packet = self.packet()
            packet[key] = value
            self.assertEqual(self.inspect(packet)["status"], "partial")
        packet = self.packet()
        packet["records"].pop(0)
        self.assertEqual(self.inspect(packet)["status"], "partial")
        packet = self.packet()
        packet["records"][0]["previous_id"] = "end"
        with self.assertRaises(integrity.RuntimeErrorBase):
            self.inspect(packet)
        for mutate in [
            lambda p: p["records"].append(p["records"][0]),
            lambda p: p["records"][0].update(id=""),
            lambda p: p["records"][0].update(original_text=None),
            lambda p: p["records"][0].update(source_coordinate=""),
        ]:
            packet = self.packet()
            mutate(packet)
            with self.assertRaises(integrity.RuntimeErrorBase):
                self.inspect(packet)
        with self.assertRaises(integrity.RuntimeErrorBase):
            self.inspect(self.packet(), workflow="unknown")


if __name__ == "__main__":
    unittest.main()
