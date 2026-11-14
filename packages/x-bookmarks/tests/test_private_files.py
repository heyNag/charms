"""Tokens, config and review state are private from the moment they exist."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from test_basic import SCRIPTS, load_module  # noqa: E402


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


class PrivateFileCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # An open umask shows what the code itself asks for.
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)
        self.files = load_module("private_files", SCRIPTS / "private_files.py")


class WriteTests(PrivateFileCase):
    def test_a_new_file_and_its_new_folders_are_private(self) -> None:
        path = self.root / "config" / "x-bookmarks" / "tokens.json"
        self.files.write_private_text(path, "{}\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(mode(path.parent), 0o700)
        self.assertEqual(os.listdir(path.parent), ["tokens.json"])

    def test_a_folder_that_already_exists_keeps_its_permissions(self) -> None:
        shared = self.root / "shared"
        shared.mkdir(mode=0o755)
        self.files.write_private_text(shared / "state.json", "{}\n")
        self.assertEqual(mode(shared), 0o755)
        self.assertEqual(mode(shared / "state.json"), 0o600)

    def test_an_open_file_is_replaced_by_a_private_one(self) -> None:
        path = self.root / "tokens.json"
        path.write_text('{"old": true}\n', encoding="utf-8")
        path.chmod(0o644)
        self.files.write_private_text(path, '{"new": true}\n')
        self.assertEqual(path.read_text(encoding="utf-8"), '{"new": true}\n')
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(os.listdir(self.root), ["tokens.json"])

    def test_the_content_is_never_in_a_file_others_can_read(self) -> None:
        path = self.root / "tokens.json"
        seen = []
        real_replace = os.replace

        def replace(source, target):
            seen.append((mode(Path(source)), Path(source).read_text(encoding="utf-8")))
            return real_replace(source, target)

        with mock.patch.object(self.files.os, "replace", side_effect=replace):
            self.files.write_private_text(path, '{"access_token": "test"}\n')
        self.assertEqual(seen, [(0o600, '{"access_token": "test"}\n')])

    def test_links_in_the_folder_are_not_written_through(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / "target.txt"
        target.write_text("untouched", encoding="utf-8")
        folder = self.root / "config"
        folder.mkdir()
        # The name the old writer used for its temporary file, and the file itself.
        (folder / "tokens.json.tmp").symlink_to(target)
        (folder / "tokens.json").symlink_to(target)

        self.files.write_private_text(folder / "tokens.json", "{}\n")

        self.assertEqual(target.read_text(encoding="utf-8"), "untouched")
        self.assertFalse((folder / "tokens.json").is_symlink())
        self.assertEqual((folder / "tokens.json").read_text(encoding="utf-8"), "{}\n")
        self.assertEqual(mode(folder / "tokens.json"), 0o600)

    def test_a_failed_write_leaves_the_old_file_and_nothing_else(self) -> None:
        path = self.root / "tokens.json"
        path.write_text('{"old": true}\n', encoding="utf-8")
        with mock.patch.object(self.files.os, "replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                self.files.write_private_text(path, '{"new": true}\n')
        self.assertEqual(path.read_text(encoding="utf-8"), '{"old": true}\n')
        self.assertEqual(os.listdir(self.root), ["tokens.json"])


class SavedFileTests(PrivateFileCase):
    def load(self, config_dir: Path, token_file: Path):
        with mock.patch.dict(os.environ, {
            "X_BOOKMARKS_CONFIG_DIR": str(config_dir), "X_BOOKMARKS_TOKEN_FILE": str(token_file),
        }):
            auth = load_module("x_api_auth_private_files", SCRIPTS / "x_api_auth.py")
            api = load_module("fetch_bookmarks_api_private_files", SCRIPTS / "fetch_bookmarks_api.py")
        return auth, api

    def test_config_and_tokens_are_private_in_a_private_new_folder(self) -> None:
        folder = self.root / "new" / "x-bookmarks"
        auth, _ = self.load(folder, folder / "tokens.json")
        auth.save_config({"client_id": "test-client"})
        auth.save_tokens({"access_token": "test-access"})
        self.assertEqual(json.loads(auth.CONFIG_FILE.read_text()), {"client_id": "test-client"})
        self.assertEqual(json.loads(auth.TOKEN_FILE.read_text()), {"access_token": "test-access"})
        self.assertEqual(
            (mode(auth.CONFIG_FILE), mode(auth.TOKEN_FILE), mode(folder)), (0o600, 0o600, 0o700),
        )
        self.assertEqual(sorted(os.listdir(folder)), ["config.json", "tokens.json"])

    def test_custom_token_and_state_paths_leave_their_folder_as_it_is(self) -> None:
        shared = self.root / "shared"
        shared.mkdir(mode=0o755)
        auth, api = self.load(self.root / "config", shared / "tokens.json")

        auth.save_tokens({"access_token": "test-access"})
        api.save_state(shared / "state.json", {"scopes": {"all": {"last_seen_id": "1"}}})

        self.assertEqual(mode(shared), 0o755)
        self.assertEqual((mode(shared / "tokens.json"), mode(shared / "state.json")), (0o600, 0o600))
        self.assertEqual(
            json.loads((shared / "state.json").read_text()), {"scopes": {"all": {"last_seen_id": "1"}}},
        )
        self.assertEqual(sorted(os.listdir(shared)), ["state.json", "tokens.json"])

    def test_new_state_folder_is_private(self) -> None:
        _, api = self.load(self.root / "config", self.root / "config" / "tokens.json")
        state = self.root / "state" / "x-bookmarks" / "state.json"
        api.save_state(state, {"scopes": {}})
        self.assertEqual((mode(state), mode(state.parent)), (0o600, 0o700))


if __name__ == "__main__":
    unittest.main()
