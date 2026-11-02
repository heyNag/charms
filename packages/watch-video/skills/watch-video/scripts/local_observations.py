"""Validate model observations and bind them to the prepared source evidence."""
from __future__ import annotations

import json
import re


SOURCE_ID_MENTION = re.compile(r"(?<![\w:])(?:frame|primary|supporting):\d+(?:[.:]\d+)*(?![\w:])")


OUTPUT_CONTRACT = {
    "observations": [{"frame_id": "one supplied frame ID", "description": "visible content, at most 40 words",
                      "visible_text": "important legible text only", "uncertainty": "unclear details, or empty"}],
    "speech_summary": "At most 60 words about the supplied speech; empty when absent.",
    "comparisons": [{"evidence_ids": ["supplied frame/text IDs"],
                     "description": "A meaningful comparison only when the actual source times align."}],
    "uncertainties": ["Evidence limitations local to this batch, not unseen portions."],
}
FINAL_MIN_FINDINGS = 1
FINAL_MAX_FINDINGS = 16
FINAL_MAX_EVIDENCE_IDS = 8
FINAL_MAX_ID_CHARS = 120
FINAL_MAX_TEXT_CHARS = 1200
FINAL_KIND_RULES = {
    "speech": {"source_type": "text", "minimum_distinct_sources": 1},
    "visual": {"source_type": "frame", "minimum_distinct_sources": 1},
    "comparison": {"source_type": "any", "minimum_distinct_sources": 2},
    "inference": {"source_type": "any", "minimum_distinct_sources": 1},
    "limitation": {"source_type": "any", "minimum_distinct_sources": 1},
}
# These are prompt instructions, not an endpoint-specific response_format.
# The same constants and kind rules below enforce the advertised contract.
FINAL_OUTPUT_CONTRACT = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {
        "type": "array", "minItems": FINAL_MIN_FINDINGS, "maxItems": FINAL_MAX_FINDINGS,
        "items": {"type": "object", "required": ["kind", "evidence_ids", "text"],
                  "properties": {
                      "kind": {"type": "string", "enum": list(FINAL_KIND_RULES)},
                      "evidence_ids": {
                          "type": "array", "minItems": 1, "maxItems": FINAL_MAX_EVIDENCE_IDS,
                          "items": {"type": "string", "minLength": 1, "maxLength": FINAL_MAX_ID_CHARS, "pattern": r"\S"},
                          "description": "Nonblank actual frame/text IDs retained in the notes only. Metadata fields such as asr_gaps and note/chunk/synthesis IDs are not evidence IDs. Every source ID mentioned in text must also appear here.",
                      },
                      "text": {"type": "string", "minLength": 1, "maxLength": FINAL_MAX_TEXT_CHARS, "pattern": r"\S",
                               "description": "One nonblank concise finding. Do not invent section time ranges; the script attaches exact source times."},
                  }},
    }},
    "kind_source_rules": FINAL_KIND_RULES,
}


def _string(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"Invalid {label} in structured evidence response")
    return value.strip()


def _strings(value, label, count, limit):
    if not isinstance(value, list) or len(value) > count:
        raise ValueError(f"Invalid {label} in structured evidence response")
    return [_string(item, label, limit, required=True) for item in value]


def parse_observations(text, frames, records):
    """Validate references, not factual truth. Source times never come from the model."""
    raw = text.strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if lines[0].strip().lower() in {"```json", "```"}:
            raw = "\n".join(lines[1:-1])
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Local model did not return the requested structured evidence JSON") from None
    if not isinstance(result, dict):
        raise ValueError("Structured evidence response must be an object")
    known_frames = {frame["id"]: frame for frame in frames}
    allowed = set(known_frames) | {record["id"] for record in records}
    observations = result.get("observations")
    if not isinstance(observations, list) or len(observations) != len(known_frames):
        raise ValueError("Structured evidence must contain one observation per supplied frame")
    seen, validated = set(), []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("Invalid frame observation")
        identifier = item.get("frame_id")
        if not isinstance(identifier, str) or identifier not in known_frames or identifier in seen:
            raise ValueError("Unknown or duplicate frame ID in structured evidence")
        seen.add(identifier)
        validated.append({
            "frame_id": identifier,
            "timestamp_seconds": known_frames[identifier]["timestamp_seconds"],
            "description": _string(item.get("description"), "description", 1200, required=True),
            "visible_text": _string(item.get("visible_text", ""), "visible text", 1000),
            "uncertainty": _string(item.get("uncertainty", ""), "visual uncertainty", 600),
        })
    comparisons = result.get("comparisons", [])
    if not isinstance(comparisons, list) or len(comparisons) > 8:
        raise ValueError("Invalid comparisons in structured evidence")
    checked_comparisons = []
    for item in comparisons:
        if not isinstance(item, dict):
            raise ValueError("Invalid comparison in structured evidence")
        identifiers = _strings(item.get("evidence_ids"), "comparison evidence IDs", 12, 120)
        if not identifiers or not set(identifiers) <= allowed:
            raise ValueError("Comparison cites missing evidence")
        checked_comparisons.append({"evidence_ids": identifiers,
                                    "description": _string(item.get("description"), "comparison", 700, required=True)})
    return {"observations": sorted(validated, key=lambda item: item["timestamp_seconds"]),
            "speech_summary": _string(result.get("speech_summary", ""), "speech summary", 3000),
            "comparisons": checked_comparisons,
            "uncertainties": _strings(result.get("uncertainties", []), "uncertainty", 8, 400)}


