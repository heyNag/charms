"""External deployment profiles and immutable, observed run bindings."""

from __future__ import annotations

import copy
from pathlib import Path
import re
import tomllib
from typing import Callable

from integrity import RuntimeErrorBase, canonical, digest

DEFAULT_CONFIG = 'schema_version = 1\nactive_profile = "default"\n\n[profiles.default]\n'
PROFILE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
REFERENCE = re.compile(r"(?:env:[A-Za-z_][A-Za-z0-9_]*|secret:[A-Za-z0-9_./:@-]+)")


def _service(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {
        "endpoint",
        "credential_ref",
        "protocol",
        "producer",
    }:
        raise RuntimeErrorBase("invalid service settings; use credential references only")
    for key, field in value.items():
        if not isinstance(field, str) or not field:
            raise RuntimeErrorBase("service fields must be nonempty strings")
        if key == "endpoint":
            from urllib.parse import urlsplit

            parsed = urlsplit(field)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise RuntimeErrorBase(
                    "service endpoint must be HTTPS without embedded credentials"
                )
            if parsed.query or parsed.fragment:
                raise RuntimeErrorBase(
                    "service endpoint cannot contain query credentials or fragments"
                )
        if key == "credential_ref" and not REFERENCE.fullmatch(field):
            raise RuntimeErrorBase("invalid credential reference")
    return copy.deepcopy(value)


def validate_profile(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {
        "runtime_root",
        "bridge",
        "history",
        "providers",
        "credential_refs",
        "override_registry",
    }:
        raise RuntimeErrorBase(
            "unsupported profile setting; model preferences and secrets are separate"
        )
    if "override_registry" in value and (
        not isinstance(value["override_registry"], str)
        or not Path(value["override_registry"]).is_absolute()
    ):
        raise RuntimeErrorBase("override_registry must be an absolute external path")
    if "runtime_root" in value:
        if (
            not isinstance(value["runtime_root"], str)
            or not Path(value["runtime_root"]).is_absolute()
        ):
            raise RuntimeErrorBase("runtime_root must be absolute")
    for name in ("bridge", "history"):
        if name in value:
            _service(value[name])
    providers = value.get("providers", {})
    if not isinstance(providers, dict):
        raise RuntimeErrorBase("providers must be a named map")
    for name, settings in providers.items():
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
            raise RuntimeErrorBase("invalid provider name")
        _service(settings)
    references = value.get("credential_refs", {})
    if not isinstance(references, dict):
        raise RuntimeErrorBase("credential_refs must be a named map")
    for name, reference in references.items():
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
            raise RuntimeErrorBase("invalid credential reference name")
        if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
            raise RuntimeErrorBase("credentials must be env:NAME or secret:ID references")
    return copy.deepcopy(value)


def load_profile(path: Path, *, selected: str | None = None) -> dict:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeErrorBase("invalid profile TOML (duplicate keys are not permitted)") from exc
    if (
        set(doc) != {"schema_version", "active_profile", "profiles"}
        or type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
    ):
        raise RuntimeErrorBase("unsupported deployment configuration schema")
    profiles = doc["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeErrorBase("configuration needs a named profile map")
    for name, value in profiles.items():
        if not PROFILE_NAME.fullmatch(name):
            raise RuntimeErrorBase("invalid profile name")
        validate_profile(value)
    active = selected if selected is not None else doc["active_profile"]
    if not isinstance(active, str) or active not in profiles:
        raise RuntimeErrorBase("unknown selected profile; no default fallback is permitted")
    profile = validate_profile(profiles[active])
    revision = digest(canonical({"schema_version": 1, "profile_id": active, "profile": profile}))
    return {
        "schema_version": 1,
        "profile_id": active,
        "profile_revision": revision,
        "profile": profile,
        "configuration_sha256": digest(path.read_bytes()),
        "capability_status": "unverified",
        "note": "Configuration does not establish account access or capabilities.",
    }


def bind_run(
    profile: dict,
    observation: dict,
    *,
    repository: str,
    payload_sha256: str,
    authorization_scope: list[str],
    authenticate: Callable[[dict], bool],
) -> dict:
    """Only a trusted host/provider observation verifier can promote capability claims.

    A model-authored JSON file is not such a verifier. CLI profile inspection does
    not call this operation; integration drivers must supply their own verifier.
    """
    if not authenticate(copy.deepcopy(observation)):
        raise RuntimeErrorBase("host/account observation is not authenticated")
    required = {"account_id", "workspace_id", "surface", "observer", "evidence_id", "capabilities"}
    if not required <= observation.keys():
        raise RuntimeErrorBase("host observation is incomplete")
    for key in required - {"capabilities"}:
        if not isinstance(observation[key], str) or not observation[key].strip():
            raise RuntimeErrorBase("host observation identity is incomplete")
    if observation["surface"] not in {"desktop", "cloud", "cli"}:
        raise RuntimeErrorBase("unknown observed surface")
    capabilities = observation["capabilities"]
    if not isinstance(capabilities, dict) or any(
        v not in {"available", "unavailable", "unverified"} for v in capabilities.values()
    ):
        raise RuntimeErrorBase("invalid observed capability states")
    if not re.fullmatch(r"[0-9a-f]{64}", payload_sha256) or not repository:
        raise RuntimeErrorBase("run needs an exact payload and repository binding")
    if not isinstance(authorization_scope, list) or any(
        not isinstance(x, str) or not x for x in authorization_scope
    ):
        raise RuntimeErrorBase("invalid authorization scope")
    binding = {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "profile_revision": profile["profile_revision"],
        "profile": copy.deepcopy(profile["profile"]),
        "account_id": observation["account_id"],
        "workspace_id": observation["workspace_id"],
        "surface": observation["surface"],
        "repository": repository,
        "payload_sha256": payload_sha256,
        "observation_sha256": digest(canonical(observation)),
        "capabilities": copy.deepcopy(capabilities),
        "authorization_scope": sorted(set(authorization_scope)),
    }
    binding["binding_sha256"] = digest(canonical(binding))
    return binding


def validate_binding(binding: dict) -> None:
    value = copy.deepcopy(binding)
    recorded = value.pop("binding_sha256", None)
    if not recorded or digest(canonical(value)) != recorded:
        raise RuntimeErrorBase("run binding changed")


def resume_binding(saved: dict, proposed: dict) -> dict:
    validate_binding(saved)
    validate_binding(proposed)
    if saved != proposed:
        raise RuntimeErrorBase(
            "run binding changed; reconcile with the original account, profile and cleanup route"
        )
    return copy.deepcopy(saved)


def require_capabilities(binding: dict, names: list[str]) -> None:
    validate_binding(binding)
    missing = [name for name in names if binding["capabilities"].get(name) != "available"]
    if missing:
        raise RuntimeErrorBase("required capabilities are not established: " + ", ".join(missing))
