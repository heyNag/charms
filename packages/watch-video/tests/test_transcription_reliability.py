"""Offline regressions for bounded uploads and honest partial transcription."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import groq_transcribe as groq  # noqa: E402
import network_guard  # noqa: E402


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


def response(text="speech"):
    return {"segments": [{"start": 1.0, "end": 2.0, "text": text}]}


def http_error(status):
    return HTTPError(groq.GROQ_ENDPOINT, status, "fixture", {}, io.BytesIO(b"fixture reason"))


class TranscriptionReliabilityTests(unittest.TestCase):
    def test_decimal_upload_boundary_is_checked_before_reading_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            with audio.open("wb") as handle:
                handle.truncate(24_000_001)
            with mock.patch.object(groq, "_read_key") as read_key:
                with self.assertRaisesRegex(RuntimeError, "24,000,000-byte"):
                    groq.transcribe_audio(audio)
            read_key.assert_not_called()

            with audio.open("wb") as handle:
                handle.truncate(24_000_000)
            with mock.patch.object(groq, "_post_transcription", return_value=response()) as post:
                self.assertEqual(groq.transcribe_audio(audio, api_key="test-placeholder"), response())
            post.assert_called_once()

    def test_request_checks_actual_audio_and_multipart_sizes_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"12345")
            args = dict(
                endpoint=groq.GROQ_ENDPOINT,
                key="test-placeholder",
                fields={},
                audio=audio,
                provider="groq",
                max_attempts=1,
                max_429_retries=0,
            )
            with mock.patch.object(groq, "MAX_UPLOAD_BYTES", 4), mock.patch.object(
                groq, "_multipart_body"
            ) as multipart, mock.patch.object(groq, "_open_without_redirects") as upload:
                with self.assertRaisesRegex(RuntimeError, "upload budget"):
                    groq._post_transcription(**args)
            multipart.assert_not_called()
            upload.assert_not_called()

            with mock.patch.object(groq, "MAX_MULTIPART_BYTES", 10), mock.patch.object(
                groq, "_multipart_body", return_value=(b"x" * 11, "boundary")
            ), mock.patch.object(groq, "_open_without_redirects") as upload:
                with self.assertRaisesRegex(RuntimeError, "multipart request exceeds"):
                    groq._post_transcription(**args)
            upload.assert_not_called()

    def test_http_failures_classify_chunk_stops_after_existing_retry_budget(self):
        cases = [(401, True, 1), (403, True, 1), (404, True, 1), (307, True, 1),
                 (429, True, 3), (400, False, 1), (503, False, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            for status, stop, attempts in cases:
                with self.subTest(status=status), mock.patch.object(
                    groq, "_open_without_redirects",
                    side_effect=[http_error(status) for _ in range(attempts)],
                ) as upload, mock.patch.object(groq.time, "sleep") as sleep:
                    with self.assertRaises(groq.TranscriptionError) as caught:
                        groq.transcribe_audio(audio, api_key="test-placeholder")
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(caught.exception.stop_remaining_chunks, stop)
                self.assertIn(f"HTTP {status}", str(caught.exception))
                self.assertEqual(upload.call_count, attempts)
                self.assertEqual(sleep.call_count, attempts - 1)

    def test_invalid_chunk_inputs_and_unknown_oversized_duration_are_rejected(self):
        for seconds, size, budget in (
            (0, 101, 100), (float("nan"), 101, 100), (float("inf"), 101, 100),
            (-1, 100, 100), (10, -1, 100), (10, 100, 0), (10, 100, True),
        ):
            with self.subTest(seconds=seconds, size=size, budget=budget):
                with self.assertRaises(RuntimeError):
                    groq.plan_chunks(seconds, size, budget)

    def test_rounded_chunk_boundaries_remain_contiguous(self):
        plan = groq.plan_chunks(1.0, 250, 100)
        for (offset, duration), (next_offset, _) in zip(plan, plan[1:]):
            self.assertAlmostEqual(offset + duration, next_offset)
        self.assertAlmostEqual(sum(duration for _, duration in plan), 1.0)

    def _splitter(self, sizes_for_attempt):
        attempts = []

        def split(_audio, directory, plan):
            attempts.append(plan)
            directory.mkdir(parents=True, exist_ok=True)
            chunks = []
            for index, (offset, _duration) in enumerate(plan):
                path = directory / f"chunk_{index:03d}.mp3"
                path.write_bytes(b"x" * sizes_for_attempt(len(attempts), index, len(plan)))
                chunks.append((path, offset))
            return chunks

        return split, attempts

    def test_actual_oversized_chunks_are_resplit_before_any_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 250)
            split, attempts = self._splitter(
                lambda attempt, index, count: 101 if attempt == 1 and index == count - 1 else 50
            )

            def transcribe(path, **kwargs):
                self.assertEqual(len(attempts), 2)
                self.assertLessEqual(path.stat().st_size, 100)
                self.assertEqual(kwargs["provider"], "openai")
                return response()

            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(groq, "transcribe_audio", side_effect=transcribe) as upload:
                segments, warnings = groq.transcribe_with_chunking(
                    audio, max_bytes=100, provider="openai"
                )
            self.assertEqual(len(attempts), 2)
            self.assertGreater(len(attempts[1]), len(attempts[0]))
            self.assertEqual(upload.call_count, len(attempts[1]))
            self.assertEqual(len(segments), upload.call_count)
            self.assertEqual(warnings, [])

    def test_split_retry_limit_prevents_every_upload_if_any_chunk_stays_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 250)
            split, attempts = self._splitter(
                lambda attempt, index, count: 101 if index == count - 1 else 10
            )
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(groq, "transcribe_audio") as upload:
                with self.assertRaisesRegex(RuntimeError, "no chunks were uploaded"):
                    groq.transcribe_with_chunking(audio, max_bytes=100)
            self.assertEqual(len(attempts), groq.MAX_SPLIT_ATTEMPTS)
            upload.assert_not_called()

    def test_partial_chunks_keep_source_offsets_gaps_and_raw_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 250)
            raw = Path(tmp) / "raw.json"
            split, _ = self._splitter(lambda *args: 90)
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(
                groq, "transcribe_audio",
                side_effect=[response("first"), RuntimeError("fixture failure"), response("third")],
            ):
                segments, warnings = groq.transcribe_with_chunking(
                    audio, max_bytes=100, offset_seconds=600, out_json=raw
                )
            self.assertEqual([segment["start"] for segment in segments], [601, 621])
            self.assertEqual(segments.gaps, [{"start": 610, "end": 620}])
            self.assertFalse(segments.no_speech)
            self.assertIn("chunk 2/3 failed", warnings[0])
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["gaps"], segments.gaps)
            self.assertEqual([chunk["index"] for chunk in saved["chunks"]], [1, 3])

    def test_permanent_http_failure_stops_uploads_and_keeps_partial_evidence(self):
        for status, retries in ((401, 1), (429, 3)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / "audio.mp3"
                audio.write_bytes(b"x" * 250)
                raw = Path(tmp) / "raw.json"
                split, _ = self._splitter(lambda *args: 90)
                replies = [io.BytesIO(json.dumps(response("first")).encode())]
                replies.extend(http_error(status) for _ in range(retries))
                with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                    groq, "split_audio", side_effect=split
                ), mock.patch.object(groq, "_open_without_redirects", side_effect=replies) as upload, mock.patch.object(
                    groq, "_multipart_body", wraps=groq._multipart_body
                ) as multipart, mock.patch.object(groq.time, "sleep"):
                    segments, warnings = groq.transcribe_with_chunking(
                        audio, max_bytes=100, offset_seconds=600, out_json=raw, api_key="test-placeholder",
                    )
                self.assertEqual(upload.call_count, 1 + retries)
                self.assertEqual(multipart.call_count, 1 + retries)
                self.assertEqual([segment["text"] for segment in segments], ["first"])
                self.assertEqual(segments[0]["start"], 601)
                self.assertEqual(segments.gaps, [{"start": 610, "end": 620}, {"start": 620, "end": 630}])
                self.assertFalse(segments.no_speech)
                self.assertIn(f"HTTP {status}", warnings[0])
                self.assertIn("not uploaded", warnings[1])
                saved = json.loads(raw.read_text())
                self.assertEqual(saved["gaps"], segments.gaps)
                self.assertEqual([chunk["index"] for chunk in saved["chunks"]], [1])

    def test_independent_http_failures_allow_later_chunks(self):
        for status, attempts in ((400, 1), (503, 4)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / "audio.mp3"
                audio.write_bytes(b"x" * 250)
                split, _ = self._splitter(lambda *args: 90)
                replies = [io.BytesIO(json.dumps(response("first")).encode())]
                replies.extend(http_error(status) for _ in range(attempts))
                replies.append(io.BytesIO(json.dumps(response("third")).encode()))
                with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                    groq, "split_audio", side_effect=split
                ), mock.patch.object(groq, "_open_without_redirects", side_effect=replies) as upload, mock.patch.object(
                    groq.time, "sleep"
                ):
                    segments, _ = groq.transcribe_with_chunking(audio, max_bytes=100, api_key="test-placeholder")
                self.assertEqual(upload.call_count, 2 + attempts)
                self.assertEqual([segment["text"] for segment in segments], ["first", "third"])
                self.assertEqual(segments.gaps, [{"start": 10, "end": 20}])

    def test_missing_key_stops_chunks_without_upload_and_preserves_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 250)
            raw = Path(tmp) / "raw.json"
            split, _ = self._splitter(lambda *args: 90)
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.dict(groq.os.environ, {}, clear=True), mock.patch.object(
                groq, "read_stored_key", return_value=None
            ), mock.patch.object(groq, "_read_key", wraps=groq._read_key) as read_key, mock.patch.object(
                groq, "_open_without_redirects"
            ) as upload:
                with self.assertRaisesRegex(groq.TranscriptionError, "GROQ_API_KEY is not set") as caught:
                    groq.transcribe_with_chunking(audio, max_bytes=100, offset_seconds=600, out_json=raw)
            read_key.assert_called_once()
            upload.assert_not_called()
            self.assertTrue(caught.exception.stop_remaining_chunks)
            self.assertIsNone(caught.exception.http_status)
            self.assertEqual(json.loads(raw.read_text())["gaps"], [
                {"start": 600, "end": 610}, {"start": 610, "end": 620}, {"start": 620, "end": 630},
            ])

    def test_empty_success_plus_failed_final_chunk_is_missing_evidence_not_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 150)
            split, _ = self._splitter(lambda *args: 80)
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(
                groq, "transcribe_audio",
                side_effect=[{"segments": []}, RuntimeError("fixture failure")],
            ):
                segments, _ = groq.transcribe_with_chunking(audio, max_bytes=100, offset_seconds=60)
            self.assertEqual(segments, [])
            self.assertEqual(segments.gaps, [{"start": 75, "end": 90}])
            self.assertFalse(segments.no_speech)

    def test_malformed_chunk_is_a_gap_and_does_not_discard_successful_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 150)
            split, _ = self._splitter(lambda *args: 80)
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(
                groq, "transcribe_audio", side_effect=[response(), {"text": "untimed text"}]
            ):
                segments, warnings = groq.transcribe_with_chunking(audio, max_bytes=100)
            self.assertEqual(len(segments), 1)
            self.assertEqual(segments.gaps, [{"start": 15, "end": 30}])
            self.assertIn("malformed", warnings[0])

    def test_all_failed_chunks_raise_instead_of_reporting_no_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"x" * 150)
            split, _ = self._splitter(lambda *args: 80)
            with mock.patch.object(groq, "audio_duration_seconds", return_value=30), mock.patch.object(
                groq, "split_audio", side_effect=split
            ), mock.patch.object(groq, "transcribe_audio", side_effect=RuntimeError("fixture")):
                with self.assertRaisesRegex(RuntimeError, "all 2 audio chunks: fixture"):
                    groq.transcribe_with_chunking(audio, max_bytes=100)

    def test_valid_empty_response_has_explicit_no_speech_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            with mock.patch.object(groq, "transcribe_audio", return_value={"segments": [], "text": " \n"}):
                segments, warnings = groq.transcribe_with_chunking(audio)
        self.assertEqual(segments, [])
        self.assertTrue(segments.no_speech)
        self.assertEqual(segments.gaps, [])
        self.assertEqual(warnings, [])

    def test_invalid_responses_never_acquire_invented_timestamps(self):
        cases = [None, [], {}, {"text": "untimed"}, {"segments": [], "text": "untimed"}]
        for values in (
            {"start": float("nan")}, {"end": float("inf")}, {"start": -1},
            {"start": True}, {"end": "2"}, {"start": 3}, {"text": " "}, {"end": 10 ** 400},
        ):
            segment = {"start": 1, "end": 2, "text": "speech", **values}
            cases.append({"segments": [segment]})
        cases.append({"segments": [response()["segments"][0], {"start": 0, "end": 1, "text": "late"}]})
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    groq.segments_from_response(data)

    def test_direct_transcription_also_rejects_malformed_provider_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            with mock.patch.object(groq, "_post_transcription", return_value={"text": "untimed"}):
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    groq.transcribe_audio(audio, api_key="test-placeholder")


if __name__ == "__main__":
    unittest.main()