def source_records(chunks):
    """Deduplicate repeated context while preserving source text and known timestamps."""
    records = {}
    for chunk in chunks:
        for record in chunk["records"]:
            records.setdefault(record["id"], {key: record[key] for key in
                ("id", "role", "provenance", "start", "end", "text", "source_path") if key in record})
    return list(records.values())


def observation_lines(observations):
    """A complete source-anchored ledger independent of any prose synthesis."""
    lines = ["## Frame observations (local model interpretation)", "",
             "Timestamps are from the extracted frames. Descriptions still require source review.", ""]
    for item in observations:
        stamp = item["timestamp_seconds"]
        minutes, seconds = divmod(stamp, 60)
        lines.append(f"- **{int(minutes):02d}:{seconds:06.3f} · {item['frame_id']}** — {item['description']}")
        if item["visible_text"]:
            lines.append(f"  Visible text: {item['visible_text']}")
        if item["uncertainty"]:
            lines.append(f"  Uncertainty: {item['uncertainty']}")
    return lines + [""]


def parse_findings(text, observations, records):
    """Ground final citations in sources; this does not certify claim semantics."""
    raw = text.strip()
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if lines[0].strip().lower() in {"```json", "```"}:
            raw = "\n".join(lines[1:-1])
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("Final synthesis did not return source-cited findings JSON") from None
    findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings, list) or not FINAL_MIN_FINDINGS <= len(findings) <= FINAL_MAX_FINDINGS:
        raise ValueError(f"Final synthesis must contain {FINAL_MIN_FINDINGS} to {FINAL_MAX_FINDINGS} source-cited findings")
    known = {item["frame_id"]: {"id": item["frame_id"], "source": "frame",
                              "start": item["timestamp_seconds"]} for item in observations}
    known.update({record["id"]: {"id": record["id"], "source": record.get("provenance", "transcript"),
                                **{key: record[key] for key in ("start", "end") if key in record}}
                  for record in records})
    # Recognize actual IDs as well as obvious unknown numeric source IDs. This
    # only checks explicit citations; it does not infer which source supports
    # a claim that contains no ID or decide whether the claim is true.
    known_mentions = re.compile(r"(?<![\w:])(?:" + "|".join(
        re.escape(identifier) for identifier in sorted(known, key=len, reverse=True)
    ) + r")(?![\w:])") if known else None
    output = []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            raise ValueError(f"Finding {index} must be an object")
        kind = finding.get("kind")
        if not isinstance(kind, str) or kind not in FINAL_KIND_RULES:
            raise ValueError(f"Finding {index} kind must be one of {', '.join(FINAL_KIND_RULES)}")
        raw_ids = finding.get("evidence_ids")
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= FINAL_MAX_EVIDENCE_IDS:
            raise ValueError(f"Finding {index} evidence_ids must contain 1 to {FINAL_MAX_EVIDENCE_IDS} source IDs")
        identifiers = _strings(raw_ids, "finding evidence IDs", FINAL_MAX_EVIDENCE_IDS, FINAL_MAX_ID_CHARS)
        if not set(identifiers) <= set(known):
            raise ValueError(f"Finding {index} cites missing evidence; use only supplied frame/text IDs, not metadata fields")
        sources = [known[identifier] for identifier in dict.fromkeys(identifiers)]
        rule = FINAL_KIND_RULES[kind]
        if rule["source_type"] == "frame" and any(source["source"] != "frame" for source in sources):
            raise ValueError("A visual finding must cite frame observations")
        if rule["source_type"] == "text" and any(source["source"] == "frame" for source in sources):
            raise ValueError("A speech finding must cite transcript records")
        if len(sources) < rule["minimum_distinct_sources"]:
            raise ValueError(f"A {kind} must cite at least {rule['minimum_distinct_sources']} distinct sources")
        claim = _string(finding.get("text"), "finding", FINAL_MAX_TEXT_CHARS, required=True)
        mentioned = set(SOURCE_ID_MENTION.findall(claim))
        if known_mentions is not None:
            mentioned.update(known_mentions.findall(claim))
        if not mentioned <= set(identifiers):
            raise ValueError("Final finding mentions evidence absent from evidence_ids")
        output.append({"kind": kind, "text": claim,
                       "evidence_ids": list(dict.fromkeys(identifiers)), "sources": sources})
    return output


def render_findings(findings):
    def stamp(seconds):
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02d}:{seconds:06.3f}"

    lines = []
    for finding in findings:
        labels = []
        for source in finding["sources"]:
            time = stamp(source["start"]) if "start" in source else "untimed"
            if "end" in source:
                time += "–" + stamp(source["end"])
            labels.append(f"{time} ({source['id']}, {source['source']})")
        lines.extend([f"- **{finding['kind'].capitalize()} — {'; '.join(labels)}**", f"  {finding['text']}", ""])
    return "\n".join(lines)
