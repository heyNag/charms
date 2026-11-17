"""Explicit setup choices must not require pre-writing the active model rule."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "integrations/pstack/codex/runtime"
sys.path.insert(0, str(RUNTIME))
try:
    import integrity
    import models
finally:
    sys.path.remove(str(RUNTIME))


class ModelChoicesCase(unittest.TestCase):
    def catalog(self):
        return {
            "schema_version": 1,
            "observation_id": "observed-openai-only",
            "models": [
                {
                    "slug": "observed-gpt-high",
                    "family": "gpt-6.1",
                    "vendor": "openai",
                    "effort": "high",
                    "fast": False,
                    "provider_model": "gpt-6.1",
                }
            ],
        }

    def choices(self):
        roles = {role: ["observed-gpt-high"] for role in models.DEFAULTS}
        roles["arena runners"] = ["auto", "observed-gpt-high", "inherit-parent", "auto"]
        roles["arena cross-judge pool"] = ["observed-gpt-high", "auto"]
        return {"schema_version": 1, "roles": roles}

    def test_first_run_requires_choices_then_plans_against_absent_active_file(self):
        unresolved = models.model_plan("", self.catalog(), "large")
        self.assertEqual(unresolved["status"], "needs_choice")
        plan = models.model_plan("", self.catalog(), "large", choices=self.choices())
        self.assertEqual(plan["status"], "awaiting_confirmation")
        self.assertEqual(plan["needs_choice"], [])
        self.assertEqual(plan["source_sha256"], integrity.digest(b""))
        self.assertEqual(plan["roles"], self.choices()["roles"])
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / "models.mdc"
            self.assertFalse(active.exists())
            models.write_preferences(active, plan, approved_plan=plan["plan_sha256"])
            self.assertEqual(models.parse_preferences(active.read_text())["roles"], plan["roles"])

    def test_partial_choices_leave_other_unavailable_roles_unresolved(self):
        plan = models.model_plan(
            "", self.catalog(), "large",
            choices={"schema_version": 1, "roles": {"bug-fix": ["inherit-parent"]}},
        )
        self.assertEqual(plan["roles"]["bug-fix"], ["inherit-parent"])
        self.assertEqual(plan["status"], "needs_choice")
        self.assertNotIn("bug-fix", {row["role"] for row in plan["needs_choice"]})
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / "models.mdc"
            with self.assertRaisesRegex(integrity.RuntimeErrorBase, "still need a choice"):
                models.write_preferences(active, plan, approved_plan=plan["plan_sha256"])
            self.assertFalse(active.exists())

    def test_explicit_choices_follow_budget_mapping_and_keep_panel_order(self):
        plan = models.model_plan("", self.catalog(), "small", choices=self.choices())
        # The source's role-choice step follows budget mapping, allowing the
        # user to select any observed model at xhigh or below for the final table.
        self.assertEqual(plan["roles"], self.choices()["roles"])
        self.assertEqual(plan["choices"], self.choices()["roles"])
        self.assertEqual(plan["budget"], "small")

    def test_unknown_roles_bad_cardinality_and_unobserved_choices_are_rejected(self):
        invalid = [
            [],
            {"schema_version": 2, "roles": {}},
            {"schema_version": True, "roles": {}},
            {"schema_version": 1, "roles": {}, "ignored": True},
            {"schema_version": 1, "roles": []},
            {"schema_version": 1, "roles": {"retired role": ["auto"]}},
            {"schema_version": 1, "roles": {"bug-fix": "auto"}},
            {"schema_version": 1, "roles": {"bug-fix": []}},
            {"schema_version": 1, "roles": {"bug-fix": ["auto", "auto"]}},
            {"schema_version": 1, "roles": {"arena runners": []}},
            {"schema_version": 1, "roles": {"bug-fix": [None]}},
            {"schema_version": 1, "roles": {"bug-fix": ["invented-model"]}},
        ]
        for choices in invalid:
            with self.subTest(choices=choices), self.assertRaises(integrity.RuntimeErrorBase):
                models.model_plan("", self.catalog(), "large", choices=choices)

    def test_choices_cannot_bypass_catalog_identity_or_independent_vendor_rules(self):
        catalog = self.catalog()
        catalog["models"][0]["family"] = "claude-opus-5-5"
        with self.assertRaises(integrity.RuntimeErrorBase):
            models.model_plan("", catalog, "large", choices=self.choices())
        plan = models.model_plan("", self.catalog(), "large", choices=self.choices())
        with self.assertRaisesRegex(integrity.RuntimeErrorBase, "other-vendor"):
            models.choose_judge(
                plan["roles"]["arena cross-judge pool"], self.catalog(), "openai",
                workflow="show-me-your-work",
            )

    def test_approval_and_stale_active_rule_checks_still_apply(self):
        original = "# defaults: 3\n" + "".join(f"{role}: auto\n" for role in models.DEFAULTS)
        choices = {"schema_version": 1, "roles": {"bug-fix": ["observed-gpt-high"]}}
        plan = models.model_plan(original, self.catalog(), "large", choices=choices)
        self.assertEqual(plan["source_sha256"], integrity.digest(original.encode()))
        self.assertEqual(plan["roles"]["hillclimb"], ["auto"])
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / "models.mdc"
            active.write_text(original)
            with self.assertRaisesRegex(integrity.RuntimeErrorBase, "confirmation"):
                models.write_preferences(active, plan, approved_plan="not-approved")
            changed = copy.deepcopy(plan)
            changed["roles"]["bug-fix"] = ["auto"]
            with self.assertRaisesRegex(integrity.RuntimeErrorBase, "confirmation"):
                models.write_preferences(active, changed, approved_plan=plan["plan_sha256"])
            self.assertEqual(active.read_text(), original)
            active.write_text(original + "# intervening edit\n")
            with self.assertRaisesRegex(integrity.RuntimeErrorBase, "changed after planning"):
                models.write_preferences(active, plan, approved_plan=plan["plan_sha256"])

    def test_cli_first_run_choices_can_be_approved_without_an_active_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            active, catalog, choices, saved_plan = (
                base / name for name in ("models.mdc", "catalog.json", "choices.json", "plan.json")
            )
            catalog.write_text(json.dumps(self.catalog()))
            choices.write_text(json.dumps(self.choices()))
            command = [sys.executable, "-B", str(RUNTIME / "pstack_runtime.py"), "models"]
            result = subprocess.run(
                command + ["plan", "--file", str(active), "--catalog", str(catalog),
                           "--budget", "large", "--choices", str(choices)],
                capture_output=True, text=True, check=True,
            )
            plan = json.loads(result.stdout)
            self.assertFalse(active.exists())
            self.assertEqual(plan["status"], "awaiting_confirmation")
            saved_plan.write_text(result.stdout)
            subprocess.run(
                command + ["write", "--file", str(active), "--plan", str(saved_plan),
                           "--approved-plan", plan["plan_sha256"]],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(models.parse_preferences(active.read_text())["roles"], plan["roles"])


if __name__ == "__main__":
    unittest.main()
