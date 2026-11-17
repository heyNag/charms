import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pstack_transform as transform  # noqa: E402


COMMIT = "2f87c854fe3e2fcda44ca86b46ede35aad3c46b7"
CONTEXT = {"upstream_commit": COMMIT, "upstream_version": "0.15.43",
           "bundle_version": "2026.11.0"}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "upstream"
        self.pstack = self.source / "pstack"
        self.adapter = self.root / "adapter"
        self.output = self.root / "output"
        self.pstack.mkdir(parents=True)
        self.adapter.mkdir()
        self.write_source("plugin.json", json.dumps({
            "name": "pstack", "version": "0.15.43", "description": "Test suite",
            "author": {"name": "Original author"}, "license": "MIT", "keywords": ["pstack"],
        }))
        self.write_source(".cursor-plugin/plugin.json", '{"name":"pstack"}')
        self.write_source("README.md", "# Canonical guide\n")
        self.write_source("LICENSE", "Upstream license\n")
        self.write_source("skills/demo/SKILL.md", "---\nname: demo\ndescription: >-\n"
                          "  The operative rule\n  includes this description.\n"
                          "disable-model-invocation: true\nicon: crown\n---\n\n# Demo\n"
                          "Read references/proof.md.\n")
        self.write_source("skills/demo/references/proof.md", "# Proof\n")
        self.write_source("skills/setup-pstack/SKILL.md", "---\nname: setup-pstack\n"
                          "description: Configure the roles.\n---\n\n# Setup\n")
        self.write_source("skills/demo/scripts/run", "#!/bin/sh\nexit 0\n").chmod(0o755)
        self.write_source("automations/benny/skills/internal/SKILL.md", "Dormant body\n")
        dep = self.source / "cursor-team-kit/LICENSE"
        dep.parent.mkdir()
        dep.write_text("Dependency license\n")
        self.rules = {
            "source_commit": COMMIT,
            "registered_skills": ["demo", "setup-pstack"], "files": {},
            "dependencies": [{"source": "cursor-team-kit/LICENSE",
                              "output": "dependencies/cursor-team-kit/LICENSE",
                              "sha256": hashlib.sha256(dep.read_bytes()).hexdigest()}],
        }
        templates = ROOT / "integrations/pstack/codex/templates"
        shutil.copytree(templates, self.adapter / "templates")
        (self.adapter / "adapter.md").write_text("# Actual binding\n")
        (self.adapter / "compatibility.json").write_text('{"certified":false}\n')
        (self.adapter / "runtime").mkdir()
        (self.adapter / "runtime/pstack_runtime.py").write_text("# Runtime fixture\n")
        self.save_rules()

    def write_source(self, name, text):
        path = self.pstack / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def save_rules(self):
        directory = self.adapter / "transforms"
        directory.mkdir(exist_ok=True)
        (directory / "rules.json").write_text(json.dumps(self.rules))

    def project(self, **context):
        return transform.project_codex(self.source, self.output, self.adapter,
                                       {**CONTEXT, **context})

    def test_projection_preserves_source_and_operational_frontmatter(self):
        source_before = {str(p): p.read_bytes() for p in self.pstack.rglob("*") if p.is_file()}
        report = self.project()
        self.assertEqual(source_before,
                         {str(p): p.read_bytes() for p in self.pstack.rglob("*") if p.is_file()})
        operative = (self.output / "skills/demo/instructions.md").read_text()
        self.assertIn("icon: crown", operative)
        self.assertIn("includes this description.", operative)
        self.assertIn("Read references/proof.md.", operative)
        descriptor = (self.output / "skills/demo/SKILL.md").read_text()
        self.assertIn("The operative rule includes this description.", descriptor)
        self.assertNotIn("icon: crown", descriptor)
        self.assertIn(f"--expected-upstream {COMMIT}", descriptor)
        self.assertIn("--expected-version 2026.11.0", descriptor)
        self.assertIn("--locator", descriptor)
        self.assertIn("--surface cloud", descriptor)
        self.assertNotIn("payload_sha256", descriptor)
        self.assertEqual(report["runtime_certification"], "not_performed")

    def test_policy_and_dormancy_survive_recursive_discovery(self):
        self.project()
        entries = sorted(p.relative_to(self.output).as_posix()
                         for p in self.output.rglob("SKILL.md"))
        self.assertEqual(entries, ["skills/demo/SKILL.md", "skills/setup-pstack/SKILL.md"])
        self.assertEqual((self.output / "skills/demo/agents/openai.yaml").read_text(),
                         "policy:\n  allow_implicit_invocation: false\n")
        self.assertIn("true", (self.output / "skills/setup-pstack/agents/openai.yaml").read_text())
        self.assertEqual((self.output / "automations/benny/skills/internal/instructions.md")
                         .read_text(), "Dormant body\n")

    def test_manifest_scope_attribution_support_modes_and_dependency_notice(self):
        self.project()
        manifest = json.loads((self.output / "plugin.json").read_text())
        self.assertEqual(manifest["version"], "2026.11.0")
        self.assertEqual(manifest["author"], {"name": "Original author"})
        native = json.loads((self.output / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(native["skills"], "./skills")
        self.assertNotIn("agents", native)
        self.assertFalse((self.output / ".cursor-plugin").exists())
        self.assertEqual((self.output / "skills/demo/scripts/run").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.output / "dependencies/cursor-team-kit/LICENSE").read_text(),
                         "Dependency license\n")
        self.assertEqual((self.output / "adapters/codex/runtime/pstack_runtime.py").read_bytes(),
                         (self.adapter / "runtime/pstack_runtime.py").read_bytes())

    def test_direct_and_internal_index_use_one_operative_identity(self):
        self.project()
        index = json.loads((self.output / "skills/index.json").read_text())["skills"]
        row = index["demo"]
        self.assertEqual(row["instructions"], "skills/demo/instructions.md")
        original = self.pstack / "skills/demo/SKILL.md"
        self.assertEqual(row["source_sha256"], hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertFalse(row["allow_implicit_invocation"])

    def test_reviewed_edits_require_exact_source_hash_and_anchor_count(self):
        rel = "skills/demo/references/proof.md"
        self.rules["files"][rel] = {
            "source_sha256": hashlib.sha256((self.pstack / rel).read_bytes()).hexdigest(),
            "edits": [{"id": "proof-route", "before": "# Proof", "after": "# Bound proof", "count": 1}],
        }
        self.save_rules()
        report = self.project()
        self.assertEqual((self.output / rel).read_text(), "# Bound proof\n")
        self.assertEqual(next(r for r in report["source_mapping"] if r["source"] == f"pstack/{rel}")
                         ["transforms"], ["proof-route"])
        shutil.rmtree(self.output)
        self.write_source(rel, "# Proof changed upstream\n")
        with self.assertRaisesRegex(ValueError, "unreviewed upstream transform"):
            self.project()
        shutil.rmtree(self.output)
        self.write_source(rel, "# Proof\n")
        self.rules["files"][rel]["edits"][0]["count"] = 2
        self.save_rules()
        with self.assertRaisesRegex(ValueError, "changed transform anchor"):
            self.project()

    def test_new_pin_new_skill_and_changed_policy_need_review(self):
        with self.assertRaisesRegex(ValueError, "reviewed for this upstream"):
            self.project(upstream_commit="a" * 40)
        self.write_source("skills/new/SKILL.md", "---\nname: new\ndescription: New.\n---\n")
        with self.assertRaisesRegex(ValueError, "skill identities changed"):
            self.project()
        shutil.rmtree(self.pstack / "skills/new")
        path = self.pstack / "skills/demo/SKILL.md"
        path.write_text(path.read_text().replace("disable-model-invocation: true\n", ""))
        with self.assertRaisesRegex(ValueError, "invocation policy"):
            self.project()

    def test_no_overlay_no_in_place_generation_and_no_symlink_inputs(self):
        self.output.mkdir()
        (self.output / "stale.md").write_text("Never preserve upstream deletions.\n")
        with self.assertRaisesRegex(ValueError, "empty output"):
            self.project()
        self.assertTrue((self.output / "stale.md").is_file())
        with self.assertRaisesRegex(ValueError, "outside its immutable inputs"):
            transform.project_codex(self.source, self.source / "new", self.adapter, CONTEXT)
        shutil.rmtree(self.output)
        os.symlink(self.root / "outside", self.pstack / "unsafe")
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.project()

    def test_missing_runtime_or_tampered_dependency_cannot_be_distributed(self):
        dependency = self.source / "cursor-team-kit/LICENSE"
        dependency.write_text("Changed upstream\n")
        with self.assertRaisesRegex(ValueError, "dependency changed"):
            self.project()
        shutil.rmtree(self.output)
        dependency.write_text("Dependency license\n")
        (self.adapter / "runtime/pstack_runtime.py").unlink()
        with self.assertRaisesRegex(ValueError, "complete runtime"):
            self.project()

    def test_deterministic_generation(self):
        self.project()
        before = {str(p.relative_to(self.output)): p.read_bytes()
                  for p in self.output.rglob("*") if p.is_file()}
        shutil.rmtree(self.output)
        self.project()
        after = {str(p.relative_to(self.output)): p.read_bytes()
                 for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_interpreter_caches_are_not_adapter_inputs_or_payload_files(self):
        cache = self.adapter / "runtime/__pycache__"
        cache.mkdir()
        (cache / "pstack_runtime.cpython-311.pyc").write_bytes(b"local interpreter cache")
        self.project()
        self.assertFalse((self.output / "adapters/codex/runtime/__pycache__").exists())


class ReviewedRuleTests(unittest.TestCase):
    def test_effective_body_resource_and_reflect_activation_contract(self):
        adapter = ROOT / "integrations/pstack/codex"
        rules = json.loads((adapter / "transforms/rules.json").read_text())
        for relative, expected in {
            "skills/reflect/SKILL.md": ["overrides.json", "base_sha256", "body_sha256",
                                        "approval_id", "same-identity", "resource_root",
                                        "does not activate an override"],
            "skills/poteto-mode/SKILL.md": ["effective instructions path", "resource_root",
                                            "selected override registry"],
            "agents/poteto-agent.md": ["effective operative instructions", "resource_root",
                                      "do not reread the descriptor or pinned base"],
        }.items():
            with self.subTest(relative=relative):
                source = ROOT / "packages/pstack/claude-code" / relative
                # Test-only recovery of these exact canonical fixtures: upstream
                # inserts its own Claude paragraph. The canonical SHA guard below
                # must still pass after removing that one known generated notice.
                data = source.read_bytes().replace(
                    b"In Claude Code, read [the Claude Code adapter]"
                    b"(../../docs/harness/claude-code.md) once per session before you follow this skill. "
                    b"It maps the Cursor names in pstack skills to Claude Code.\n\n", b"")
                body, _ = transform.apply_edits(relative, data,
                                                rules["files"][relative])
                for value in expected:
                    self.assertIn(value, body.decode())

    def test_worktree_audit_keeps_main_checkout_with_spaces_out_of_candidates(self):
        relative = "skills/poteto-mode/scripts/worktree-audit.sh"
        rules = json.loads((ROOT / "integrations/pstack/codex/transforms/rules.json").read_text())
        data, _ = transform.apply_edits(relative,
            (ROOT / "packages/pstack/claude-code" / relative).read_bytes(), rules["files"][relative])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main, linked, bin_dir = root / "main checkout", root / "linked checkout", root / "bin"
            for path in (main, linked, bin_dir):
                path.mkdir()
            script = root / "audit.sh"
            script.write_bytes(data)
            git = bin_dir / "git"
            git.write_text(f"#!{sys.executable}\n" + '''import os, sys
args = sys.argv[1:]
if args[:1] == ["-C"]:
    args = args[2:]
if args[:2] == ["worktree", "list"]:
    print("worktree " + os.environ["TEST_MAIN"] + "\\n\\nworktree " + os.environ["TEST_LINKED"])
elif args[:1] == ["rev-parse"]:
    print("a" * 40)
elif args[:1] == ["log"]:
    print("1")
elif args[:1] == ["symbolic-ref"]:
    sys.exit(1)
''')
            git.chmod(0o755)
            for name in ("gh", "origin"):
                command = bin_dir / name
                command.write_text("#!/bin/sh\nexit 1\n")
                command.chmod(0o755)
            result = subprocess.run(["bash", str(script), "-b", "HEAD", str(main)],
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                     "PSTACK_TRANSCRIPTS_DIR": "", "TEST_MAIN": str(main),
                     "TEST_LINKED": str(linked)}, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [line.split("\t") for line in result.stdout.splitlines()[2:]]
            self.assertEqual([row[-1] for row in rows], [str(linked)])
            self.assertEqual(rows[0][-2], "review-missing-history")

    def test_upstream_fidelity_and_missing_capability_boundaries_are_declared(self):
        adapter = ROOT / "integrations/pstack/codex"
        rules = json.loads((adapter / "transforms/rules.json").read_text())
        self.assertEqual(len(rules["registered_skills"]), 58)
        self.assertNotIn("orchestrate", rules["registered_skills"])
        self.assertEqual(len(rules["dependencies"]), 4)
        self.assertTrue(all(not p.startswith("skills/statechart/scripts/") for p in rules["files"]))
        roles = rules["files"]["agents/poteto-agent.md"]["edits"]
        self.assertTrue(any(e["id"] == "bound-runtime-no-cache-scan" for e in roles))
        worker = rules["files"]["skills/poteto-mode/playbooks/eval.md"]["edits"]
        self.assertTrue(any(e["id"] == "blind-trial-loading" for e in worker))
        compatibility = json.loads((adapter / "compatibility.json").read_text())
        declared = {row["id"] for row in compatibility["codex_deviations"]}
        used = {edit["id"] for row in rules["files"].values() for edit in row["edits"]}
        self.assertFalse(used - declared)
        self.assertEqual(compatibility["mechanisms"]["native_original_history"]["status"],
                         "unavailable_until_applicable_producer_is_established")


if __name__ == "__main__":
    unittest.main()
