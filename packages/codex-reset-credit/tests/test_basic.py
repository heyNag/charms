from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_load_auth_errors_do_not_reveal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "private-auth.json"
            with self.assertRaises(reset_credit.AuthError) as missing_error:
                reset_credit.load_auth(str(missing))

            unreadable = Path(tmp) / "directory-auth.json"
            unreadable.mkdir()
            with self.assertRaises(reset_credit.AuthError) as read_error:
                reset_credit.load_auth(str(unreadable))

        self.assertEqual(str(missing_error.exception), "Codex auth file not found.")
        self.assertEqual(str(read_error.exception), "Could not read Codex auth file.")
        self.assertNotIn(str(missing), str(missing_error.exception))
        self.assertNotIn(str(unreadable), str(read_error.exception))

    def test_default_state_paths_follow_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"CODEX_HOME": tmp}):
                self.assertEqual(reset_credit.auth_candidates(), [Path(tmp) / "auth.json"])
                self.assertEqual(reset_credit.session_roots(), [Path(tmp) / "sessions"])

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

    def test_normalize_reset_credits_handles_camel_case_payload(self) -> None:
        import datetime as dt

        summary = reset_credit.normalize_reset_credits(
            {
                "availableResetCredits": 2,
                "totalEarnedCount": 5,
                "resetCredits": [
                    {"state": "available", "expiresAt": "2026-07-10T00:00:00Z"},
                    {"state": "used", "expiresAt": "2026-07-01T00:00:00Z"},
                ],
            },
            dt.timezone.utc,
        )

        self.assertEqual(summary["available"], "2")
        self.assertEqual(summary["total_earned"], "5")
        self.assertEqual(len(summary["credits"]), 2)
        # Credits sort by expiry; the available one is picked as next expiring.
        self.assertEqual(summary["next_expiring_credit"]["status"], "available")

    def test_parse_datetime_accepts_epoch_millis_and_iso(self) -> None:
        millis = reset_credit._parse_datetime(1_780_000_000_000)
        seconds = reset_credit._parse_datetime(1_780_000_000)
        iso = reset_credit._parse_datetime("2026-07-02T10:00:00Z")

        self.assertIsNotNone(millis)
        self.assertEqual(millis, seconds)
        self.assertIsNotNone(iso)
        assert iso is not None
        self.assertEqual(iso.year, 2026)

    def test_display_window_minutes_humanizes(self) -> None:
        self.assertEqual(reset_credit._display_window_minutes(1440), "1d (1440 minutes)")
        self.assertEqual(reset_credit._display_window_minutes(300), "5h (300 minutes)")
        self.assertEqual(reset_credit._display_window_minutes(90), "90 minutes")

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
