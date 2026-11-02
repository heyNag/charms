"""Visual observations retain their actual times without dropping speech evidence."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "watch-video" / "scripts"))
import local_analyze  # noqa: E402


class LocalAlignmentTests(unittest.TestCase):
    @staticmethod
    def evidence(times, *, start=0, end=60):
        return {"range": {"start_seconds": start, "end_seconds": end},
                "frames": [{"timestamp_seconds": stamp, "path": f"frame-{index}.png"}
                           for index, stamp in enumerate(times)]}

    def assert_complete_coverage(self, chunks, expected):
        self.assertEqual({frame["id"] for chunk in chunks for frame in chunk["frames"]},
                         set(expected["frame_ids"]))
        self.assertEqual({record["id"] for chunk in chunks for record in chunk["records"]},
                         set(expected["text_ids"]))

    def test_early_images_do_not_receive_later_benchmark_speech(self):
        transcript = {"source": "local_whisper", "segments": [
            {"start": 0, "end": 13.66, "text": "A title and model introduction."},
            {"start": 14.36, "end": 19.56, "text": "Earlier performance comparison."},
            {"start": 26.94, "end": 34.8, "text": "The newer engine update."},
            {"start": 44.74, "end": 53.88, "text": "This benchmark chart compares the engines."},
            {"start": 53.88, "end": 60, "text": "The chart axes and conclusion."},
        ]}
        chunks, expected, _ = local_analyze.plan_chunks(
            self.evidence([3, 5.25, 6, 9, 43.5, 45, 45.75]), transcript, {"sources": []})
        visual = [chunk for chunk in chunks if chunk["frames"]]
        early, chart = visual
        self.assertEqual(early["window"], {"start": 3.0, "end": 9.0})
        self.assertEqual(early["context_window"], {"start": 1.0, "end": 11.0})
        self.assertEqual(early["observed_frame_times"], [3.0, 5.25, 6.0, 9.0])
        self.assertEqual([record["id"] for record in early["records"]], ["primary:1.1"])
        self.assertEqual(chart["window"], {"start": 43.5, "end": 45.75})
        self.assertEqual([record["id"] for record in chart["records"]], ["primary:4.1"])
        text_only = [chunk for chunk in chunks if not chunk["frames"]]
        self.assertEqual({record["id"] for chunk in text_only for record in chunk["records"]},
                         {"primary:2.1", "primary:3.1", "primary:5.1"})
        self.assert_complete_coverage(chunks, expected)

    def test_segment_crossing_bucket_boundary_keeps_source_interval(self):
        segment = {"start": 55.25, "end": 68.75, "text": "A statement spanning the bucket boundary."}
        chunks, expected, _ = local_analyze.plan_chunks(
            self.evidence([61.25], end=120), {"source": "local_whisper", "segments": [segment]}, {})
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk["window"], {"start": 61.25, "end": 61.25})
        self.assertEqual(chunk["context_window"], {"start": 59.25, "end": 63.25})
        self.assertEqual(chunk["records"][0]["start"], 55.25)
        self.assertEqual(chunk["records"][0]["end"], 68.75)
        self.assert_complete_coverage(chunks, expected)

    def test_asr_starting_before_requested_range_is_retained_when_it_overlaps(self):
        transcript = {"source": "local_whisper", "segments": [
            {"start": 58, "end": 65, "text": "Keep this overlapping speech intact."},
            {"start": 10, "end": 20, "text": "Out of range."},
        ]}
        chunks, expected, _ = local_analyze.plan_chunks(
            self.evidence([61], start=60, end=75), transcript, {})
        self.assertEqual(chunks[0]["context_window"], {"start": 60.0, "end": 63.0})
        self.assertEqual(chunks[0]["records"][0]["start"], 58)
        self.assertEqual(expected["excluded_text_ids"], ["primary:2"])
        self.assert_complete_coverage(chunks, expected)

    def test_start_only_and_untimed_support_have_no_invented_duration(self):
        support = {"sources": [{"path": "meeting_transcript_grouped.txt", "provenance": "supplied_transcript",
                               "content_hash": "fixture-hash", "blocks": [
                                   {"start": 3, "text": "Earlier speaker block."},
                                   {"start": 44, "text": "Nearby speaker block."},
                                   {"text": "Untimed supporting detail."}]}]}
        chunks, expected, warnings = local_analyze.plan_chunks(self.evidence([45]), {}, support)
        visual = next(chunk for chunk in chunks if chunk["frames"])
        self.assertEqual([record["text"] for record in visual["records"]], ["Nearby speaker block."])
        for chunk in chunks:
            for record in chunk["records"]:
                self.assertNotIn("end", record)
                self.assertEqual(record["role"], "supporting")
                self.assertEqual(record["provenance"], "supplied_transcript")
                self.assertEqual(record["source_path"], "meeting_transcript_grouped.txt")
                self.assertEqual(record["source_hash"], "fixture-hash")
            if not chunk["frames"]:
                self.assertIsNone(chunk["window"]["end"])
        untimed = next(chunk for chunk in chunks if chunk["untimed_support"])
        self.assertEqual(untimed["window"], {"start": None, "end": None})
        self.assertTrue(any("Untimed" in warning for warning in warnings))
        self.assert_complete_coverage(chunks, expected)

    def test_long_overflowing_text_is_lossless_without_reusing_every_frame(self):
        original = "A long technical statement. " * 900
        support_text = "A distinct supplied transcript. " * 300
        transcript = {"source": "local_whisper", "segments": [{"start": 0, "end": 60, "text": original}]}
        support = {"sources": [{"path": "meeting.srt", "provenance": "native_captions", "blocks": [
            {"start": 1, "end": 60, "text": support_text}]}]}
        chunks, expected, _ = local_analyze.plan_chunks(self.evidence([3, 45]), transcript, support,
                                                      max_frames_per_chunk=1, max_text_chars=2000)
        self.assertEqual(sum(len(chunk["frames"]) for chunk in chunks), 2)
        unique = {record["id"]: record for chunk in chunks for record in chunk["records"]}
        for role, source_text in (("primary", original), ("supporting", support_text)):
            parts = sorted((record for record in unique.values() if record["role"] == role),
                           key=lambda record: record["part"])
            self.assertEqual("".join(record["text"] for record in parts), source_text)
        self.assertTrue(all(len(json.dumps(chunk["records"])) <= 2100 for chunk in chunks))
        self.assertTrue(all(record["provenance"] == "native_captions"
                            for record in unique.values() if record["role"] == "supporting"))
        self.assert_complete_coverage(chunks, expected)

    def test_text_only_timing_uses_known_segment_bounds(self):
        transcript = {"source": "local_whisper", "segments": [
            {"start": 26.94, "end": 34.8, "text": "An entire speech segment, not an audio gap."}]}
        chunks, expected, _ = local_analyze.plan_chunks(self.evidence([]), transcript, {})
        self.assertEqual(chunks[0]["window"], {"start": 26.94, "end": 34.8})
        self.assertEqual(chunks[0]["observed_frame_times"], [])
        self.assert_complete_coverage(chunks, expected)


if __name__ == "__main__":
    unittest.main()
