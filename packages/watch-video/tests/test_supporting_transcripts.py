"""Offline checks for supplied transcript discovery and honest timing metadata."""

from __future__ import annotations

import codecs
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "watch-video" / "scripts"))

from supporting_transcripts import discover_supporting_transcripts, load_supporting_transcript  # noqa: E402


class SupportingTranscriptTests(unittest.TestCase):
    def test_discovery_keeps_all_exact_matches_without_nearby_meetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            video = directory / "Meeting Recording.mp4"
            expected = ["Meeting Recording.txt", "Meeting Recording_transcript.TXT",
                        "Meeting Recording_transcript_grouped.txt"]
            other = ["Meeting Recording 2.txt", "Meeting Recording.en.txt",
                     "Meeting Recording_transcript_grouped.vtt", "Meeting Recording_transcript_old.txt",
                     "Other Meeting Recording.txt", "Meeting Record.txt"]
            for name in reversed(expected + other):
                (directory / name).write_text("fixture", encoding="utf-8")
            self.assertEqual([p.name for p in discover_supporting_transcripts(video)], expected)

    def test_discovery_requires_exact_stem_case_and_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "meeting.txt").write_text("different name", encoding="utf-8")
            (directory / "Meeting_transcript.txt").mkdir()
            self.assertEqual(discover_supporting_transcripts(directory / "Meeting.mp4"), [])

    def test_discovery_preserves_txt_and_srt_without_matching_other_meetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            expected = ["meeting.txt", "meeting_transcript.TXT", "meeting_transcript_grouped.txt",
                        "meeting.SRT", "meeting_transcript.srt", "meeting_transcript_grouped.srt"]
            other = ["meeting 2.srt", "meeting_transcript_old.srt", "meeting.en.srt", "othermeeting.srt"]
            for name in reversed(expected + other):
                (directory / name).write_text("fixture", encoding="utf-8")
            self.assertEqual([p.name for p in discover_supporting_transcripts(directory / "meeting.mp4")], expected)

    def test_missing_sidecars_return_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_supporting_transcripts(Path(tmp) / "meeting.mp4"), [])

    def test_discovery_does_not_follow_matching_transcript_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "recordings"
            directory.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("Outside the selected recording folder.", encoding="utf-8")
            (directory / "meeting.txt").symlink_to(outside)
            (directory / "meeting.srt").symlink_to(outside)
            sidecar = directory / "meeting_transcript.txt"
            sidecar.write_text("Direct sidecar.", encoding="utf-8")
            self.assertEqual(discover_supporting_transcripts(directory / "meeting.mp4"), [sidecar])

    def test_grouped_speech_preserves_preamble_paragraphs_and_only_start_times(self):
        original = (
            "Meeting title\r\nExported transcript\r\n\r\n"
            "[00:01:02.125] Alex Smith: First line.\r\nSecond line.\r\n\r\nAnother paragraph.\r\n"
            "[01:02:03] Blair:\r\nNext speaker.\r\n"
            "[01:03:00] Speech without a speaker label.\r\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            path.write_bytes(original.encode("utf-8"))
            result = load_supporting_transcript(path)
        self.assertEqual(result["text"], original)
        self.assertEqual(result["role"], "supporting")
        self.assertEqual(result["provenance"], "supplied_transcript")
        self.assertEqual(result["timestamps"], "block_start")
        self.assertEqual(result["blocks"], [
            {"text": "Meeting title\nExported transcript"},
            {"start": 62.125, "speaker": "Alex Smith", "text": "First line.\nSecond line.\n\nAnother paragraph."},
            {"start": 3723.0, "speaker": "Blair", "text": "Next speaker."},
            {"start": 3780.0, "text": "Speech without a speaker label."},
        ])
        self.assertEqual(result["warnings"], [])
        self.assertTrue(all("end" not in block for block in result["blocks"]))

    def test_plain_text_does_not_invent_speakers_or_timing(self):
        text = "Alex: We should ship this.\n\nBlair: Agreed.\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            path.write_text(text, encoding="utf-8")
            result = load_supporting_transcript(path)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["blocks"], [{"text": text.strip()}])
        self.assertEqual(result["timestamps"], "unavailable")

    def test_bom_encodings_preserve_unicode_and_hash_original_bytes(self):
        text = "Résumé\n[00:00:01.5] 李: Hello.\n"
        encodings = [codecs.BOM_UTF8 + text.encode("utf-8"),
                     codecs.BOM_UTF16_LE + text.encode("utf-16-le"),
                     codecs.BOM_UTF16_BE + text.encode("utf-16-be")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            for raw in encodings:
                with self.subTest(bom=raw[:3]):
                    path.write_bytes(raw)
                    result = load_supporting_transcript(path)
                    self.assertEqual(result["text"], text)
                    self.assertEqual(result["content_hash"], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(result["blocks"][1]["speaker"], "李")
                    self.assertEqual(result["blocks"][1]["start"], 1.5)

    def test_malformed_timestamps_remain_untimed_and_keep_all_content(self):
        malformed = ["[00:61:00]", "[00:00:60]", "[01:23]", "[00:00:01,5]",
                     "[00:00:05.abc]", "[-01:00:00]", "[00:00:05"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            for header in malformed:
                text = f"[00:00:01] Alex: Before.\n{header} Blair: Keep this.\nContinuation.\n[00:00:10] After."
                with self.subTest(header=header):
                    path.write_text(text, encoding="utf-8")
                    result = load_supporting_transcript(path)
                    self.assertEqual(result["text"], text)
                    self.assertEqual(result["blocks"][1], {"text": f"{header} Blair: Keep this.\nContinuation."})
                    self.assertEqual(len(result["warnings"]), 1)
                    self.assertIn("Line 2", result["warnings"][0])

    def test_nonmonotonic_timestamps_are_not_sorted_or_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            path.write_text("[00:00:10] Later.\n[00:00:01] Earlier.", encoding="utf-8")
            result = load_supporting_transcript(path)
        self.assertEqual([block["start"] for block in result["blocks"]], [10.0, 1.0])
        self.assertEqual(len(result["warnings"]), 1)

    def test_read_and_decode_errors_are_left_to_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            with self.assertRaises(FileNotFoundError):
                load_supporting_transcript(path)
            path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(UnicodeDecodeError):
                load_supporting_transcript(path)
            path.write_bytes(b"\xffinvalid utf8")
            with self.assertRaises(UnicodeDecodeError):
                load_supporting_transcript(path)

    def test_empty_transcript_is_preserved_without_timed_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.txt"
            path.write_bytes(b"")
            result = load_supporting_transcript(path)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["blocks"], [])
        self.assertEqual(result["timestamps"], "unavailable")

    def test_srt_preserves_repeated_cues_order_multiline_text_and_supplied_ranges(self):
        text = (
            "1\r\n00:00:03,125 --> 00:00:04,750\r\nRepeated speech.\r\nSecond line.\r\n\r\n"
            "2\r\n00:00:03.500 --> 00:00:05.000\r\nRepeated speech.\r\nSecond line.\r\n\r\n"
            "3\r\n00:00:01,000 --> 00:00:02,000\r\nEarlier cue appears later in source.\r\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.srt"
            path.write_bytes(text.encode("utf-8"))
            result = load_supporting_transcript(path)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["timestamps"], "cue_range")
        self.assertEqual(result["role"], "supporting")
        self.assertEqual(result["provenance"], "supplied_transcript")
        self.assertEqual(result["blocks"], [
            {"start": 3.125, "end": 4.75, "text": "Repeated speech.\nSecond line."},
            {"start": 3.5, "end": 5.0, "text": "Repeated speech.\nSecond line."},
            {"start": 1.0, "end": 2.0, "text": "Earlier cue appears later in source."},
        ])
        self.assertEqual(result["warnings"], [])

    def test_srt_invalid_cues_remain_untimed_without_hiding_preamble_or_speech(self):
        invalid = ["00:00:03,000 --> 00:00:02,000", "00:00:01,000 --> 00:00:01,000",
                   "00:99:00,000 --> 01:00:00,000", "00:00:01,000 --> 00:00:02,0000",
                   "00:00:01 --> 00:00:02", "00:00:01,000 -> 00:00:02,000"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.srt"
            for timing in invalid:
                text = f"Meeting title\n\n1\n{timing}\nDo not lose this.\n\n2\n00:00:10,000 --> 00:00:11,000\nValid speech."
                with self.subTest(timing=timing):
                    path.write_text(text, encoding="utf-8")
                    result = load_supporting_transcript(path)
                    self.assertEqual(result["text"], text)
                    self.assertEqual(result["blocks"][0], {"text": "Meeting title"})
                    self.assertEqual(result["blocks"][1], {"text": f"1\n{timing}\nDo not lose this."})
                    self.assertEqual(result["blocks"][2], {"start": 10.0, "end": 11.0, "text": "Valid speech."})
                    self.assertEqual(len(result["warnings"]), 2)
                    self.assertEqual(result["timestamps"], "cue_range")

    def test_srt_utf16_bom_and_uppercase_suffix_preserve_text_and_hash(self):
        text = "1\r\n00:00:01,500 --> 00:00:03,000\r\nRésumé 李\r\n"
        raw = codecs.BOM_UTF16_BE + text.encode("utf-16-be")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.SRT"
            path.write_bytes(raw)
            result = load_supporting_transcript(path)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["content_hash"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["blocks"], [{"start": 1.5, "end": 3.0, "text": "Résumé 李"}])

    def test_srt_speaker_requires_explicit_voice_markup_and_body_is_preserved(self):
        bodies = ["Alex: We use A --> B.", "<v Alex &amp; Blair>We agree.</v>",
                  "<v Alex>First.</v>\n<v Blair>Second.</v>"]
        text = "\n\n".join(f"{n}\n00:00:0{n},000 --> 00:00:0{n + 1},000\n{body}"
                           for n, body in enumerate(bodies, start=1))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.srt"
            path.write_text(text, encoding="utf-8")
            result = load_supporting_transcript(path)
        self.assertEqual([block["text"] for block in result["blocks"]], bodies)
        self.assertNotIn("speaker", result["blocks"][0])
        self.assertEqual(result["blocks"][1]["speaker"], "Alex & Blair")
        self.assertNotIn("speaker", result["blocks"][2])
        self.assertEqual(result["warnings"], [])

    def test_srt_missing_cue_separator_is_preserved_instead_of_combining_ranges(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\nFirst.\n2\n00:00:03,000 --> 00:00:04,000\nSecond."
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.srt"
            path.write_text(text, encoding="utf-8")
            result = load_supporting_transcript(path)
        self.assertEqual(result["blocks"], [{"text": text}])
        self.assertEqual(result["timestamps"], "unavailable")
        self.assertEqual(len(result["warnings"]), 1)

    def test_srt_empty_file_and_empty_cue_do_not_invent_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meeting.srt"
            for text in ("", " \n\r\n"):
                path.write_text(text, encoding="utf-8")
                result = load_supporting_transcript(path)
                self.assertEqual(result["blocks"], [])
                self.assertEqual(result["warnings"], [])
                self.assertEqual(result["timestamps"], "unavailable")
            path.write_text("1\n00:00:01,000 --> 00:00:02,000\n", encoding="utf-8")
            result = load_supporting_transcript(path)
        self.assertEqual(result["blocks"], [{"start": 1.0, "end": 2.0, "text": ""}])
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
