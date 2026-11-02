"""Source-bound observations survive summarization and cannot invent references."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "skills" / "watch-video" / "scripts"))
import local_analyze  # noqa: E402
import local_observations  # noqa: E402
import network_guard  # noqa: E402


def setUpModule():
    network_guard.install()


def tearDownModule():
    network_guard.uninstall()


def structured(identifier="frame:1", description="A benchmark chart is visible."):
    return {"observations": [{"frame_id": identifier, "description": description,
                              "visible_text": "Qwen3.6-35B", "uncertainty": ""}],
            "speech_summary": "", "comparisons": [], "uncertainties": []}


def reply(value):
    return {"choices": [{"message": {"content": value if isinstance(value, str) else json.dumps(value)},
                         "finish_reason": "stop"}]}


def final_reply(text):
    return reply({"findings": [{"kind": "inference", "evidence_ids": ["frame:1"], "text": text}]})


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.frames = [{"id": "frame:1", "timestamp_seconds": 45.75}]
        self.records = [{"id": "primary:1.1", "start": 44.74, "end": 53.88, "text": "A chart."}]

    def parse(self, value):
        return local_observations.parse_observations(json.dumps(value), self.frames, self.records)

    def test_manifest_time_wins_over_model_time(self):
        value = structured()
        value["observations"][0]["timestamp_seconds"] = 3
        result = self.parse(value)
        self.assertEqual(result["observations"][0]["timestamp_seconds"], 45.75)

    def test_missing_duplicate_and_unknown_frames_are_rejected(self):
        for observations in ([], [structured("frame:99")["observations"][0]],
                             structured()["observations"] * 2):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                self.parse({**structured(), "observations": observations})

    def test_unknown_comparison_reference_is_rejected(self):
        value = structured()
        value["comparisons"] = [{"evidence_ids": ["primary:999"], "description": "Invented comparison"}]
        with self.assertRaises(ValueError):
            self.parse(value)

    def test_bounded_response_and_prose_validation(self):
        with self.assertRaises(ValueError):
            self.parse(structured(description="x" * 1201))
        with self.assertRaises(ValueError):
            local_observations.parse_observations("A plausible but unstructured answer.", self.frames, self.records)

    def test_code_fence_is_supported_without_accepting_surrounding_prose(self):
        result = local_observations.parse_observations("```json\n" + json.dumps(structured()) + "\n```",
                                                     self.frames, self.records)
        self.assertEqual(result["observations"][0]["frame_id"], "frame:1")
        with self.assertRaises(ValueError):
            local_observations.parse_observations("Here is JSON:\n" + json.dumps(structured()), self.frames, self.records)

    def test_large_lineage_stays_out_of_bounded_prompt_fragments(self):
        identifiers = [f"primary:{n}.1" for n in range(720)] + [f"frame:{n}" for n in range(300)]
        notes = [{"id": "synthesis-1", "text": "A source finding. " * 1000, "source_ids": identifiers}]
        groups = local_analyze._summary_groups(notes)
        self.assertTrue(all(sum(len(json.dumps(part, ensure_ascii=False)) for part in group) <= 18000
                            for group in groups))
        self.assertEqual("".join(part["text"] for group in groups for part in group), notes[0]["text"])
        self.assertTrue(all(part["source_note_id"] == "synthesis-1" for group in groups for part in group))
        self.assertEqual(notes[0]["source_ids"], identifiers)

    def test_final_times_are_from_sources_and_unknown_references_fail(self):
        finding = {"kind": "comparison", "evidence_ids": ["frame:1", "primary:1.1"],
                   "text": "The chart corroborates the speech.", "start": 2}
        parsed = local_observations.parse_findings(json.dumps({"findings": [finding]}),
                                                   self.parse(structured())["observations"], self.records)
        rendered = local_observations.render_findings(parsed)
        self.assertIn("00:45.750", rendered)
        self.assertIn("00:44.740–00:53.880", rendered)
        self.assertNotIn("00:02", rendered)
        finding["evidence_ids"] = ["frame:999"]
        with self.assertRaises(ValueError):
            local_observations.parse_findings(json.dumps({"findings": [finding]}), [], self.records)

    def test_speech_cannot_be_labeled_as_a_visual_observation(self):
        value = {"findings": [{"kind": "visual", "evidence_ids": ["primary:1.1"], "text": "A chart."}]}
        with self.assertRaises(ValueError):
            local_observations.parse_findings(json.dumps(value), [], self.records)

    def test_final_text_must_list_every_explicit_source_reference(self):
        observations = self.parse(structured())["observations"] + [
            {"frame_id": "frame:2", "timestamp_seconds": 46.5}]
        records = [*self.records,
                   {"id": "supporting:2:1.1", "text": "Supplied text."},
                   {"id": "caption:custom", "text": "Another identified source."}]
        for identifier in ("frame:2", "primary:1.1", "supporting:2:1.1", "caption:custom"):
            finding = {"kind": "inference", "evidence_ids": ["frame:1"],
                       "text": f"The claim also refers to `{identifier}`."}
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "absent from evidence_ids"):
                local_observations.parse_findings(json.dumps({"findings": [finding]}), observations, records)

    def test_unknown_numeric_source_mentions_are_rejected(self):
        observations = self.parse(structured())["observations"]
        for identifier in ("frame:999", "primary:77.2", "supporting:9.2", "supporting:9:2.1"):
            finding = {"kind": "inference", "evidence_ids": ["frame:1"],
                       "text": f"The result is confirmed by {identifier}."}
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "absent from evidence_ids"):
                local_observations.parse_findings(json.dumps({"findings": [finding]}), observations, self.records)

    def test_complete_reference_mentions_and_ordinary_text_are_allowed(self):
        observations = self.parse(structured())["observations"]
        records = [*self.records, {"id": "supporting:1:1.1", "text": "Supplied text."}]
        findings = [
            {"kind": "comparison", "evidence_ids": ["frame:1", "primary:1.1", "supporting:1:1.1"],
             "text": "Compare `frame:1`, (primary:1.1), and supporting:1:1.1. The frame:1 label is readable."},
            {"kind": "visual", "evidence_ids": ["frame:1"],
             "text": "The chart names a 35B model, version 3.6, and has a keyframe:123 label."},
        ]
        result = local_observations.parse_findings(json.dumps({"findings": findings}), observations, records)
        self.assertEqual([finding["text"] for finding in result], [finding["text"] for finding in findings])

    def test_final_contract_and_parser_enforce_the_same_size_boundaries(self):
        frames = [{"frame_id": f"frame:{i}", "timestamp_seconds": i} for i in range(1, 10)]
        value = {"findings": [{"kind": "visual", "evidence_ids": [f"frame:{i}" for i in range(1, 9)],
                               "text": "x" * 1200} for _ in range(16)]}
        validator = Draft202012Validator(local_observations.FINAL_OUTPUT_CONTRACT)
        validator.validate(value)
        self.assertEqual(len(local_observations.parse_findings(json.dumps(value), frames, [])), 16)
        oversized = []
        more_findings = copy.deepcopy(value)
        more_findings["findings"].append(copy.deepcopy(value["findings"][0]))
        oversized.append(more_findings)
        more_ids = copy.deepcopy(value)
        more_ids["findings"][0]["evidence_ids"].append("frame:9")
        oversized.append(more_ids)
        long_text = copy.deepcopy(value)
        long_text["findings"][0]["text"] += "x"
        oversized.append(long_text)
        for invalid in oversized:
            with self.subTest(invalid=invalid["findings"][0]["evidence_ids"]):
                self.assertTrue(list(validator.iter_errors(invalid)))
                with self.assertRaises(ValueError):
                    local_observations.parse_findings(json.dumps(invalid), frames, [])
        for empty in ([], [{"kind": "visual", "evidence_ids": [], "text": "x"}],
                      [{"kind": "visual", "evidence_ids": ["frame:1"], "text": " "}]):
            self.assertTrue(list(validator.iter_errors({"findings": empty})))
            with self.assertRaises(ValueError):
                local_observations.parse_findings(json.dumps({"findings": empty}), frames, [])

    def test_final_kind_rules_require_correct_sources_and_distinct_comparison_ids(self):
        frames = self.parse(structured())["observations"]
        valid = {"speech": ["primary:1.1"], "visual": ["frame:1"],
                 "comparison": ["frame:1", "primary:1.1"], "inference": ["frame:1"],
                 "limitation": ["primary:1.1"]}
        for kind, identifiers in valid.items():
            value = {"findings": [{"kind": kind, "evidence_ids": identifiers, "text": "A finding."}]}
            self.assertEqual(local_observations.parse_findings(json.dumps(value), frames, self.records)[0]["kind"], kind)
        for kind, identifiers in (("speech", ["frame:1"]), ("visual", ["primary:1.1"]),
                                  ("comparison", ["frame:1", "frame:1"]), ("unsupported", ["frame:1"])):
            value = {"findings": [{"kind": kind, "evidence_ids": identifiers, "text": "A finding."}]}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                local_observations.parse_findings(json.dumps(value), frames, self.records)


class ObservationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        self.image = self.root / "chart.png"
        self.image.write_bytes(b"mock frame bytes")
        for name, value in {
            "evidence.json": {"source": "sample.mp4", "range": {"start_seconds": 0, "end_seconds": 60},
                              "frames": [{"path": str(self.image), "timestamp_seconds": 45.75}]},
            "transcript.json": {"source": "local_whisper", "gaps": [],
                                "segments": [{"start": 44.74, "end": 53.88, "text": "Here is the chart."}]},
            "metadata.json": {"visual_evidence_requested": True},
        }.items():
            (self.root / name).write_text(json.dumps(value))
        self.client = mock.Mock()
        self.enterContext(mock.patch.object(local_analyze, "LocalClient", return_value=self.client))

    def run_analysis(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return local_analyze.analyze_local(self.root, **kwargs)

    def test_source_anchored_chart_survives_bad_final_summary(self):
        self.client.request_json.side_effect = [reply(structured()), final_reply("No chart is visible anywhere.")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")  # Processing, not semantic correctness.
        self.assertEqual(result["quality"]["status"], "requires_source_review")
        self.assertEqual(result["synthesis_mode"], "direct_evidence")
        self.assertEqual(result["coverage"]["sampled_visual_coverage"], {
            "count": 1, "first_timestamp_seconds": 45.75, "last_timestamp_seconds": 45.75,
            "requested_range": {"start_seconds": 0, "end_seconds": 60}, "continuous_coverage": False,
        })
        request = json.loads(self.client.request_json.call_args_list[1].args[1]["messages"][1]["content"])
        canonical = json.loads(request["notes"][0]["text"])
        self.assertEqual(canonical["observations"][0]["timestamp_seconds"], 45.75)
        self.assertEqual(canonical["records"][0]["text"], "Here is the chart.")
        self.assertEqual(request["asr_gaps"], [])
        report = (self.root / "local_analysis.md").read_text()
        self.assertIn("00:45.750", report)
        self.assertIn("A benchmark chart is visible.", report)
        self.assertIn("No chart is visible anywhere.", report)
        self.assertIn("does not establish factual accuracy", report)

    def test_invalid_observations_do_not_claim_frame_or_text_coverage_and_can_resume(self):
        self.client.request_json.return_value = reply(structured("frame:999"))
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["analyzed_frame_ids"], [])
        self.assertEqual(result["coverage"]["analyzed_text_ids"], [])
        self.assertEqual(self.client.request_json.call_count, 1)
        self.client.reset_mock()
        self.client.request_json.side_effect = [reply(structured()), final_reply("A chart appears.")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["chunks"][0]["reused"])
        self.assertEqual(self.client.request_json.call_count, 2)

    def test_schema_failures_stop_after_two_consecutive_batches(self):
        evidence = json.loads((self.root / "evidence.json").read_text())
        evidence["range"]["end_seconds"] = 180
        evidence["frames"] = [{"path": str(self.image), "timestamp_seconds": n} for n in (45.75, 90, 135)]
        (self.root / "evidence.json").write_text(json.dumps(evidence))
        self.client.request_json.return_value = reply("Not the required JSON")
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.client.request_json.call_count, 2)
        self.assertEqual(result["synthesis"], [])
        self.assertTrue(result["chunks"][-1]["stop_remaining"])

    def test_escaped_key_echo_is_removed_before_parsed_observations_are_saved(self):
        secret = 'unit-quoted-"-key'
        payload = json.dumps(structured(description="Visible " + secret))
        payload = payload.replace("unit", "\\u0075nit")
        for fenced in (False, True):
            value = "```json\n" + payload + "\n```" if fenced else payload
            with self.subTest(fenced=fenced):
                self.client.request_json.side_effect = [reply(value), final_reply("A chart appears.")]
                with contextlib.redirect_stdout(io.StringIO()):
                    result = local_analyze.analyze_local(self.root, api_key=secret, refresh=True)
                self.assertEqual(result["status"], "complete")
                self.assertIn("[REDACTED]", result["observations"][0]["description"])
                for path in self.root.rglob("*.json"):
                    self.assertNotIn(secret, str(json.loads(path.read_text())))
                self.assertNotIn(secret, (self.root / "local_analysis.md").read_text())

    def test_invalid_final_id_repairs_once_preserves_draft_and_reuses_repaired_cache(self):
        rejected = reply({"findings": [{"kind": "limitation", "evidence_ids": ["asr_gaps"],
                                        "text": "An unsupported reference."}]})
        self.client.request_json.side_effect = [reply(structured()), rejected, final_reply("A chart appears.")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.client.request_json.call_count, 3)
        final = result["synthesis"][-1]
        self.assertEqual(final["repair"]["attempts"], 1)
        self.assertEqual(final["repair"]["status"], "complete")
        initial = json.loads(Path(final["repair"]["rejected_response_path"]).read_text())
        self.assertEqual(initial["status"], "partial")
        self.assertIn("asr_gaps", initial["text"])
        repaired = json.loads(Path(final["repair"]["response_path"]).read_text())
        self.assertEqual(repaired["status"], "complete")
        payloads = [call.args[1] for call in self.client.request_json.call_args_list]
        first_request, repair_request = [json.loads(p["messages"][1]["content"]) for p in payloads[1:]]
        self.assertEqual(repair_request["notes"], first_request["notes"])
        self.assertEqual(repair_request["final_output_contract"], first_request["final_output_contract"])
        self.assertIn("cites missing evidence", repair_request["schema_repair"]["validation_error"])
        self.assertLess(len(json.dumps(repair_request)) - len(json.dumps(first_request)), 1000)
        self.client.reset_mock()
        self.client.request_json.side_effect = AssertionError("A complete repaired result should be reused")
        resumed = self.run_analysis()
        self.assertEqual(resumed["status"], "complete")
        self.client.request_json.assert_not_called()
        self.assertTrue(resumed["synthesis"][-1]["reused"])
        self.assertEqual(resumed["quality"]["status"], "requires_source_review")

    def test_excess_final_citations_are_repaired_without_silent_truncation(self):
        transcript_path = self.root / "transcript.json"
        transcript = json.loads(transcript_path.read_text())
        transcript["segments"] *= 8
        transcript_path.write_text(json.dumps(transcript))
        identifiers = ["frame:1", *[f"primary:{i}.1" for i in range(1, 9)]]
        rejected = reply({"findings": [{"kind": "inference", "evidence_ids": identifiers, "text": "A long citation list."}]})
        self.client.request_json.side_effect = [reply(structured()), rejected, final_reply("A focused chart finding.")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.client.request_json.call_count, 3)
        final = result["synthesis"][-1]
        self.assertIn("1 to 8", final["repair"]["initial_validation_error"])
        initial = json.loads(Path(final["repair"]["rejected_response_path"]).read_text())
        self.assertEqual(json.loads(initial["text"])["findings"][0]["evidence_ids"], identifiers)
        self.assertEqual(result["findings"][0]["text"], "A focused chart finding.")

    def test_failed_final_repair_is_bounded_and_preserves_complete_evidence(self):
        invalid = reply({"findings": [{"kind": "visual", "evidence_ids": ["frame:999"], "text": "Bad source."}]})
        self.client.request_json.side_effect = [reply(structured()), invalid, invalid]
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.client.request_json.call_count, 3)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["coverage"]["missing_frame_ids"], [])
        self.assertEqual(result["coverage"]["missing_text_ids"], [])
        self.assertEqual(result["synthesis"][-1]["repair"]["status"], "partial")
        repair = json.loads(Path(result["synthesis"][-1]["repair"]["response_path"]).read_text())
        self.assertEqual(repair["status"], "partial")

    def test_incomplete_or_service_failed_final_does_not_trigger_schema_repair(self):
        truncated = final_reply("An incomplete answer.")
        truncated["choices"][0]["finish_reason"] = "length"
        for response in (truncated, RuntimeError("access denied")):
            with self.subTest(response=response):
                self.client.reset_mock()
                self.client.request_json.side_effect = [reply(structured()), response]
                result = self.run_analysis(refresh=True)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(self.client.request_json.call_count, 2)
                self.assertNotIn("repair", result["synthesis"][-1])

    def test_service_failure_during_repair_stops_and_retains_rejected_draft(self):
        invalid = reply({"findings": [{"kind": "visual", "evidence_ids": ["frame:999"], "text": "Bad source."}]})
        self.client.request_json.side_effect = [reply(structured()), invalid, RuntimeError("service stopped")]
        result = self.run_analysis()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.client.request_json.call_count, 3)
        final = result["synthesis"][-1]
        self.assertTrue(final["stop_remaining"])
        self.assertEqual(final["repair"]["status"], "error")
        self.assertTrue(Path(final["repair"]["rejected_response_path"]).is_file())

    def test_rejected_and_repaired_outputs_redact_escaped_secrets(self):
        secret = 'unit-quoted-"-key'
        invalid = {"findings": [{"kind": "visual", "evidence_ids": ["frame:999"], "text": "Echo " + secret}]}
        escaped = "```json\n" + json.dumps(invalid).replace("unit", "\\u0075nit") + "\n```"
        self.client.request_json.side_effect = [reply(structured()), reply(escaped), final_reply("Echo " + secret)]
        result = self.run_analysis(api_key=secret)
        self.assertEqual(result["status"], "complete")
        self.assertIn("[REDACTED]", result["text"])
        for path in self.root.rglob("*.json"):
            self.assertNotIn(secret, str(json.loads(path.read_text())))
        self.assertNotIn(secret, (self.root / "local_analysis.md").read_text())


if __name__ == "__main__":
    unittest.main()
