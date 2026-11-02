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
FINAL_OUTPUT_CONTRACT = {
    "findings": [{"kind": "speech, visual, comparison, inference, or limitation",
                  "evidence_ids": ["actual frame or text record IDs from the supplied notes"],
                  "text": "One concise finding. Do not write timestamps or invent section time ranges; the script attaches exact source times."}],
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
    if not isinstance(findings, list) or not 1 <= len(findings) <= 16:
        raise ValueError("Final synthesis must contain 1 to 16 source-cited findings")
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
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Invalid final finding")
        kind = finding.get("kind")
        if kind not in {"speech", "visual", "comparison", "inference", "limitation"}:
            raise ValueError("Invalid final finding kind")
        identifiers = _strings(finding.get("evidence_ids"), "finding evidence IDs", 8, 120)
        if not identifiers or not set(identifiers) <= set(known):
            raise ValueError("Final finding cites missing evidence")
        sources = [known[identifier] for identifier in dict.fromkeys(identifiers)]
        if kind == "visual" and any(source["source"] != "frame" for source in sources):
            raise ValueError("A visual finding must cite frame observations")
        if kind == "speech" and any(source["source"] == "frame" for source in sources):
            raise ValueError("A speech finding must cite transcript records")
        if kind == "comparison" and len(sources) < 2:
            raise ValueError("A comparison must cite at least two sources")
        claim = _string(finding.get("text"), "finding", 1200, required=True)
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
