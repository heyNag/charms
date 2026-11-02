"""Local analysis keeps complete, bounded evidence and reports failures honestly."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from http.client import HTTPResponse
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "skills" / "watch-video" / "scripts"))
import local_analyze  # noqa: E402
import local_api  # noqa: E402
import network_guard  # noqa: E402
import watch  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


def completion(text="The model settings are visible.", finish="stop"):
    return {"_fixture_text": True,
            "choices": [{"finish_reason": finish, "message": {"content": text}}],
            "usage": {"prompt_tokens": 321, "completion_tokens": 25}}


def response_for_payload(payload, response, known_ids=None):
    """Use the caller's actual evidence IDs while keeping service fixtures terse."""
    if not response.get("_fixture_text"):
        return response
    response = copy.deepcopy(response)
    response.pop("_fixture_text")
    choice = response["choices"][0]
    message = choice["message"]
    note = message["content"]
    if choice["finish_reason"] != "stop" or not note:
        return response
    content = payload["messages"][1]["content"]
    if isinstance(content, list):
        request = json.loads(content[0]["text"])
        if known_ids is not None:
            known_ids.extend(frame["id"] for frame in request.get("observed_frames", []))
            known_ids.extend(record["id"] for record in request.get("records", []))
        message["content"] = json.dumps({
            "observations": [{"frame_id": frame["id"], "description": note[:1200],
                              "visible_text": "", "uncertainty": ""}
                             for frame in request.get("observed_frames", [])],
            "speech_summary": note[:3000] if request.get("records") else "",
            "comparisons": [], "uncertainties": [],
        })
    elif isinstance(content, str):
        request = json.loads(content)
        if request.get("final_output_contract"):
            evidence_ids = [source_id for entry in request["notes"]
                            for source_id in entry.get("source_ids", [])]
            evidence_ids = evidence_ids or known_ids or []
            message["content"] = json.dumps({"findings": [
                {"kind": "inference", "evidence_ids": evidence_ids[:1], "text": note[:1200]}
            ]})
    return response


