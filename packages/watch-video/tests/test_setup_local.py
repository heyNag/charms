"""Portable native oMLX setup: safe defaults, storage, and resumable downloads."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import setup_local as setup  # noqa: E402
import network_guard  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


class FakeAdmin:
    inference_url = "http://127.0.0.1:8147/v1"

    def __init__(self, root):
        self.root = root
        self.settings = {"server": {"host": "127.0.0.1"},
                         "model": {"model_dirs": [str(root)]},
                         "external_engines": {"splash": {"available": True}},
                         "auth": {"api_key": "secret-never-output"}}
        self.models = []
        self.tasks = []
        self.calls = []
        self.ignore_settings_write = False
        self.fail_download = False

    def install_models(self, configured=False):
        for repo in setup.REPOSITORIES:
            path = self.root / repo
            path.mkdir(parents=True, exist_ok=True)
            (path / "config.json").write_text("{}")
            (path / "model.safetensors").write_bytes(b"fixture")
            self.models.append({"id": repo.split("/")[-1], "model_path": str(path),
                                "settings": {}, "loaded": False,
                                "external_engines": [{"id": "splash", "compatible": True}]})
        if configured:
            self.models[1]["settings"] = {
                "model_alias": setup.VISION_ALIAS, "external_engine": "splash",
                "max_context_window": 16384, "ttl_seconds": 300,
                "dflash_draft_model": setup.DRAFT_REPO.split("/")[-1],
            }

    def request_json(self, path, payload=None, *, method=None):
        self.calls.append((path, copy.deepcopy(payload), method))
        if path == "global-settings":
            return copy.deepcopy(self.settings)
        if path == "models":
            return {"models": copy.deepcopy(self.models)}
        if path == "hf/tasks":
            return {"tasks": copy.deepcopy(self.tasks)}
        if path == "reload":
            return {"success": True}
        if path == "hf/download":
            if self.fail_download:
                raise setup.LocalAPIError("Local API response was interrupted or malformed.")
            self.tasks.append({"repo_id": payload["repo_id"], "status": "pending", "created_at": 1})
            return {"success": True}
        if path.endswith("/settings") and method == "PUT":
            if not self.ignore_settings_write:
                self.models[1]["settings"].update(payload)
            return {"success": True}
        raise AssertionError(f"Unexpected request: {path}")


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / ".omlx/models"
        self.client = FakeAdmin(self.root)

    def run_setup(self, **kwargs):
        return setup.setup(client=self.client, model_dir=self.root, **kwargs)

    def test_check_is_read_only_and_does_not_expose_auth(self):
        result = self.run_setup()
        self.assertEqual(result["status"], "needs_setup")
        self.assertEqual(len(result["models"]), 3)
        self.assertFalse(any(payload is not None for _, payload, _ in self.client.calls))
        self.assertNotIn("secret-never-output", json.dumps(result))
        self.assertFalse(self.root.exists())

    def test_configure_queues_only_missing_and_second_run_reuses_active_tasks(self):
        result = self.run_setup(configure=True)
        self.assertEqual(result["status"], "pending")
        self.assertEqual([call[1]["repo_id"] for call in self.client.calls if call[0] == "hf/download"],
                         list(setup.REPOSITORIES))
        self.client.calls.clear()
        result = self.run_setup(configure=True)
        self.assertEqual(result["status"], "pending")
        self.assertFalse(any(path == "hf/download" for path, _, _ in self.client.calls))

    def test_models_in_another_cache_do_not_satisfy_common_storage(self):
        self.client.install_models()
        for model in self.client.models:
            model["model_path"] = str(Path(self.temp.name) / "other-cache" / model["id"])
        result = self.run_setup()
        self.assertTrue(all(row["state"] == "missing" for row in result["models"]))

    def test_wrong_directory_or_missing_splash_blocks_before_any_mutation(self):
        for change in ("directory", "splash", "host"):
            with self.subTest(change=change):
                self.client = FakeAdmin(self.root)
                if change == "directory":
                    self.client.settings["model"]["model_dirs"] = [str(self.root / "different")]
                elif change == "splash":
                    self.client.settings["external_engines"]["splash"]["available"] = False
                else:
                    self.client.settings["server"]["host"] = "0.0.0.0"
                result = self.run_setup(configure=True)
                self.assertTrue(result["blockers"])
                self.assertEqual(len(self.client.calls), 1)

    def test_failed_download_does_not_retry_or_queue_more(self):
        self.client.tasks = [{"repo_id": setup.VISION_REPO, "status": "failed", "created_at": 1,
                              "error": "private body secret-never-output"}]
        result = self.run_setup(configure=True)
        self.assertEqual(result["status"], "error")
        self.assertFalse(any(path == "hf/download" for path, _, _ in self.client.calls))
        self.assertNotIn("private body", json.dumps(result))

    def test_ambiguous_download_failure_stops_without_repeating_write(self):
        self.client.fail_download = True
        with self.assertRaises(setup.LocalAPIError):
            self.run_setup(configure=True)
        self.assertEqual(sum(path == "hf/download" for path, _, _ in self.client.calls), 1)

    def test_configure_sets_alias_and_bounded_context_then_verifies(self):
        self.client.install_models()
        result = self.run_setup(configure=True)
        self.assertEqual(result["status"], "ready")
        writes = [call for call in self.client.calls if call[2] == "PUT"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "models/Qwen3.6-35B-A3B-4bit/settings")
        self.assertEqual(writes[0][1]["model_alias"], setup.VISION_ALIAS)
        self.assertEqual(writes[0][1]["dflash_draft_model"], "Qwen3.6-35B-A3B-DFlash2")
        self.assertNotIn("auth", writes[0][1])
        self.client.calls.clear()
        self.assertEqual(self.run_setup(configure=True)["status"], "ready")
        self.assertFalse(any(method == "PUT" for _, _, method in self.client.calls))

    def test_settings_http_success_without_persistence_is_not_ready(self):
        self.client.install_models()
        self.client.ignore_settings_write = True
        with self.assertRaisesRegex(setup.LocalAPIError, "could not be verified"):
            self.run_setup(configure=True)

    def test_loaded_model_is_not_reconfigured(self):
        self.client.install_models()
        self.client.models[1]["loaded"] = True
        result = self.run_setup(configure=True)
        self.assertEqual(result["status"], "needs_setup")
        self.assertFalse(any(method == "PUT" for _, _, method in self.client.calls))

    def test_active_download_never_uses_partially_registered_model(self):
        self.client.install_models(configured=True)
        self.client.tasks.append({"repo_id": setup.VISION_REPO, "status": "downloading", "created_at": 1})
        self.assertEqual(self.run_setup()["status"], "pending")

    def test_missing_shard_is_not_present(self):
        self.client.install_models(configured=True)
        path = self.root / setup.VISION_REPO
        (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "missing.safetensors"}}))
        result = self.run_setup()
        self.assertEqual(result["models"][1]["state"], "missing")

    def test_bounded_wait_does_not_cancel_app_downloads(self):
        with mock.patch.object(setup.time, "monotonic", side_effect=[0, 0, 5]), \
                mock.patch.object(setup.time, "sleep") as sleep:
            result = self.run_setup(configure=True, wait_seconds=5)
        self.assertEqual(result["status"], "pending")
        sleep.assert_called_once_with(5)
        self.assertEqual(sum(path == "hf/download" for path, _, _ in self.client.calls), 3)
        self.assertFalse(any("cancel" in path for path, _, _ in self.client.calls))

    def test_wait_finishes_native_downloads_and_configures_without_requeue(self):
        def finish_downloads(_seconds):
            self.client.install_models()
            for task in self.client.tasks:
                task["status"] = "completed"

        with mock.patch.object(setup.time, "monotonic", side_effect=[0, 0]), \
                mock.patch.object(setup.time, "sleep", side_effect=finish_downloads):
            result = self.run_setup(configure=True, wait_seconds=10)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(sum(path == "hf/download" for path, _, _ in self.client.calls), 3)
        self.assertEqual(sum(method == "PUT" for _, _, method in self.client.calls), 1)

    def test_ready_check_and_portable_home_default(self):
        self.client.install_models(configured=True)
        with mock.patch.object(setup.Path, "home", return_value=Path(self.temp.name)):
            result = setup.setup(client=self.client)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["model_directory"], str(self.root.resolve()))

    def test_admin_client_stays_loopback_and_reuses_sanitized_transport(self):
        for url in ("https://example.com/v1", "http://secret@127.0.0.1/v1"):
            with self.assertRaises(ValueError):
                setup.AdminClient(url)
        client = setup.AdminClient("http://localhost:8147/v1")
        self.assertEqual(client.base_url, "http://127.0.0.1:8147/admin/api")
        self.assertEqual(client.inference_url, "http://127.0.0.1:8147/v1")

    def test_cli_exits_two_for_pending_without_dumping_global_settings(self):
        with mock.patch.object(setup, "AdminClient", return_value=self.client), \
                redirect_stdout(io.StringIO()) as output:
            code = setup.main(["--configure", "--model-dir", str(self.root), "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "pending")
        self.assertNotIn("secret-never-output", output.getvalue())


if __name__ == "__main__":
    unittest.main()
