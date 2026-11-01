"""YouTube rolling-caption fixtures with padded 10 ms display refreshes."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills/watch-video/scripts"))

import captions  # noqa: E402
import network_guard  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


# This follows the downloaded en-orig VTT's exact cue/padding/timing shape.
# The words are synthetic so the expected spoken sequence is easy to audit.
ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.630 align:start position:0%
<PAD>
First<00:00:00.400><c> line</c><00:00:00.560><c> starts</c><00:00:00.760><c> here.</c>

00:00:02.630 --> 00:00:02.640 align:start position:0%
First line starts here.
<PAD>

00:00:02.640 --> 00:00:04.390 align:start position:0%
First line starts here.
Second<00:00:02.960><c> line</c><00:00:03.120><c> follows</c><00:00:03.280><c> now.</c>

00:00:04.390 --> 00:00:04.400 align:start position:0%
Second line follows now.
<PAD>

00:00:04.400 --> 00:00:06.230 align:start position:0%
Second line follows now.
Third<00:00:04.640><c> line</c><00:00:04.880><c> finishes</c><00:00:05.160><c> cleanly.</c>

00:00:06.230 --> 00:00:06.240 align:start position:0%
Third line finishes cleanly.
<PAD>

00:00:06.240 --> 00:00:08.030 align:start position:0%
Third line finishes cleanly.
Fourth<00:00:06.600><c> line</c><00:00:06.880><c> wraps</c><00:00:07.160><c> it</c><00:00:07.320><c> up.</c>

00:00:08.030 --> 00:00:08.040 align:start position:0%
Fourth line wraps it up.
<PAD>
""".replace("\n<PAD>\n", "\n \n")


class CaptionRollupTests(unittest.TestCase):
    def parse(self, body):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "captions.vtt"
            path.write_text(body, encoding="utf-8")
            return captions.parse_vtt(path)

    def test_leading_whitespace_display_line_keeps_first_words_at_zero(self):
        out = self.parse(
            "WEBVTT\n\n00:00.000 --> 00:02.630 align:start position:0%\n"
            " \nFirst<00:00.400><c> spoken</c><00:00.800><c> words.</c>\n"
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[0]["text"], "First spoken words.")

    def test_display_refreshes_do_not_repeat_rolling_text_or_drop_words(self):
        out = self.parse(ROLLING_VTT)
        self.assertEqual(
            " ".join(segment["text"] for segment in out),
            "First line starts here. Second line follows now. "
            "Third line finishes cleanly. Fourth line wraps it up.",
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["start"], 0.0)
        self.assertEqual(out[-1]["end"], 8.04)
        self.assertEqual(captions.transcript_coverage_seconds(out), 8.04)

    def test_padded_refresh_after_a_gap_does_not_merge_repeated_speech(self):
        out = self.parse(
            "00:00.000 --> 00:01.000\nSame words.\n\n"
            "00:02.000 --> 00:02.010\nSame words.\n \n"
        )
        self.assertEqual([segment["text"] for segment in out], ["Same words.", "Same words."])
        self.assertEqual(captions.transcript_coverage_seconds(out), 1.01)

    def test_touching_standalone_repetitions_are_preserved_even_when_short(self):
        for ending in ("01.010", "02.000"):
            with self.subTest(ending=ending):
                out = self.parse(
                    "00:00.000 --> 00:01.000\nyes\n\n"
                    f"00:01.000 --> 00:{ending}\nyes\n"
                )
                self.assertEqual(len(out), 2)
                self.assertEqual([segment["text"] for segment in out], ["yes", "yes"])

    def test_refreshes_preserve_speaker_and_region_boundaries(self):
        for first_settings, next_settings, first_text, next_text in (
            ("region:a", "region:b", "same", "same"),
            ("region:a", "region:a", "<v Alice>same</v>", "<v Bob>same</v>"),
        ):
            with self.subTest(settings=next_settings, voice=next_text):
                out = self.parse(
                    f"00:00.000 --> 00:01.000 {first_settings}\n{first_text}\n\n"
                    f"00:01.000 --> 00:01.010 {next_settings}\n{next_text}\n \n"
                )
                self.assertEqual(len(out), 2)
                self.assertEqual(out[-1]["region"], next_settings)
                if "Bob" in next_text:
                    self.assertEqual(out[-1]["speaker"], "Bob")

    def test_padded_multi_voice_cue_keeps_words_without_false_attribution(self):
        out = self.parse(
            "00:00.000 --> 00:02.000 region:a\n \n"
            "<v Alice>Hello</v>\n<v Bob>Hi</v>\n"
        )
        self.assertEqual(out[0]["text"], "Hello Hi")
        self.assertNotIn("speaker", out[0])
        self.assertEqual(out[0]["region"], "region:a")

    def test_whitespace_padding_does_not_end_a_metadata_block(self):
        out = self.parse(
            "WEBVTT\n\nNOTE ignore this example\n \n"
            "00:00.000 --> 00:01.000\nnot spoken\n\n"
            "00:02.000 --> 00:03.000\nactual speech\n"
        )
        self.assertEqual([segment["text"] for segment in out], ["actual speech"])


if __name__ == "__main__":
    unittest.main()
