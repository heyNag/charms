"""Build task-specific worker inputs; do not claim prompt text enforces isolation."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile

from integrity import (
    RuntimeErrorBase,
    canonical,
    contained,
    digest,
    regular,
    resolve_skill,
    safe_relative,
    verify_payload,
)
from profiles import load_profile

FORBIDDEN = (
    "eval",
    "test",
    "judge",
    "experiment",
    "rubric",
    "score",
    "compare",
    "benchmark",
    "candidate",
    "arena",
)
CHAIN_CUES = re.compile(
    r"(?:list|name|report|describe|which).{0,60}(?:skills|principles|files).{0,30}(?:applied|used|followed)|which (?:skills|principles|files)",
    re.I | re.S,
)


def worker_brief(
    root: Path,
    task: str,
    *,
    role: str = "poteto-agent",
    policy: str = "ordinary",
    overrides: Path | None = None,
    verified: dict | None = None,
    config: Path | None = None,
    surface: str = "desktop",
    locator: Path | None = None,
) -> str:
    if not task.strip():
        raise RuntimeErrorBase("worker task is empty")
    verified = verified or verify_payload(root)
    if Path(verified["root"]).resolve() != root.resolve():
        raise RuntimeErrorBase("verification belongs to another root")
    if surface not in {"desktop", "cloud", "cli"}:
        raise RuntimeErrorBase("unknown worker runtime surface")
    if surface == "cloud" and locator is None:
        raise RuntimeErrorBase("Cloud workers need the parent's installation locator")
    worker = contained(root, "skills/poteto-mode/worker.md")
    regular(worker)
    if role not in {"poteto-agent", "comment-sicko", "generic"} or policy not in {
        "ordinary",
        "benny",
    }:
        raise RuntimeErrorBase("unknown worker role or authority policy")
    lines = [f"Read {worker.resolve()} before anything else.", "", task, ""]
    if role != "generic":
        role_path = contained(root, f"agents/{role}.md")
        regular(role_path)
        lines.append(f"Read the role instructions at {role_path.resolve()}.")
    if role == "poteto-agent":
        binding = resolve_skill(root, "poteto-mode", overrides=overrides, verified=verified)
        mode = Path(binding["instructions"])
        lines.append(
            f"Read the complete effective mode at {mode.resolve()} and the matched current playbook."
        )
        lines.append(
            f"Its immutable resource_root is {binding['resource_root']} in payload {binding['payload_root']}. Resolve relative helpers from that resource_root through the runtime resource command, never from the effective body's external directory."
        )
        lines.append(
            "The role's request to read poteto-mode means this effective body selected by the same resolver. Do not replace it by rereading a descriptor or unselected base body."
        )
    lines.append(
        "If you start another agent, propagate the absolute worker.md read-first line in its kickoff."
    )
    if overrides is not None:
        lines.append(
            f"Use the same approved override registry at {overrides.resolve()} for all internal and nested skill resolution."
        )
    arguments = ["--root", str(root.resolve()), "--surface", surface]
    if locator is not None:
        arguments.extend(["--locator", str(locator.resolve())])
    # Do not turn a self-consistency check into a claim of externally pinned origin.
    if verified.get("origin_verified"):
        arguments.extend(["--expected-manifest", verified["manifest_sha256"]])
    arguments.extend(
        [
            "--expected-upstream",
            verified["upstream"]["commit"],
            "--expected-version",
            verified["bundle_version"],
        ]
    )
    if config is not None:
        arguments.extend(["--config", str(config.resolve())])
        if config.exists() or config.is_symlink():
            deployment = load_profile(config)
            configured_root = deployment["profile"].get("runtime_root")
            if configured_root is not None and Path(configured_root).resolve() != root.resolve():
                raise RuntimeErrorBase("selected profile belongs to another runtime root")
            lines.append(
                f"Keep deployment profile {deployment['profile_id']} at revision {deployment['profile_revision']}; if that binding changes, stop and reconcile with the coordinator."
            )
    if overrides is not None:
        arguments.extend(["--overrides", str(overrides.resolve())])
    lines.extend(
        [
            "Append these runtime arguments to every resolve, resource and worker command. "
            "Propagate them unchanged to nested workers; do not substitute the default "
            "configuration, another surface or an unpinned installation.",
            "Runtime arguments: " + shlex.join(arguments),
        ]
    )
    if policy == "benny":
        lines.append(
            "Explicit kickoff override: you have no PR creation or Slack-write authority. Return findings and evidence to the coordinator. Only the coordinator may open a draft PR under the Benny procedure; this replaces the generic ready-PR instruction for this task."
        )
    return "\n".join(lines) + "\n"


def check_blind_text(value: str, *, label: str) -> None:
    lowered = value.casefold()
    if any(token in lowered for token in FORBIDDEN):
        raise RuntimeErrorBase(
            f"blinding incompatibility in {label}; preserve the treatment and explicitly redesign the comparison"
        )
    if CHAIN_CUES.search(value):
        raise RuntimeErrorBase(f"chain-eliciting instruction in {label}")


def project_trial(
    *,
    payload_root: Path,
    expected_manifest_sha256: str,
    treatment_root: Path,
    files: list[str],
    organic_request: str,
    destination: Path,
    expected_treatment_sha256: str,
) -> dict:
    """Create a neutral allowed-input tree, never a substitute for sandbox enforcement.

    The common worker dependency has one declared lexical adaptation (tests to
    checks). The parent payload requires an externally supplied artifact pin;
    arbitrary worker text cannot become this verified dependency. Experimental
    treatment bytes are never changed. The receipt returned
    to the coordinator must remain outside the candidate's filesystem and prompt.
    """
    if not isinstance(expected_manifest_sha256, str):
        raise RuntimeErrorBase("trial projection requires an external parent artifact pin")
    verified = verify_payload(payload_root, expected_manifest=expected_manifest_sha256)
    worker_source = contained(payload_root, "skills/poteto-mode/worker.md")
    if destination.exists():
        raise RuntimeErrorBase("trial destination must be new; refusing to merge exposed context")
    check_blind_text(str(destination.absolute()), label="visible absolute path")
    check_blind_text(organic_request, label="organic request")
    if len(set(files)) != len(files):
        raise RuntimeErrorBase("duplicate treatment file")
    records = []
    for relative in sorted(files):
        relative = safe_relative(relative)
        check_blind_text(relative, label="treatment path")
        source = contained(treatment_root.resolve(), relative)
        regular(source)
        data = source.read_bytes()
        check_blind_text(data.decode("utf-8", errors="replace"), label="treatment content")
        records.append(
            {
                "path": relative,
                "sha256": digest(data),
                "mode": "100755" if source.stat().st_mode & 0o111 else "100644",
                "size": len(data),
            }
        )
    treatment_digest = digest(canonical(records))
    if expected_treatment_sha256 != treatment_digest:
        raise RuntimeErrorBase("declared treatment identity changed; no silent projection rewrite")
    regular(worker_source)
    original_worker = worker_source.read_text(encoding="utf-8")
    if original_worker.count("pass its own tests.") != 1:
        raise RuntimeErrorBase("common worker lexical adaptation anchor changed")
    neutral_worker = original_worker.replace(
        "pass its own tests.", "pass the checks for its own change."
    )
    check_blind_text(neutral_worker, label="neutral worker instructions")
    worker_relative = ".instructions/worker.md"
    if worker_relative in files or any(x.startswith(".instructions/") for x in files):
        raise RuntimeErrorBase("treatment collides with the worker dependency")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".pstack-stage-", dir=destination.parent))
    try:
        for record in records:
            source = contained(treatment_root.resolve(), record["path"])
            target = temporary / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            target.chmod(0o755 if record["mode"] == "100755" else 0o644)
        target = temporary / worker_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(neutral_worker, encoding="utf-8")
        target.chmod(0o644)
        # Recheck actual copied bytes against the frozen treatment before exposing it.
        for record in records:
            if digest((temporary / record["path"]).read_bytes()) != record["sha256"]:
                raise RuntimeErrorBase("treatment changed during projection")
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    kickoff = f"Read {destination.absolute() / worker_relative} before anything else.\n\n{organic_request}\n"
    check_blind_text(kickoff, label="worker kickoff")
    return {
        "status": "projection_ready_execution_unqualified",
        "kickoff": kickoff,
        "destination": str(destination.absolute()),
        "parent_payload_sha256": verified["manifest_sha256"],
        "parent_tree_sha256": verified["tree_sha256"],
        "parent_upstream": verified["upstream"],
        "parent_worker_path": "skills/poteto-mode/worker.md",
        "treatment_sha256": treatment_digest,
        "treatment_files": records,
        "worker_source_sha256": digest(original_worker.encode()),
        "worker_projection_sha256": digest(neutral_worker.encode()),
        "worker_transform": "common-worker-tests-to-checks-v1",
        "requires": [
            "generic role with no full-mode loading",
            "no inherited parent history",
            "actual file/tool/credential closure limited to this projection",
            "coordinator receipt and evaluator context inaccessible to worker",
        ],
    }
