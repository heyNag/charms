from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "codex-reset-credit"
    / "scripts"
    / "check_reset_credits.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("check_reset_credits", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


reset_credit = load_module()


class CodexResetCreditTests(unittest.TestCase):
    def test_extract_auth_nested_tokens(self) -> None:
        auth = reset_credit.extract_auth(
            {
                "tokens": {
                    "access_token": "access-token",
                    "account_id": "account-id",
                }
            }
        )

        self.assertEqual(auth.access_token, "access-token")
        self.assertEqual(auth.account_id, "account-id")

    def test_extract_auth_missing_token_raises(self) -> None:
        with self.assertRaises(reset_credit.AuthError):
            reset_credit.extract_auth({"tokens": {"account_id": "account-id"}})

    def test_candidate_session_file_specific_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-example.jsonl"
            path.write_text("", encoding="utf-8")

            files = reset_credit.candidate_session_files(
                sessions_root=None,
                session_file=str(path),
                thread_id=None,
            )

        self.assertEqual(files, [path])

    def test_extract_snapshot_reads_latest_token_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-thread.jsonl"
            entries = [
                {"type": "session_meta", "payload": {"id": "thread-123"}},
                {
                    "type": "event_msg",
                    "timestamp": "2026-06-21T00:00:00Z",
                    "payload": {
                        "type": "token_count",
                        "rate_limits": {
                            "plan_type": "pro",
                            "primary": {
                                "used_percent": 42,
                                "window_minutes": 300,
                                "resets_at": "2026-06-21T01:00:00Z",
                            },
                        },
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

            snapshot = reset_credit.extract_snapshot(path)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.thread_id, "thread-123")
        self.assertEqual(snapshot.rate_limits["plan_type"], "pro")

    def test_format_report_does_not_need_live_data(self) -> None:
        report = reset_credit.format_report(
            {
                "reset_credits": None,
                "reset_credits_error": "live unavailable",
                "rate_limits": None,
                "rate_limits_error": "no local snapshots",
            }
        )

        self.assertIn("Reset credits", report)
        self.assertIn("Rate-limit windows", report)


if __name__ == "__main__":
    unittest.main()
