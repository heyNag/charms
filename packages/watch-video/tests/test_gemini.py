from __future__ import annotations

import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import Request


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS = TESTS_DIR.parent / "skills" / "watch-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS_DIR))

import gemini  # noqa: E402
import network_guard  # noqa: E402


def setUpModule() -> None:
    network_guard.install()


def tearDownModule() -> None:
    network_guard.uninstall()


KEY = "unit-test-credential-never-disclose"
YOUTUBE = "https://www.youtube.com/watch?v=qSuCPooR3E4"
SESSION = f"{gemini.API_ORIGIN}/upload/v1beta/files?upload_id=private-session"
FILE = {"name": "files/test123", "state": "ACTIVE",
        "uri": f"{gemini.API_ORIGIN}/v1beta/files/test123", "mimeType": "video/mp4"}


class Response:
    def __init__(self, body: bytes = b"", headers: dict | None = None):
        self.body = body
        self.headers = headers or {}

    def read(self, limit=-1):
        return self.body[:limit] if limit >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def response(data, headers=None):
    return Response(json.dumps(data).encode(), headers)


def completed(text="At 00:03 a menu opens.", **changes):
    return {
        "status": "completed",
        "steps": [{"type": "thought", "content": [{"type": "text", "text": "hidden thought"}]},
                  {"type": "model_output", "content": [{"type": "text", "text": text}]}],
        "usage": {"total_tokens": 321, "total_input_tokens": 200,
                  "total_thought_tokens": 21, "total_output_tokens": 100,
                  "total_tool_use_tokens": 20, "input_tokens_by_modality": [
                      {"modality": "video", "tokens": 180}, {"modality": "text", "tokens": 20}]},
        **changes,
    }


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / "sample.mp4"
        self.video.write_bytes(b"video-content" * 100)
        self.calls = []
        self.replies = []
        self.network = mock.patch.object(gemini, "_open_request", side_effect=self.open_request)
        self.network.start()
        self.addCleanup(self.network.stop)
        self.sleep = mock.patch.object(gemini.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def open_request(self, request, timeout):
        self.calls.append((request, timeout))
        if not self.replies:
            raise AssertionError("Unexpected HTTP request")
        reply = self.replies.pop(0)
        if callable(reply):
            return reply(request)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def upload_responses(self, state="ACTIVE"):
        return [Response(headers={"X-Goog-Upload-URL": SESSION}),
                response({"file": {**FILE, "state": state}})]

    def run_video(self, source=YOUTUBE, **kwargs):
        return gemini.analyze_video(source, api_key=KEY, **kwargs)

    def test_youtube_is_sent_directly_with_agentic_processing_and_no_store(self):
        self.replies = [response(completed())]
        result = self.run_video(question="Which menu opens?")
        self.assertEqual(len(self.calls), 1)
        request, timeout = self.calls[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, gemini.INTERACTIONS_URL)
        self.assertEqual(request.get_header("X-goog-api-key"), KEY)
        self.assertNotIn(KEY, request.full_url)
        self.assertEqual(payload["input"][0], {"type": "video", "uri": YOUTUBE, "processing": "agentic"})
        self.assertIn("Which menu opens?", payload["input"][1]["text"])
        self.assertIn("source-relative", payload["input"][1]["text"])
        self.assertFalse(payload["store"])
        self.assertEqual(timeout, 600)
        self.assertEqual(result["source_kind"], "youtube_url")
        self.assertEqual(result["processing"], "agentic")
        self.assertEqual(result["answer"], "At 00:03 a menu opens.")
        self.assertEqual(result["usage"]["total_tool_use_tokens"], 20)
        self.assertEqual(result["usage"]["input_tokens_by_modality"][0], {"modality": "video", "tokens": 180})
        self.assertIsNone(result["remote_file"])

    def test_focused_ranges_keep_exact_fractional_offsets(self):
        for start, end, expected in [
            (3.25, 6.125, {"type": "static", "start_offset": "3.25s", "end_offset": "6.125s"}),
            (None, 8, {"type": "static", "end_offset": "8.0s"}),
            (9, None, {"type": "static", "start_offset": "9.0s"}),
        ]:
            with self.subTest(start=start, end=end):
                self.replies = [response(completed())]
                result = self.run_video(start=start, end=end)
                self.assertEqual(json.loads(self.calls[-1][0].data)["input"][0]["processing"], expected)
                self.assertEqual(result["processing"], "static")

    def test_local_upload_streams_without_api_key_then_polls_and_deletes(self):
        def upload_body(request):
            self.assertTrue(hasattr(request.data, "read"))
            self.assertIsNone(request.get_header("X-goog-api-key"))
            self.assertEqual(int(request.get_header("Content-length")), self.video.stat().st_size)
            self.assertEqual(request.data.read(13), b"video-content")
            return response({"file": {**FILE, "state": "PROCESSING"}})
        self.replies = [Response(headers={"X-Goog-Upload-URL": SESSION}), upload_body,
                        response(FILE), response(completed()), Response()]
        result = self.run_video(self.video)
        self.assertEqual([req.method for req, _ in self.calls], ["POST", "POST", "GET", "POST", "DELETE"])
        payload = json.loads(self.calls[3][0].data)
        self.assertEqual(payload["input"][0]["uri"], FILE["uri"])
        self.assertEqual(result["remote_file"], {"name": FILE["name"], "cleanup_status": "deleted"})
        self.assertTrue(self.video.exists())

    def test_processing_failures_and_cancellation_still_delete_remote_file(self):
        for failure, kind in [
            (URLError(KEY), gemini.GeminiError),
            (Response(b"invalid JSON"), gemini.GeminiError),
            (KeyboardInterrupt(), KeyboardInterrupt),
            (response({**FILE, "state": "FAILED"}), gemini.GeminiError),
            (response({**FILE, "name": "files/different"}), gemini.GeminiError),
        ]:
            with self.subTest(failure=type(failure).__name__):
                self.calls.clear()
                self.replies = [*self.upload_responses("PROCESSING"), failure, Response()]
                with self.assertRaises(kind):
                    self.run_video(self.video)
                self.assertEqual(self.calls[-1][0].method, "DELETE")
                self.assertTrue(self.calls[-1][0].full_url.endswith("/files/test123"))

    def test_analysis_failure_still_deletes_and_records_cleanup_status(self):
        self.replies = [*self.upload_responses(), URLError("broken " + KEY), Response()]
        with self.assertRaises(gemini.GeminiError) as caught:
            self.run_video(self.video)
        self.assertEqual(caught.exception.remote_file["cleanup_status"], "deleted")
        self.assertNotIn(KEY, json.dumps(caught.exception.to_dict()))

    def test_cleanup_failure_preserves_success_and_original_error(self):
        self.replies = [*self.upload_responses(), response(completed()), URLError(KEY)]
        result = self.run_video(self.video)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["remote_file"]["cleanup_status"], "failed")
        self.assertTrue(result["warnings"])
        self.replies = [*self.upload_responses(), Response(b"bad JSON"), URLError(KEY)]
        with self.assertRaises(gemini.GeminiError) as caught:
            self.run_video(self.video)
        self.assertEqual(caught.exception.category, "response")
        self.assertTrue(caught.exception.warnings)
        self.assertNotIn(KEY, str(caught.exception))

    def test_upload_processing_deadline_is_bounded_and_cleanup_still_runs(self):
        self.replies = [*self.upload_responses("PROCESSING"), Response()]
        with mock.patch.object(gemini.time, "monotonic", side_effect=[0, 0, 0, 10]):
            with self.assertRaises(gemini.GeminiError) as caught:
                self.run_video(self.video, upload_timeout=5)
        self.assertEqual(caught.exception.category, "timeout")
        self.assertEqual(self.calls[-1][0].method, "DELETE")

    def test_untrusted_upload_destinations_receive_no_media(self):
        for url in ["https://evil.invalid/upload", "http://generativelanguage.googleapis.com/upload",
                    "https://generativelanguage.googleapis.com.evil.invalid/upload",
                    "https://user@generativelanguage.googleapis.com/upload",
                    "https://generativelanguage.googleapis.com:444/upload", "https://storage.googleapis.com/bucket"]:
            with self.subTest(url=url):
                self.calls.clear()
                self.replies = [Response(headers={"X-Goog-Upload-URL": url})]
                with self.assertRaises(gemini.GeminiError):
                    self.run_video(self.video)
                self.assertEqual(len(self.calls), 1)

    def test_invalid_provider_file_uri_is_rejected_and_known_file_deleted(self):
        self.replies = [Response(headers={"X-Goog-Upload-URL": SESSION}),
                        response({"file": {**FILE, "uri": "https://evil.invalid/video"}}), Response()]
        with self.assertRaises(gemini.GeminiError):
            self.run_video(self.video)
        self.assertEqual(self.calls[-1][0].method, "DELETE")

    def test_request_errors_are_categorized_and_never_echo_provider_text(self):
        for status, category in [(401, "auth"), (403, "auth"), (429, "quota"), (500, "service"), (400, "rejected"), (307, "redirect")]:
            with self.subTest(status=status):
                self.replies = [HTTPError("https://provider.invalid/" + KEY, status, KEY, {}, io.BytesIO(KEY.encode()))]
                with self.assertRaises(gemini.GeminiError) as caught:
                    self.run_video()
                self.assertEqual(caught.exception.category, category)
                self.assertNotIn(KEY, str(caught.exception))

    def test_invalid_api_key_reported_as_400_is_still_auth(self):
        body = json.dumps({"error": {"message": "API key not valid: " + KEY}}).encode()
        self.replies = [HTTPError(gemini.INTERACTIONS_URL, 400, "Bad Request", {}, io.BytesIO(body))]
        with self.assertRaises(gemini.GeminiError) as caught:
            self.run_video()
        self.assertEqual(caught.exception.category, "auth")
        self.assertNotIn(KEY, str(caught.exception))

    def test_provider_identifier_cannot_echo_credentials_in_metadata(self):
        name = "files/" + KEY
        info = {**FILE, "name": name, "uri": f"{gemini.API_ORIGIN}/v1beta/{name}"}
        self.replies = [Response(headers={"X-Goog-Upload-URL": SESSION}), response({"file": info}),
                        response(completed()), Response()]
        result = self.run_video(self.video)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertTrue(self.calls[-1][0].full_url.endswith(name))

    def test_response_must_be_completed_and_have_model_text(self):
        for data in [{"status": "in_progress"}, completed(steps=[]), [],
                     completed(steps=[None, {"type": "model_output", "content": "wrong"}])]:
            with self.subTest(data=data):
                self.replies = [response(data)]
                with self.assertRaises(gemini.GeminiError) as caught:
                    self.run_video()
                self.assertEqual(caught.exception.category, "response")

    def test_response_size_limit_and_redaction(self):
        self.replies = [Response(b"x" * (gemini.MAX_RESPONSE_BYTES + 1))]
        with self.assertRaises(gemini.GeminiError):
            self.run_video()
        self.replies = [response(completed("answer " + KEY))]
        self.assertEqual(self.run_video()["answer"], "answer [redacted]")

    def test_invalid_usage_values_are_not_reported_as_measurements(self):
        self.replies = [response(completed(usage={"total_tokens": True, "total_input_tokens": -1,
                                                "total_output_tokens": "100", "server_note": KEY}))]
        self.assertEqual(self.run_video()["usage"], {})

    def test_missing_credentials_never_make_request_or_read_user_configuration(self):
        with self.assertRaises(gemini.GeminiError) as caught:
            gemini.analyze_video(YOUTUBE)
        self.assertEqual(caught.exception.category, "auth")
        self.assertFalse(self.calls)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": KEY}):
            self.replies = [response(completed())]
            self.assertEqual(gemini.analyze_video(YOUTUBE)["status"], "completed")

    def test_invalid_inputs_fail_before_network(self):
        for kwargs in [{"timeout": 0}, {"timeout": float("nan")}, {"upload_timeout": float("inf")},
                       {"poll_interval": -1}, {"start": -1}, {"start": 9, "end": 8},
                       {"end": 0}, {"model": "model\n"}, {"question": 12}]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(gemini.GeminiError):
                    self.run_video(**kwargs)
                self.assertFalse(self.calls)
        for source in ["https://vimeo.com/123", self.video.with_name("missing.mp4")]:
            with self.assertRaises(gemini.GeminiError):
                self.run_video(source)
        self.video.write_bytes(b"")
        with self.assertRaises(gemini.GeminiError):
            self.run_video(self.video)
        self.assertFalse(self.calls)

    def test_youtube_recognition_does_not_match_other_hosts_or_playlists(self):
        for source in [YOUTUBE, "https://youtu.be/qSuCPooR3E4?t=3", "https://m.youtube.com/shorts/qSuCPooR3E4"]:
            self.assertTrue(gemini.is_youtube_url(source))
        for source in ["https://youtube.com.evil.invalid/watch?v=qSuCPooR3E4", "https://www.youtube.com/playlist?list=abc",
                       "https://evil@youtube.com/watch?v=qSuCPooR3E4", "https://youtu.be/too-short"]:
            self.assertFalse(gemini.is_youtube_url(source))


class RedirectTests(unittest.TestCase):
    def test_real_urllib_redirect_is_refused_without_a_second_request(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/start", headers={"x-goog-api-key": KEY})
            with self.assertRaises(gemini.GeminiError) as caught:
                gemini._open_request(request, 2)
            self.assertEqual(caught.exception.category, "redirect")
            self.assertEqual(seen, ["/start"])
            self.assertNotIn(KEY, str(caught.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
