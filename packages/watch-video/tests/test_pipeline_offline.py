"""Offline end-to-end pipeline test using a fake yt-dlp on PATH.

Exercises watch.py's full URL orchestration - probe, download decision,
frame engines, captions, report - with zero network: a shim yt-dlp copies
fixture files (info JSON, English VTT, an ffmpeg-synthesized mp4) into the
media directory. POSIX-only because the shim relies on shebang execution.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parents[0] / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(TESTS_DIR))

from test_frame_engines import build_cut_clip  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

FAKE_YTDLP = """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
out_dir = Path(args[args.index("-o") + 1]).parent
out_dir.mkdir(parents=True, exist_ok=True)
fixtures = Path(os.environ["FAKE_YTDLP_FIXTURES"])
if "--skip-download" in args:
    shutil.copy(fixtures / "video.info.json", out_dir / "video.info.json")
    shutil.copy(fixtures / "captions.vtt", out_dir / "video.en.vtt")
else:
    shutil.copy(fixtures / "media.mp4", out_dir / "video.mp4")
sys.exit(0)
"""

FIXTURE_VTT = """WEBVTT

00:00:00.500 --> 00:00:02.000
hello from fixtures

00:00:02.000 --> 00:00:03.500
second caption line
"""


@unittest.skipUnless(os.name == "posix" and HAVE_FFMPEG, "needs POSIX shim and ffmpeg")
class OfflinePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)

        fixtures = base / "fixtures"
        fixtures.mkdir()
        build_cut_clip(fixtures / "media.mp4")
        (fixtures / "captions.vtt").write_text(FIXTURE_VTT, encoding="utf-8")
        (fixtures / "video.info.json").write_text(
            json.dumps(
                {
                    "id": "fixture",
                    "title": "Fixture Video",
                    "uploader": "Tester",
                    "duration": 4.0,
                    "webpage_url": "https://example.com/v",
                }
            ),
            encoding="utf-8",
        )

        shim_dir = base / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "yt-dlp"
        shim.write_text(FAKE_YTDLP, encoding="utf-8")
        shim.chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_YTDLP_FIXTURES"] = str(fixtures)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("WATCH_VIDEO_DETAIL", None)
        cls.env = env
        cls.base = base

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def run_watch(self, *extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        out_dir = Path(tempfile.mkdtemp(dir=self.base))
        cmd = [
            sys.executable,
            str(SCRIPTS / "watch.py"),
            "https://example.com/v",
            "--transcriber",
            "none",
            "--out-dir",
            str(out_dir),
            *extra,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=self.env, timeout=180, check=False
        )
        return proc, out_dir

    def _single_run_dir(self, out_dir: Path) -> Path:
        runs = [entry for entry in out_dir.iterdir() if entry.is_dir()]
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_full_run_produces_frames_captions_and_report(self) -> None:
        proc, out_dir = self.run_watch("--max-frames", "6")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("native captions", report)
        self.assertIn("Fixture Video", report)
        self.assertIn(
            "hello from fixtures", (run_dir / "transcript.md").read_text(encoding="utf-8")
        )
        frames = list((run_dir / "frames").glob("frame_*"))
        self.assertTrue(frames)
        self.assertLessEqual(len(frames), 6)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["detail"], "balanced")
        self.assertIn(metadata["frames"]["engine"]["engine"], {"scene", "uniform"})
        self.assertTrue((run_dir / "media" / "video.mp4").exists())

    def test_transcript_detail_skips_media_download(self) -> None:
        proc, out_dir = self.run_watch("--detail", "transcript")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skipping media download", proc.stderr)
        run_dir = self._single_run_dir(out_dir)
        self.assertFalse((run_dir / "media" / "video.mp4").exists())
        self.assertIn(
            "hello from fixtures", (run_dir / "transcript.md").read_text(encoding="utf-8")
        )
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["frames"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
