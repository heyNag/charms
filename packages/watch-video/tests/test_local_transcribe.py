"""Local inference privacy and original-audio ASR regression tests."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from http.client import BadStatusLine, IncompleteRead, RemoteDisconnected
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent / "skills" / "watch-video" / "scripts"))

import local_api as api  # noqa: E402
import local_transcribe as asr  # noqa: E402
import network_guard  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


def response(text="Independent audio words"):
    return {"text": text, "segments": [{"start": 1.5, "end": 2.5, "text": text}]}


class LocalClientTests(unittest.TestCase):
    def test_localhost_is_pinned_and_ipv6_is_supported(self):
        self.assertEqual(api.validate_base_url("http://localhost:8147/"), api.DEFAULT_BASE_URL)
        self.assertEqual(api.validate_base_url("http://[::1]:8147/v1/"), "http://[::1]:8147/v1")
        self.assertEqual(api.validate_base_url("http://127.0.0.2:8080"), "http://127.0.0.2:8080/v1")

    def test_remote_ambiguous_credential_urls_are_rejected_without_echo(self):
        for url in ["https://api.example.com/v1", "http://192.168.1.2/v1",
                    "http://0.0.0.0/v1", "http://127.1/v1", "http://2130706433/v1",
                    "http://localhost.evil/v1", "http://secret@localhost/v1",
                    "http://localhost/v1?api_key=secret", "http://localhost/v1#secret",
                    "http://localhost:0/v1", "http://[::ffff:127.0.0.1]/v1",
                    "file:///tmp/file", "http://localhost/elsewhere", "http://localhost\n/v1"]:
            with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                api.validate_base_url(url)
            self.assertNotIn("secret", str(caught.exception))

    def test_proxy_disabled_and_key_only_in_authorization(self):
        opener = mock.Mock()
        opened = mock.MagicMock()
        opened.__enter__.return_value.read.return_value = b'{"text":"ok"}'
        opener.open.return_value = opened
        with mock.patch.object(api, "build_opener", return_value=opener) as build:
            client = api.LocalClient(api_key="test-local-secret")
            self.assertEqual(client.request_json("chat/completions", {"model": "fixture"}), {"text": "ok"})
        self.assertIsInstance(build.call_args.args[0], ProxyHandler)
        self.assertEqual(build.call_args.args[0].proxies, {})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-local-secret")
        self.assertNotIn(b"test-local-secret", request.data)
        self.assertNotIn("test-local-secret", request.full_url)

    def test_endpoint_cannot_escape_origin(self):
        client = api.LocalClient(api_key="fixture")
        for path in ["https://elsewhere/v1", "//elsewhere", "../admin", "models/../admin",
                     "models/./admin", "models?key=fixture", ""]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.request_json(path)

    def test_dotted_model_identifier_is_a_valid_endpoint_segment(self):
        client = api.LocalClient(api_key="fixture")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with mock.patch.object(client._opener, "open", return_value=response) as opened:
            client.request_json("models/Qwen3.6-35B-A3B-4bit/unload", {})
        self.assertEqual(opened.call_args.args[0].full_url,
                         client.base_url + "/models/Qwen3.6-35B-A3B-4bit/unload")

    def test_no_redirect_retry_or_error_echo(self):
        client = api.LocalClient(api_key="secret-fixture")
        for status in [302, 307, 400, 401, 503]:
            error = HTTPError(client.base_url, status, "secret-fixture", {}, io.BytesIO(b"secret-fixture"))
            with self.subTest(status=status), mock.patch.object(client._opener, "open", side_effect=error) as opened:
                with self.assertRaises(api.LocalAPIError) as caught:
                    client.get_models()
                self.assertEqual(opened.call_count, 1)
                self.assertNotIn("secret-fixture", str(caught.exception))
                self.assertEqual(caught.exception.http_status, status)
                self.assertTrue(caught.exception.stop_remaining_chunks)
        with self.assertRaises(HTTPError) as caught:
            api._RefuseRedirects().redirect_request(mock.Mock(full_url=client.base_url), None, 307, "", {}, "http://example.com")
        caught.exception.close()

    def test_successful_response_echo_is_redacted(self):
        client = api.LocalClient(api_key="secret-fixture")
        opened = mock.MagicMock()
        opened.__enter__.return_value.read.return_value = b'{"text":"echo secret-fixture", "nested":["secret-fixture"]}'
        with mock.patch.object(client._opener, "open", return_value=opened):
            self.assertNotIn("secret-fixture", json.dumps(client.get_models()))

    def test_malformed_or_oversized_body_and_transport_errors_are_safe(self):
        client = api.LocalClient(api_key="secret-fixture")
        for data in [b"secret-fixture", b"[]", b"x" * (api.MAX_RESPONSE_BYTES + 1)]:
            opened = mock.MagicMock()
            opened.__enter__.return_value.read.return_value = data
            with self.subTest(size=len(data)), mock.patch.object(client._opener, "open", return_value=opened):
                with self.assertRaises(api.LocalAPIError) as caught:
                    client.get_models()
                self.assertNotIn("secret-fixture", str(caught.exception))
        with mock.patch.object(client._opener, "open", side_effect=URLError("secret-fixture")):
            with self.assertRaises(api.LocalAPIError) as caught:
                client.get_models()
            self.assertNotIn("secret-fixture", str(caught.exception))

    def test_http_protocol_errors_stop_without_partial_body_or_exception_echo(self):
        client = api.LocalClient(api_key="secret-fixture")
        errors = [IncompleteRead(b"private partial response secret-fixture", 100),
                  BadStatusLine("private malformed status secret-fixture"),
                  RemoteDisconnected("private disconnect reason secret-fixture")]
        for error in errors:
            opened = mock.MagicMock()
            opened.__enter__.return_value.read.side_effect = error
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(client._opener, "open", return_value=opened) as request:
                with self.assertRaises(api.LocalAPIError) as caught:
                    client.request_json("chat/completions", {"model": "fixture"})
                self.assertTrue(caught.exception.stop_remaining_chunks)
                self.assertIsNone(caught.exception.http_status)
                self.assertNotIn("secret-fixture", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))
                self.assertEqual(request.call_count, 1)
                opened.__exit__.assert_called_once()


class LocalTranscriptionTests(unittest.TestCase):
    def test_default_model_respects_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(asr.default_model(), asr.DEFAULT_ASR_MODEL)
        with mock.patch.dict(os.environ, {"WATCH_VIDEO_LOCAL_ASR_MODEL": "another-local-model"}):
            self.assertEqual(asr.default_model(), "another-local-model")

    def test_pcm_extraction_has_no_lossy_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / "source.mp4", Path(tmp) / "audio.wav"
            source.write_bytes(b"video")
            def run(command, **_kwargs):
                out.write_bytes(b"wav" * 100)
                self.assertIn("pcm_s16le", command)
                self.assertIn("16000", command)
                self.assertNotIn("libmp3lame", command)
                self.assertEqual(command[command.index("-map") + 1], "0:a:0")
                self.assertEqual(command[command.index("-t") + 1], "10.000000")
                return mock.Mock(returncode=0)
            with mock.patch.object(asr.shutil, "which", return_value="/ffmpeg"), mock.patch.object(asr.subprocess, "run", side_effect=run):
                self.assertEqual(asr.extract_audio_clip(source, out, start=3, end=13), out.resolve())

    def test_no_caption_prompt_and_empty_omlx_response_is_valid_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"audio")
            client = mock.Mock()
            client.request_json.return_value = {"text": "", "segments": None}
            self.assertEqual(asr.transcribe_audio(audio, client=client)["segments"], [])
            request = client.request_json.call_args
            self.assertEqual(request.args[0], "audio/transcriptions")
            self.assertNotIn(b'name="prompt"', request.kwargs["body"])
            self.assertIn(asr.DEFAULT_ASR_MODEL.encode(), request.kwargs["body"])

    def test_text_only_and_out_of_range_timestamps_are_not_silence_or_invented(self):
        for data in [{"text": "speech", "segments": None}, {},
                     {"text": "speech", "segments": []},
                     {"text": "speech", "segments": [{"start": 4, "end": 100, "text": "speech"}]}]:
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                asr._validated_response(data, duration=30)

    def _split(self, source, output, **_kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"chunk-audio")
        return output

    def test_chunk_success_offsets_and_evidence_cover_full_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=650), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split) as split, \
                    mock.patch.object(asr, "transcribe_audio", return_value=response()) as transcribe:
                segments, warnings = asr.transcribe_with_chunking(audio, out_json=raw, offset_seconds=12)
            self.assertEqual([s["start"] for s in segments], [13.5, 313.5, 613.5])
            self.assertEqual([c.kwargs["duration"] for c in split.call_args_list], [300, 300, 50])
            self.assertEqual(transcribe.call_count, 3)
            self.assertEqual(warnings, [])
            self.assertEqual(segments.gaps, [])
            self.assertFalse(segments.no_speech)
            self.assertEqual(json.loads(raw.read_text())["chunk_count"], 3)

    def test_partial_failure_preserves_previous_chunks_and_remaining_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=650), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=[response(), api.LocalAPIError("Local API request rejected (HTTP 401).", http_status=401)]) as transcribe:
                segments, warnings = asr.transcribe_with_chunking(audio, out_json=raw, offset_seconds=12)
            self.assertEqual(transcribe.call_count, 2)
            self.assertEqual(len(segments), 1)
            self.assertEqual(segments.gaps, [{"start": 312, "end": 612}, {"start": 612, "end": 662}])
            self.assertFalse(segments.no_speech)
            self.assertEqual(len(warnings), 2)
            self.assertEqual(json.loads(raw.read_text())["gaps"], segments.gaps)

    def test_all_failed_saves_gaps_before_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=30), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=RuntimeError("unsafe response")):
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw)
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["gaps"], [{"start": 0, "end": 30}])
            self.assertFalse(saved["no_speech"])
            self.assertNotIn("unsafe response", raw.read_text())

    def test_wrong_model_http400_stops_hour_long_recording_after_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            client = api.LocalClient(api_key="test-placeholder")
            error = HTTPError(client.base_url, 400, "model is not speech-to-text", {}, io.BytesIO())
            with mock.patch.object(asr, "audio_duration_seconds", return_value=3600), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "LocalClient", return_value=client), \
                    mock.patch.object(client._opener, "open", side_effect=error) as opened:
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw, model="vision-model")
            self.assertEqual(opened.call_count, 1)
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["chunk_count"], 12)
            self.assertEqual(len(saved["gaps"]), 12)
            self.assertEqual(saved["gaps"][-1], {"start": 3300, "end": 3600})
            self.assertEqual(len(saved["chunks"]), 1)
            self.assertFalse(saved["no_speech"])

    def test_validation_failure_retains_redacted_raw_response_and_specific_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            client = api.LocalClient(api_key="secret-fixture")
            invalid = {"text": "secret-fixture", "segments": [
                {"start": 10, "end": 112, "text": "secret-fixture"},
            ]}
            opened = mock.MagicMock()
            opened.__enter__.return_value.read.return_value = json.dumps(invalid).encode()
            with mock.patch.object(asr, "audio_duration_seconds", return_value=109.493), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "LocalClient", return_value=client), \
                    mock.patch.object(client._opener, "open", return_value=opened):
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw)
            saved = json.loads(raw.read_text())
            self.assertIn("timestamps beyond the audio chunk", saved["chunks"][0]["error"])
            self.assertEqual(saved["chunks"][0]["response"]["segments"][0]["end"], 112)
            self.assertEqual(saved["gaps"], [{"start": 0, "end": 54.746}, {"start": 54.746, "end": 109.493}])
            self.assertEqual(saved["chunks"][0]["recovery"]["status"], "partial")
            self.assertNotIn("secret-fixture", raw.read_text())
            self.assertIn("[REDACTED]", raw.read_text())

    def test_timestamp_shape_failure_retains_response_before_transcribe_audio_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            client = mock.Mock(base_url=api.DEFAULT_BASE_URL)
            client.request_json.return_value = {"text": "words without timestamps", "segments": None}
            with mock.patch.object(asr, "audio_duration_seconds", return_value=30), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "LocalClient", return_value=client):
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw)
            record = json.loads(raw.read_text())["chunks"][0]
            self.assertIn("segments array", record["error"])
            self.assertEqual(record["response"], client.request_json.return_value)
            self.assertEqual(client.request_json.call_count, 3)

    def test_malformed_chunk_recovers_once_without_repeating_valid_neighbors(self):
        invalid = {"text": "discard this", "segments": [{"start": 176.78, "end": 176.28, "text": "discard this"}]}
        replies = [response("before"), invalid, *[response(f"recovery {i}") for i in range(5)], response("after")]
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=650), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split) as split, \
                    mock.patch.object(asr, "transcribe_audio", side_effect=replies) as transcribe:
                segments, warnings = asr.transcribe_with_chunking(audio, out_json=raw, offset_seconds=12)
            self.assertEqual(transcribe.call_count, 8)
            self.assertEqual([s["text"] for s in segments], ["before", *[f"recovery {i}" for i in range(5)], "after"])
            self.assertEqual([s["start"] for s in segments], [13.5, 313.5, 373.5, 433.5, 493.5, 553.5, 613.5])
            self.assertEqual([c.kwargs["start"] for c in split.call_args_list], [0, 300, 300, 360, 420, 480, 540, 600])
            self.assertEqual([c.kwargs["duration"] for c in split.call_args_list], [300, 300, 60, 60, 60, 60, 60, 50])
            self.assertEqual(len({c.args[1] for c in split.call_args_list}), 8)
            self.assertEqual(segments.gaps, [])
            self.assertFalse(segments.no_speech)
            self.assertEqual(len(warnings), 1)
            saved = json.loads(raw.read_text())
            parent = saved["chunks"][1]
            self.assertEqual(parent["response"], invalid)
            self.assertEqual(parent["status"], "recovered")
            self.assertEqual(parent["recovery"]["status"], "complete")
            self.assertEqual(parent["recovery"]["chunk_count"], 5)
            self.assertEqual([c["offset_seconds"] for c in parent["recovery"]["chunks"]], [300, 360, 420, 480, 540])
            self.assertEqual(saved["chunks"][0]["response"], replies[0])
            self.assertEqual(saved["chunks"][2]["response"], replies[-1])

    def test_recovery_keeps_successful_children_and_only_marks_failed_intervals(self):
        reversed_times = {"text": "bad", "segments": [{"start": 10, "end": 9, "text": "bad"}]}
        beyond_end = {"text": "bad", "segments": [{"start": 1, "end": 61, "text": "bad"}]}
        replies = [reversed_times, response("first"), reversed_times, response("third"), beyond_end,
                   response("fifth"), response("next original")]
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=600), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=replies) as transcribe:
                segments, _warnings = asr.transcribe_with_chunking(audio, out_json=raw, offset_seconds=7)
            self.assertEqual(transcribe.call_count, 7)  # No recursive subdivision of failed children.
            self.assertEqual([s["start"] for s in segments], [8.5, 128.5, 248.5, 308.5])
            self.assertEqual(segments.gaps, [{"start": 67, "end": 127}, {"start": 187, "end": 247}])
            parent = json.loads(raw.read_text())["chunks"][0]
            self.assertEqual(parent["status"], "partial")
            self.assertEqual(len(parent["recovery"]["chunks"]), 5)
            self.assertEqual(parent["recovery"]["chunks"][1]["response"], reversed_times)
            self.assertEqual(parent["recovery"]["chunks"][3]["response"], beyond_end)

    def test_fatal_recovery_error_stops_all_remaining_requests(self):
        invalid = {"text": "missing segments"}
        denial = api.LocalAPIError("Local API request rejected (HTTP 401).", http_status=401)
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=900), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=[response("before"), invalid, response("recovered"), denial]) as transcribe:
                segments, _warnings = asr.transcribe_with_chunking(audio, out_json=raw, offset_seconds=12)
            self.assertEqual(transcribe.call_count, 4)
            self.assertEqual([s["start"] for s in segments], [13.5, 313.5])
            self.assertEqual(segments.gaps, [{"start": 372, "end": 432}, {"start": 432, "end": 492},
                                           {"start": 492, "end": 552}, {"start": 552, "end": 612},
                                           {"start": 612, "end": 912}])
            saved = json.loads(raw.read_text())
            self.assertEqual(len(saved["chunks"]), 2)
            children = saved["chunks"][1]["recovery"]["chunks"]
            self.assertEqual(len(children), 2)
            self.assertNotIn("response", children[1])

    def test_recovery_fatal_error_preserves_status_when_every_attempt_failed(self):
        denial = api.LocalAPIError("Local API request rejected (HTTP 403).", http_status=403)
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=600), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=[{"text": "missing segments"}, denial]) as transcribe:
                with self.assertRaises(asr.TranscriptionError) as caught:
                    asr.transcribe_with_chunking(audio, out_json=raw)
            self.assertEqual(transcribe.call_count, 2)
            self.assertEqual(caught.exception.http_status, 403)
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["gaps"], [{"start": i * 60, "end": (i + 1) * 60} for i in range(5)]
                             + [{"start": 300, "end": 600}])

    def test_recovered_silence_counts_as_completed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=30), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split) as split, \
                    mock.patch.object(asr, "transcribe_audio", side_effect=[{"text": "missing segments"},
                        {"text": "", "segments": None}, {"text": "", "segments": []}]) as transcribe:
                segments, _warnings = asr.transcribe_with_chunking(audio, out_json=raw)
            self.assertEqual(transcribe.call_count, 3)
            self.assertEqual([c.kwargs["duration"] for c in split.call_args_list], [15, 15])
            self.assertEqual(segments, [])
            self.assertTrue(segments.no_speech)
            self.assertEqual(segments.gaps, [])
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["chunks"][0]["status"], "recovered")
            self.assertTrue(saved["chunked"])

    def test_repeated_validation_failure_has_a_finite_recovery_budget(self):
        invalid = {"text": "bad", "segments": [{"start": 10, "end": 9, "text": "bad"}]}
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=300), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", return_value=invalid) as transcribe:
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw)
            self.assertEqual(transcribe.call_count, 6)
            saved = json.loads(raw.read_text())
            self.assertEqual(saved["gaps"], [{"start": i * 60, "end": (i + 1) * 60} for i in range(5)])
            self.assertEqual(len(saved["chunks"][0]["recovery"]["chunks"]), 5)

    def test_submillisecond_boundary_does_not_create_empty_recovery_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=0.001), \
                    mock.patch.object(asr, "transcribe_audio", return_value={"text": "missing segments"}) as transcribe, \
                    mock.patch.object(asr, "extract_audio_clip") as split:
                with self.assertRaises(asr.TranscriptionError):
                    asr.transcribe_with_chunking(audio, out_json=raw)
            self.assertEqual(transcribe.call_count, 1)
            split.assert_not_called()
            self.assertEqual(json.loads(raw.read_text())["gaps"], [{"start": 0, "end": 0.001}])

    def test_failure_without_response_never_reuses_previous_chunks_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, raw = Path(tmp) / "audio.wav", Path(tmp) / "raw.json"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=600), \
                    mock.patch.object(asr, "extract_audio_clip", side_effect=self._split), \
                    mock.patch.object(asr, "transcribe_audio", side_effect=[response(), api.LocalAPIError("Local connection failed.")]):
                segments, _warnings = asr.transcribe_with_chunking(audio, out_json=raw)
            saved = json.loads(raw.read_text())
            self.assertEqual(len(segments), 1)
            self.assertIn("response", saved["chunks"][0])
            self.assertNotIn("response", saved["chunks"][1])

    def test_completed_silence_not_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"audio")
            with mock.patch.object(asr, "audio_duration_seconds", return_value=30), \
                    mock.patch.object(asr, "transcribe_audio", return_value={"text": "", "segments": None}):
                segments, warnings = asr.transcribe_with_chunking(audio)
            self.assertEqual(segments, [])
            self.assertTrue(segments.no_speech)
            self.assertEqual(segments.gaps, [])
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
