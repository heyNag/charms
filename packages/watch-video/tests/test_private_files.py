"""Files that hold credentials are private from the moment they exist."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))
sys.path.insert(0, str(TESTS_DIR))

import groq_transcribe as groq  # noqa: E402
import private_files  # noqa: E402


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


class WriteTests(PrivateFileCase):
    def test_a_new_file_and_its_new_folders_are_private(self) -> None:
        path = self.root / "config" / "watch-video" / ".env"
        private_files.write_private_text(path, "KEY=value\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "KEY=value\n")
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(mode(path.parent), 0o700)
        self.assertEqual(os.listdir(path.parent), [".env"])

    def test_a_folder_that_already_exists_keeps_its_permissions(self) -> None:
        shared = self.root / "shared"
        shared.mkdir(mode=0o755)
        private_files.write_private_text(shared / ".env", "KEY=value\n")
        self.assertEqual(mode(shared), 0o755)
        self.assertEqual(mode(shared / ".env"), 0o600)

    def test_an_open_file_is_replaced_by_a_private_one(self) -> None:
        path = self.root / ".env"
        path.write_text("KEY=old\n", encoding="utf-8")
        path.chmod(0o644)
        private_files.write_private_text(path, "KEY=new\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "KEY=new\n")
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(os.listdir(self.root), [".env"])

    def test_the_content_is_never_in_a_file_others_can_read(self) -> None:
        path = self.root / ".env"
        seen = []
        real_replace = os.replace

        def replace(source, target):
            seen.append((mode(Path(source)), Path(source).read_text(encoding="utf-8")))
            return real_replace(source, target)

        with mock.patch.object(private_files.os, "replace", side_effect=replace):
            private_files.write_private_text(path, "KEY=value\n")
        self.assertEqual(seen, [(0o600, "KEY=value\n")])

    def test_links_in_the_folder_are_not_written_through(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / "target.txt"
        target.write_text("untouched", encoding="utf-8")
        folder = self.root / "config"
        folder.mkdir()
        # The name the old writer used for its temporary file, and the file itself.
        (folder / ".env.tmp").symlink_to(target)
        (folder / ".env").symlink_to(target)

        private_files.write_private_text(folder / ".env", "KEY=value\n")

        self.assertEqual(target.read_text(encoding="utf-8"), "untouched")
        self.assertFalse((folder / ".env").is_symlink())
        self.assertEqual((folder / ".env").read_text(encoding="utf-8"), "KEY=value\n")
        self.assertEqual(mode(folder / ".env"), 0o600)

    def test_a_failed_write_leaves_the_old_file_and_nothing_else(self) -> None:
        path = self.root / ".env"
        path.write_text("KEY=old\n", encoding="utf-8")
        with mock.patch.object(private_files.os, "replace", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                private_files.write_private_text(path, "KEY=new\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "KEY=old\n")
        self.assertEqual(os.listdir(self.root), [".env"])


class StoredKeyTests(PrivateFileCase):
    def store(self, folder: Path, value: str = "gsk_stored1") -> Path:
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_CONFIG_DIR": str(folder)}):
            return groq.set_stored_key("GROQ_API_KEY", value)

    def test_the_key_file_is_private_and_a_new_config_folder_too(self) -> None:
        folder = self.root / "new" / "watch-video"
        path = self.store(folder)
        self.assertEqual(path, folder / ".env")
        self.assertEqual(path.read_text(encoding="utf-8"), "GROQ_API_KEY=gsk_stored1\n")
        self.assertEqual((mode(path), mode(folder)), (0o600, 0o700))
        self.assertEqual(os.listdir(folder), [".env"])

    def test_an_existing_config_folder_keeps_its_permissions(self) -> None:
        folder = self.root / "shared"
        folder.mkdir(mode=0o755)
        (folder / ".env").write_text("# mine\nOPENAI_API_KEY=sk-kept\n", encoding="utf-8")
        (folder / ".env").chmod(0o644)

        path = self.store(folder)

        self.assertEqual(mode(folder), 0o755)
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            "# mine\nOPENAI_API_KEY=sk-kept\nGROQ_API_KEY=gsk_stored1\n",
        )
        self.assertEqual(os.listdir(folder), [".env"])


if __name__ == "__main__":
    unittest.main()