class ResponseMock(mock.Mock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._evidence_ids = []

    def __call__(self, *args, **kwargs):
        response = super().__call__(*args, **kwargs)
        return response_for_payload(args[1], response, self._evidence_ids)


def two_stage_groups(notes):
    """Exercise intermediate and final calls without depending on prose length."""
    return [notes[:2], notes[2:]] if len(notes) > 2 else [notes]


class LocalAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        self.client = mock.Mock()
        self.client.request_json = ResponseMock()
        self.client.request_json.return_value = completion()
        self.factory = self.enterContext(mock.patch.object(local_analyze, "LocalClient", return_value=self.client))
        self.image = self.root / "frame.png"
        self.image.write_bytes(b"unit-image-placeholder")
        self.evidence = {"source": "meeting.mp4", "range": {"start_seconds": 0, "end_seconds": 120},
                         "frames": [{"path": str(self.image), "timestamp_seconds": 3.25}], "warnings": []}
        self.transcript = {"source": "local_whisper", "segments": [{"start": 2, "end": 5,
                           "text": "The original audio says Splash."}], "gaps": []}
        self.support = {"sources": [{"path": "meeting.txt", "provenance": "supplied_transcript",
                        "blocks": [{"start": 2, "text": "The supplied text says Flash."}]}]}
        self.save_inputs()

    def save_inputs(self):
        for filename, value in (("evidence.json", self.evidence), ("transcript.json", self.transcript),
                                ("supporting_transcripts.json", self.support)):
            (self.root / filename).write_text(json.dumps(value))

    def run_analysis(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return local_analyze.analyze_local(self.root, **kwargs)

    def test_full_hour_all_frames_and_speech_are_bounded_and_covered(self):
        evidence = {"range": {"start_seconds": 0, "end_seconds": 3600}, "frames": [
            {"timestamp_seconds": n * 12, "path": str(self.image)} for n in range(300)]}
        transcript = {"source": "local_whisper", "segments": [
            {"start": n * 5, "end": n * 5 + 4, "text": f"Original speech {n}."} for n in range(720)]}
        chunks, expected, _ = local_analyze.plan_chunks(evidence, transcript, {"sources": []})
        self.assertEqual(len(expected["frame_ids"]), 300)
        self.assertEqual(len(expected["primary_text_ids"]), 720)
        self.assertEqual({f["id"] for c in chunks for f in c["frames"]}, set(expected["frame_ids"]))
        self.assertEqual({r["id"] for c in chunks for r in c["records"]}, set(expected["text_ids"]))
        self.assertTrue(all(len(chunk["frames"]) <= 4 for chunk in chunks))
        self.assertTrue(all(len(json.dumps(c["records"])) < 16000 for c in chunks))
        self.assertIn(3588, [f["timestamp_seconds"] for c in chunks for f in c["frames"]])

    def test_huge_untimed_transcript_is_preserved_without_invented_times(self):
        original = "A speech block with no time. " * 4000
        support = {"sources": [{"path": "meeting.txt", "blocks": [{"text": original}]}]}
        chunks, expected, warnings = local_analyze.plan_chunks(self.evidence, self.transcript, support)
        records = [r for chunk in chunks for r in chunk["records"] if r["role"] == "supporting"]
        self.assertEqual("".join(r["text"] for r in records), original)
        self.assertEqual(len(records), len(expected["supporting_text_ids"]))
        self.assertTrue(all("start" not in r and "end" not in r for r in records))
        self.assertTrue(any("Untimed" in warning for warning in warnings))

    def test_matching_txt_is_secondary_and_source_timestamps_are_exact(self):
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["coverage"]["original_audio_asr"])
        payload = self.client.request_json.call_args_list[0].args[1]
        text = payload["messages"][1]["content"][0]["text"]
        self.assertIn("The original audio says Splash.", text)
        self.assertIn("The supplied text says Flash.", text)
        parsed = json.loads(text)
        self.assertEqual([record["role"] for record in parsed["records"]], ["primary", "supporting"])
        self.assertNotIn("end", parsed["records"][1])
        self.assertEqual(result["chunks"][0]["frames"][0]["timestamp_seconds"], 3.25)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payload["max_tokens"], 3072)
        self.assertEqual(self.client.request_json.call_args_list[-1].args[1]["max_tokens"], 8192)
        self.assertTrue((self.root / "local_analysis.md").exists())

    def test_native_captions_are_included_once_when_same_srt(self):
        self.support["sources"][0]["path"] = "meeting.srt"
        self.save_inputs()
        (self.root / "native_captions.json").write_text(json.dumps({"caption_path": "meeting.srt", "segments": [
            {"start": 2, "end": 5, "text": "This duplicate should not be analyzed twice."}]}))
        result = self.run_analysis()
        self.assertEqual(len(result["coverage"]["expected"]["supporting_text_ids"]), 1)
        (self.root / "native_captions.json").write_text(json.dumps({"caption_path": "download.en.vtt", "segments": [
            {"start": 2, "end": 5, "text": "An independent caption source."}]}))
        result = self.run_analysis()
        self.assertEqual(len(result["coverage"]["expected"]["supporting_text_ids"]), 2)

    def test_complete_chunks_reuse_but_changed_image_invalidates_cache(self):
        self.run_analysis()
        self.client.reset_mock()
        reused = self.run_analysis()
        self.client.request_json.assert_not_called()
        self.assertTrue(reused["chunks"][0]["reused"])
        self.image.write_bytes(b"different-image-pixels")
        changed = self.run_analysis()
        self.assertFalse(changed["chunks"][0]["reused"])
        self.assertEqual(self.client.request_json.call_count, 1)  # Same generated text permits synthesis reuse.

    def test_cached_result_cannot_be_reused_for_other_model_or_question(self):
        self.run_analysis()
        self.client.reset_mock()
        self.run_analysis(model="other-model", question="Read the label precisely")
        self.assertEqual(self.client.request_json.call_count, 2)

    def test_partial_output_not_cached_as_complete_or_claimed_full_coverage(self):
        self.client.request_json.side_effect = [completion("Truncated note", "length"), completion()]
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["missing_frame_ids"], ["frame:1"])
        self.assertTrue(result["coverage"]["missing_text_ids"])
        self.client.request_json.side_effect = None
        self.client.reset_mock()
        self.run_analysis()
        self.assertGreaterEqual(self.client.request_json.call_count, 1)

    def test_failure_stops_unchanged_requests_and_redacts_secret(self):
        self.evidence["frames"].append({"path": str(self.image), "timestamp_seconds": 80})
        self.save_inputs()
        secret = "unit-key-must-not-be-recorded"
        self.client.request_json.side_effect = RuntimeError(f"server error {secret}")
        result = self.run_analysis(api_key=secret)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.client.request_json.call_count, 1)
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes())

    def test_interrupted_response_preserves_completed_chunks_and_resumes(self):
        self.evidence["range"]["end_seconds"] = 180
        self.evidence["frames"].extend([
            {"path": str(self.image), "timestamp_seconds": 80},
            {"path": str(self.image), "timestamp_seconds": 140},
        ])
        self.save_inputs()
        secret = "unit-key-must-not-be-recorded"
        client = local_api.LocalClient(api_key=secret)
        self.factory.return_value = client
        known_ids = []

        def complete_response(request, **kwargs):
            reply = response_for_payload(json.loads(request.data), completion(), known_ids)
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(reply).encode()
            return response

        # Exercise the actual stdlib chunk decoder, not merely a mocked error:
        # the server disconnects in the middle of its first chunk.
        wire = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n100\r\n"
                + b"private partial body " + secret.encode())
        interrupted_response = HTTPResponse(mock.Mock(makefile=mock.Mock(return_value=io.BytesIO(wire))))
        interrupted_response.begin()
        responses = iter([complete_response, lambda *_args, **_kwargs: interrupted_response])
        with mock.patch.object(client._opener, "open",
                               side_effect=lambda *args, **kwargs: next(responses)(*args, **kwargs)) as opened:
            result = self.run_analysis(api_key=secret)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([chunk["status"] for chunk in result["chunks"]], ["complete", "error"])
        self.assertTrue(result["chunks"][1]["stop_remaining"])
        self.assertEqual(result["synthesis"], [])
        self.assertEqual(result["coverage"]["missing_frame_ids"], ["frame:2", "frame:3"])
        self.assertTrue((self.root / "local_analysis.md").exists())
        for path in self.root.rglob("*.json"):
            self.assertNotIn(secret, path.read_text())
            self.assertNotIn("private partial body", path.read_text())
        with mock.patch.object(client._opener, "open", side_effect=complete_response) as resumed:
            result = self.run_analysis(api_key=secret)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(resumed.call_count, 3)  # Two unfinished windows, then synthesis.
        self.assertEqual([chunk["reused"] for chunk in result["chunks"]], [True, False, False])
        self.assertEqual(result["coverage"]["missing_frame_ids"], [])

    def test_missing_original_asr_or_gaps_are_not_full_success(self):
        self.transcript["source"] = "native_captions"
        self.save_inputs()
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["coverage"]["original_audio_asr"])
        self.transcript["source"] = "local_whisper"
        self.transcript["gaps"] = [{"start": 12, "end": 22, "reason": "decode failure"}]
        self.save_inputs()
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["asr_gaps"], self.transcript["gaps"])

    def test_empty_asr_is_not_success_unless_valid_no_speech(self):
        self.transcript["segments"] = []
        self.save_inputs()
        self.assertEqual(self.run_analysis()["status"], "partial")
        self.transcript["no_speech"] = True
        self.save_inputs()
        self.assertEqual(self.run_analysis()["status"], "complete")

    def test_explicit_no_audio_scope_can_complete_without_asr_claim(self):
        self.transcript["source"] = "native_captions"
        self.save_inputs()
        (self.root / "metadata.json").write_text(json.dumps({
            "transcriber": "none", "original_audio": {"requested": False},
            "visual_evidence_requested": True,
        }))
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["coverage"]["original_audio_asr"])
        self.assertFalse(result["coverage"]["original_audio_requested"])
        self.assertEqual(result["coverage"]["original_audio_status"], "not_requested")
        self.assertIn("original audio not requested", result["audio_representation"])
        report = (self.root / "local_analysis.md").read_text()
        self.assertNotIn("Audio evidence is independent ASR", report)
        self.assertFalse(any("missing" in warning for warning in result["warnings"]))

    def test_partial_metadata_does_not_waive_original_audio_requirement(self):
        self.transcript["source"] = "native_captions"
        self.save_inputs()
        for metadata in ({"transcriber": "none"}, {"original_audio": {"requested": False}},
                         {"transcriber": "local", "original_audio": {"requested": False}}):
            with self.subTest(metadata=metadata):
                (self.root / "metadata.json").write_text(json.dumps(metadata))
                self.assertEqual(self.run_analysis()["status"], "partial")

    def test_requested_visual_pass_without_frames_is_partial(self):
        self.evidence["frames"] = []
        self.save_inputs()
        for metadata in ({"visual_evidence_requested": True},
                         {"frames": {"enabled": True, "detail": "balanced"}}):
            with self.subTest(metadata=metadata):
                (self.root / "metadata.json").write_text(json.dumps(metadata))
                result = self.run_analysis()
                self.assertEqual(result["status"], "partial")
                self.assertTrue(result["coverage"]["visual_evidence_requested"])
                self.assertTrue(any("no usable video frames" in warning for warning in result["warnings"]))
        (self.root / "metadata.json").write_text(json.dumps({
            "visual_evidence_requested": False, "frames": {"enabled": True, "detail": "balanced"}}))
        self.assertEqual(self.run_analysis()["status"], "complete")

    def test_real_watch_explicit_none_with_frames_and_srt_succeeds(self):
        video = self.root / "meeting.mp4"
        video.write_bytes(b"synthetic video")
        video.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:02:00,000\nSupplied caption.\n")
        self.enterContext(mock.patch.object(watch, "require_tool"))
        self.enterContext(mock.patch.object(watch, "ffprobe_metadata", return_value={
            "duration_seconds": 120, "width": 1280, "height": 720, "has_audio": True}))
        self.enterContext(mock.patch.object(watch, "extract_scene_frames", return_value=(
            [{"path": str(self.image), "timestamp_seconds": 3.25, "timestamp": "00:03"}], {})))
        self.enterContext(mock.patch.object(watch, "run_command", side_effect=AssertionError("unexpected command")))
        self.enterContext(mock.patch.object(watch, "extract_audio_clip", side_effect=AssertionError("unexpected hosted audio")))
        self.enterContext(mock.patch.object(watch.local_transcribe, "extract_audio_clip", side_effect=AssertionError("unexpected local audio")))
        self.enterContext(mock.patch.object(watch, "transcribe_with_chunking", side_effect=AssertionError("unexpected hosted ASR")))
        self.enterContext(mock.patch.object(watch.local_transcribe, "transcribe_with_chunking", side_effect=AssertionError("unexpected local ASR")))
        self.enterContext(mock.patch.object(watch.gemini, "analyze_video", side_effect=AssertionError("unexpected Gemini")))
        output = self.root / "integration-runs"
        with mock.patch.object(sys, "argv", ["watch.py", str(video), "--out-dir", str(output),
                                           "--analyzer", "local", "--transcriber", "none"]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main()
        self.assertEqual(code, 0)
        run = next(output.iterdir())
        analysis = json.loads((run / "local_analysis.json").read_text())
        self.assertEqual(analysis["status"], "complete")
        self.assertFalse(analysis["coverage"]["original_audio_asr"])
        self.assertEqual(analysis["coverage"]["original_audio_status"], "not_requested")
        self.assertEqual(analysis["coverage"]["missing_frame_ids"], [])
        self.assertTrue(analysis["coverage"]["expected"]["supporting_text_ids"])
        self.assertGreaterEqual(self.client.request_json.call_count, 2)

    def test_synthesis_error_stops_before_later_groups_or_merge_depths(self):
        self.evidence["range"]["end_seconds"] = 180
        self.evidence["frames"] = [{"path": str(self.image), "timestamp_seconds": stamp} for stamp in (3, 70, 130)]
        self.save_inputs()
        self.client.request_json.side_effect = [
            completion(), completion(), completion(), completion("First group consolidated."),
            RuntimeError("service stopped"),
        ]
        with mock.patch.object(local_analyze, "DIRECT_EVIDENCE_CHAR_BUDGET", 0), \
                mock.patch.object(local_analyze, "_summary_groups", side_effect=two_stage_groups):
            result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.client.request_json.call_count, 5)
        self.assertEqual(len(result["synthesis"]), 2)
        self.assertEqual(result["text"], "")
        self.assertTrue(any("no further synthesis" in warning for warning in result["warnings"]))

    def test_larger_final_budget_preserves_intermediate_payloads_and_resumes_only_final(self):
        self.evidence["range"]["end_seconds"] = 180
        self.evidence["frames"] = [{"path": str(self.image), "timestamp_seconds": stamp}
                                   for stamp in (3, 70, 130)]
        self.save_inputs()
        self.client.request_json.side_effect = [
            *[completion() for _ in range(3)],
            completion("Consolidated first group."), completion("Consolidated second group."),
            completion("Truncated final answer.", "length"),
        ]
        self.enterContext(mock.patch.object(local_analyze, "DIRECT_EVIDENCE_CHAR_BUDGET", 0))
        self.enterContext(mock.patch.object(local_analyze, "_summary_groups", side_effect=two_stage_groups))
        with mock.patch.object(local_analyze, "FINAL_SYNTHESIS_MAX_TOKENS", 4096):
            partial = self.run_analysis()
        self.assertEqual(partial["status"], "partial")
        payloads = [call.args[1] for call in self.client.request_json.call_args_list]
        intermediate = payloads[3:5]
        self.assertEqual(len(partial["synthesis"]), 3)
        for payload in intermediate:
            self.assertEqual(payload["max_tokens"], 4096)
            self.assertTrue(json.loads(payload["messages"][1]["content"])["notes"])
        old_hashes = [result["request_hash"] for result in partial["synthesis"][:2]]
        self.client.reset_mock()
        self.client.request_json.side_effect = None
        self.client.request_json.return_value = completion("Concise complete final answer.")
        resumed = self.run_analysis()
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(self.client.request_json.call_count, 1)
        final_payload = self.client.request_json.call_args.args[1]
        self.assertEqual(final_payload["max_tokens"], 8192)
        self.assertEqual([result["request_hash"] for result in resumed["synthesis"][:2]], old_hashes)
        self.assertTrue(all(result["reused"] for result in resumed["chunks"]))
        self.assertTrue(all(result["reused"] for result in resumed["synthesis"][:2]))
        self.assertFalse(resumed["synthesis"][-1]["reused"])

    def test_final_length_limit_remains_partial_with_complete_evidence_coverage(self):
        self.client.request_json.side_effect = [completion(), completion("Still truncated.", "length")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["missing_frame_ids"], [])
        self.assertEqual(result["coverage"]["missing_text_ids"], [])
        self.assertEqual(result["synthesis"][-1]["status"], "partial")
        self.assertTrue(result["synthesis"][-1]["truncated"])
        self.assertEqual(self.client.request_json.call_args.args[1]["max_tokens"], 8192)

    def test_invalid_final_source_is_partial_and_only_synthesis_is_retried(self):
        invalid = completion(json.dumps({"findings": [
            {"kind": "visual", "evidence_ids": ["frame:999"], "text": "An unsupported observation."}
        ]}))
        invalid.pop("_fixture_text")
        self.client.request_json.side_effect = [completion(), invalid]
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["coverage"]["missing_frame_ids"], [])
        self.assertEqual(result["synthesis"][-1]["status"], "partial")
        self.assertIn("validation_error", result["synthesis"][-1])

        self.client.reset_mock()
        self.client.request_json.side_effect = None
        resumed = self.run_analysis()
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(self.client.request_json.call_count, 1)
        self.assertTrue(resumed["chunks"][0]["reused"])
        self.assertFalse(resumed["synthesis"][-1]["reused"])
        self.assertNotIn("An unsupported observation.", resumed["text"])

    def test_missing_frame_remains_explicit_even_when_text_succeeds(self):
        self.image.unlink()
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["missing_frame_ids"], ["frame:1"])

    def test_reasoning_without_final_answer_is_error(self):
        self.client.request_json.return_value = {"choices": [{"message": {"content": None, "reasoning_content": "internal reasoning"}, "finish_reason": "stop"}]}
        result = self.run_analysis()
        self.assertEqual(result["status"], "error")
        self.assertNotIn("internal reasoning", json.dumps(result))

    def test_length_limited_reasoning_only_reply_is_explicit_partial(self):
        self.client.request_json.return_value = {"choices": [{"message": {
            "content": None, "reasoning_content": "Unfinished internal reasoning must not be evidence"},
            "finish_reason": "length"}], "usage": {"completion_tokens": 3072}}
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["chunks"][0]["status"], "partial")
        self.assertEqual(result["chunks"][0]["finish_reason"], "length")
        self.assertTrue(result["chunks"][0]["truncated"])
        self.assertNotIn("stop_remaining", result["chunks"][0])
        self.assertNotIn("Unfinished internal reasoning", json.dumps(result))
        self.assertEqual(result["text"], "")
        self.assertEqual(result["coverage"]["analyzed_frame_ids"], [])
        self.assertEqual(self.client.request_json.call_count, 1)
        self.client.reset_mock()
        self.client.request_json.return_value = completion()
        retried = self.run_analysis()
        self.assertEqual(retried["status"], "complete")
        self.assertEqual(self.client.request_json.call_count, 2)

    def test_chunk_source_presence_and_synthesis_gaps_follow_actual_evidence(self):
        self.evidence["range"]["end_seconds"] = 180
        self.evidence["frames"] = [{"path": str(self.image), "timestamp_seconds": stamp} for stamp in (3, 70, 130)]
        self.support["sources"][0]["blocks"].append({"start": 65, "text": "Supplied-only evidence without ASR."})
        self.transcript["gaps"] = [{"start": 60, "end": 180, "reason": "ASR unavailable"}]
        self.save_inputs()
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        requests = [call.args[1] for call in self.client.request_json.call_args_list]
        chunks = [json.loads(payload["messages"][1]["content"][0]["text"])
                  for payload in requests if isinstance(payload["messages"][1]["content"], list)]
        by_frames = {tuple(frame["id"] for frame in chunk["observed_frames"]): chunk for chunk in chunks}
        self.assertEqual(len(chunks), 4)
        self.assertEqual({ids: (chunk["has_primary_asr"], chunk["has_supporting"])
                          for ids, chunk in by_frames.items()},
                         {("frame:1",): (True, True), (): (False, True),
                          ("frame:2",): (False, False), ("frame:3",): (False, False)})
        self.assertEqual(by_frames[()]["records"][0]["start"], 65)
        self.assertNotIn("end", by_frames[()]["records"][0])
        synthesis = json.loads(requests[-1]["messages"][1]["content"])
        self.assertEqual(synthesis["asr_gaps"], self.transcript["gaps"])
        self.assertTrue(synthesis["original_audio_requested"])
        self.assertTrue(synthesis["direct_source_evidence"])
        records = json.loads(synthesis["notes"][0]["text"])["records"]
        self.assertEqual(len(records), 3)
        self.assertEqual(sorted(record["start"] for record in records), [2, 2, 65])
        self.assertEqual({record["provenance"] for record in records},
                         {"local_whisper", "supplied_transcript"})
        self.assertFalse(result["chunks"][1]["has_primary_asr"])

    def test_model_synthesis_batches_long_notes_without_dropping_text(self):
        notes = [{"id": f"chunk-{n}", "text": (f"Evidence {n}. " * 600)} for n in range(20)]
        groups = local_analyze._summary_groups(notes)
        recovered = "".join(part["text"] for group in groups for part in group)
        self.assertEqual(recovered, "".join(note["text"] for note in notes))
        self.assertTrue(all(sum(len(json.dumps(part)) for part in group) <= 18500 for group in groups))


if __name__ == "__main__":
    unittest.main()
