"""An error about a missing tool names the install command for this computer."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))
sys.path.insert(0, str(TESTS_DIR))

import doctor  # noqa: E402
import extract_frames  # noqa: E402
import groq_transcribe as groq  # noqa: E402
import local_preflight  # noqa: E402
import network_guard  # noqa: E402
import tool_hints  # noqa: E402
import watch  # noqa: E402

MAC = {
    "ffmpeg": "ffmpeg is not installed. fix: brew install ffmpeg",
    "ffprobe": "ffprobe is not installed. fix: brew install ffmpeg",
    "yt-dlp": "yt-dlp is not installed. fix: brew install yt-dlp",
}
LINUX = {
    "ffmpeg": "ffmpeg is not installed. fix: sudo apt install ffmpeg",
    "ffprobe": "ffprobe is not installed. fix: sudo apt install ffmpeg",
    "yt-dlp": 'yt-dlp is not installed. fix: pipx install "yt-dlp[default,deno]"',
}


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def on(system: str):
    """Patches that make this computer look like Darwin or Linux with no tools installed."""
    return (
        mock.patch("shutil.which", return_value=None),
        mock.patch.object(tool_hints.platform, "system", return_value=system),
    )


class HintTests(unittest.TestCase):
    def test_each_platform_gets_its_own_command(self) -> None:
        for name, message in MAC.items():
            self.assertEqual(tool_hints.missing_tool(name, "Darwin"), message)
        for name, message in LINUX.items():
            self.assertEqual(tool_hints.missing_tool(name, "Linux"), message)
            self.assertNotIn("brew", message)

    def test_other_platforms_and_other_tools_still_get_a_sentence(self) -> None:
        self.assertEqual(
            tool_hints.missing_tool("ffmpeg", "FreeBSD"),
            "ffmpeg is not installed. fix: watch-video supports macOS and Linux only",
        )
        self.assertEqual(
            tool_hints.missing_tool("deno", "Linux"), "deno is not installed. fix: install deno",
        )

    def test_doctor_lists_the_same_commands(self) -> None:
        for binaries in (["ffmpeg"], ["ffprobe"], ["yt-dlp"], ["yt-dlp", "ffmpeg", "ffprobe"]):
            self.assertEqual(doctor.install_hints(binaries), tool_hints.install_hints(binaries))
        self.assertEqual(
            doctor.install_hints(), tool_hints.install_hints(list(doctor.LOCAL_BINARIES)),
        )
        for system, expected in (("Darwin", MAC), ("Linux", LINUX)):
            with mock.patch.object(doctor, "current_platform", return_value=tool_hints.current_platform(system)), \
                    mock.patch.object(doctor.shutil, "which", return_value=None):
                for name, message in expected.items():
                    self.assertEqual(
                        f"{name} is not installed. fix: {doctor.check_binary(name)['fix']}", message,
                    )


class ErrorTests(unittest.TestCase):
    def errors(self, system: str) -> dict[str, tuple[str, str]]:
        """The tool each script needs, and what it says when the tool is missing."""
        which, platform_name = on(system)
        found: dict[str, tuple[str, str]] = {}
        with which, platform_name, tempfile.TemporaryDirectory() as temporary:
            for label, tool, call, error in (
                ("watch yt-dlp", "yt-dlp", lambda: watch.require_tool("yt-dlp"), SystemExit),
                ("watch ffprobe", "ffprobe", lambda: watch.require_tool("ffprobe"), SystemExit),
                ("frames ffmpeg", "ffmpeg", extract_frames._require_ffmpeg, RuntimeError),
                ("audio ffmpeg", "ffmpeg", groq._require_ffmpeg, RuntimeError),
                ("audio ffprobe", "ffprobe",
                 lambda: groq.audio_duration_seconds(Path(temporary) / "audio.mp3"), RuntimeError),
            ):
                with self.assertRaises(error, msg=label) as caught:
                    call()
                found[label] = (tool, str(caught.exception))
        return found

    def test_linux_errors_do_not_mention_homebrew(self) -> None:
        for label, (tool, message) in self.errors("Linux").items():
            with self.subTest(script=label):
                self.assertEqual(message, LINUX[tool])

    def test_macos_errors_keep_the_homebrew_command(self) -> None:
        for label, (tool, message) in self.errors("Darwin").items():
            with self.subTest(script=label):
                self.assertEqual(message, MAC[tool])

    def test_local_model_preflight_names_this_platforms_command(self) -> None:
        for system, command in (("Darwin", "brew install ffmpeg"), ("Linux", "sudo apt install ffmpeg")):
            which, platform_name = on(system)
            with self.subTest(system=system), which, platform_name, tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.object(local_preflight.Path, "home", return_value=Path(temporary)), \
                    mock.patch.object(local_preflight, "_sysctl", return_value=None):
                result = local_preflight.preflight(
                    base_url="http://127.0.0.1:8147/v1", model_dir=Path(temporary) / "models",
                )
            step = next(step for step in result["next_steps"] if step["id"] == "ffmpeg")
            self.assertEqual(step["instruction"], f"Install FFmpeg, which includes ffprobe ({command}).")


if __name__ == "__main__":
    unittest.main()
