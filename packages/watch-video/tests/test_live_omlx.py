"""Ask a running oMLX server what the setup helper asks it. Opt-in.

The other tests give setup_local.py a stand-in for oMLX's admin API, so a
change in the real API would still pass them. This test puts the same
read-only questions to the real server. It is skipped unless
WATCH_VIDEO_LIVE_OMLX=1, which `make omlx-test` sets. It uses the saved local
configuration, changes nothing in oMLX and loads no model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import setup_local  # noqa: E402

LIVE = os.environ.get("WATCH_VIDEO_LIVE_OMLX") == "1"
SKIP_REASON = "needs a running oMLX server: set WATCH_VIDEO_LIVE_OMLX=1 or run `make omlx-test`"
# What the read-only check may report for a server it understands.
STATUSES = {"ready", "needs_setup", "pending"}
MODEL_STATES = {"present", "missing", "downloading"}


def check_result(result: object) -> list[str]:
    """Say what is wrong with the answer of `setup_local.py --check --json`."""
    if not isinstance(result, dict):
        return ["the check did not print a JSON object"]
    blockers = result.get("blockers") or []
    status = result.get("status")
    if status not in STATUSES:
        return [f"status is {status!r}: {'; '.join(str(item) for item in blockers) or 'no reason given'}"]
    if blockers:
        # The server answered, and something in its settings has to change first.
        return []

    problems: list[str] = []
    rows = result.get("models")
    rows = rows if isinstance(rows, list) else []
    names = sorted(str(row.get("repo_id")) for row in rows if isinstance(row, dict))
    if names != sorted(setup_local.REPOSITORIES):
        problems.append(f"expected one row for each model repository, found {names}")
    for row in rows:
        if isinstance(row, dict) and row.get("state") not in MODEL_STATES:
            problems.append(f"{row.get('repo_id')}: unexpected state {row.get('state')!r}")
    if status == "ready" and result.get("model_settings_needed") != {}:
        problems.append("a ready server should need no model settings")
    return problems


class CheckResultTests(unittest.TestCase):
    """The reading of the answer, held against the answers the helper can give."""

    def rows(self, state: str = "present") -> list[dict[str, str]]:
        return [{"repo_id": repo, "path": f"/models/{repo}", "state": state} for repo in setup_local.REPOSITORIES]

    def test_answers_from_a_server_the_helper_understands_pass(self) -> None:
        ready = {"status": "ready", "blockers": [], "models": self.rows(), "model_settings_needed": {}}
        missing = {"status": "needs_setup", "blockers": [], "models": self.rows("missing")}
        downloading = {"status": "pending", "blockers": [], "models": self.rows("downloading")}
        blocked = {"status": "needs_setup", "blockers": ["Set oMLX's primary model directory."], "models": []}
        for result in (ready, missing, downloading, blocked):
            with self.subTest(status=result["status"], blocked=bool(result["blockers"])):
                self.assertEqual(check_result(result), [])

    def test_an_error_or_an_unknown_answer_is_reported(self) -> None:
        self.assertEqual(check_result([]), ["the check did not print a JSON object"])
        self.assertEqual(
            check_result({"status": "error", "blockers": ["oMLX returned an unsupported setup response."]}),
            ["status is 'error': oMLX returned an unsupported setup response."],
        )
        self.assertEqual(check_result({"status": "error"}), ["status is 'error': no reason given"])
        self.assertEqual(
            check_result({"status": "needs_setup", "blockers": [], "models": self.rows()[:1]}),
            [f"expected one row for each model repository, found {[setup_local.REPOSITORIES[0]]}"],
        )
        unknown = self.rows()
        unknown[0]["state"] = "queued"
        self.assertEqual(
            check_result({"status": "needs_setup", "blockers": [], "models": unknown}),
            [f"{setup_local.REPOSITORIES[0]}: unexpected state 'queued'"],
        )
        self.assertEqual(
            check_result({"status": "ready", "blockers": [], "models": self.rows(),
                          "model_settings_needed": {"ttl_seconds": 300}}),
            ["a ready server should need no model settings"],
        )


@unittest.skipUnless(LIVE, SKIP_REASON)
class LiveOmlxSetupTests(unittest.TestCase):
    def test_the_read_only_check_understands_the_running_server(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "setup_local.py"), "--check", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=120,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except ValueError:
            self.fail(f"setup_local.py --check --json printed no JSON (exit {completed.returncode})")

        self.assertEqual(check_result(result), [])
        print(f"\noMLX setup check: {result['status']}")
        for row in result.get("models", []):
            print(f"  {row['repo_id']}: {row['state']}")
        for blocker in result.get("blockers", []):
            print(f"  to do: {blocker}")


if __name__ == "__main__":
    unittest.main()
