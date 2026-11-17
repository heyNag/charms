"""Source-faithful nine-role model preference migration and observed selection."""

from __future__ import annotations

import re
from pathlib import Path

from integrity import RuntimeErrorBase, canonical, digest, require_external_destination

ALIASES = {"inherit-parent", "auto"}
EFFORTS = ["low", "medium", "high", "xhigh"]
PANELS = {"arena runners", "arena cross-judge pool", "interrogate reviewers"}
DEFAULTS = {
    "feature, refactoring": ["claude-opus-5-5-xhigh-fast"],
    "bug-fix": ["claude-opus-5-5-xhigh-fast"],
    "perf-issue": ["claude-opus-5-5-xhigh-fast"],
    "hillclimb": ["claude-opus-5-5-xhigh-fast"],
    "judgment and prose": ["claude-opus-5-5-xhigh-fast"],
    "arena runners": ["claude-fable-5-2-high", "claude-opus-5-5-high-fast", "gemini-4-carbon-high"],
    "arena cross-judge pool": ["claude-opus-5-5-high-fast", "gemini-4-carbon-high"],
    "swarm workers": ["claude-opus-5-5-high-fast"],
    "interrogate reviewers": [
        "claude-fable-5-2-high",
        "claude-opus-5-5-high-fast",
        "gemini-4-carbon-high",
    ],
}


def parse_preferences(text: str) -> dict:
    roles = {}
    retired = []
    defaults = None
    budget = None
    in_frontmatter = text.startswith("---\n")
    line_start = 1 if in_frontmatter else 0
    lines = text.splitlines()
    if in_frontmatter:
        try:
            line_start = lines.index("---", 1) + 1
        except ValueError as exc:
            raise RuntimeErrorBase("unterminated model-rule frontmatter") from exc
    for line in lines[line_start:]:
        if match := re.fullmatch(r"# defaults: ([0-9]+)\s*", line):
            if defaults is not None:
                raise RuntimeErrorBase("duplicate defaults revision")
            defaults = int(match[1])
        elif match := re.fullmatch(
            r"# budget: (large|medium|small|unlimited)(?: \([^)]*\))?\s*", line
        ):
            if budget is not None:
                raise RuntimeErrorBase("duplicate model budget")
            budget = match[1]
        elif line and not line.startswith("#") and ":" in line:
            role, raw = line.split(":", 1)
            role = role.strip()
            if role not in DEFAULTS:
                retired.append(role)
                continue
            if role in roles:
                raise RuntimeErrorBase("duplicate model role")
            values = [v.strip() for v in raw.split(",")]
            if not all(values) or (role not in PANELS and len(values) != 1):
                raise RuntimeErrorBase("invalid role cardinality")
            roles[role] = values
    if defaults is not None and defaults > 3:
        raise RuntimeErrorBase("unsupported model defaults revision")
    return {"defaults": defaults, "budget": budget or "large", "roles": roles, "retired": retired}


def read_preferences(parsed: dict) -> dict:
    """Honor an existing rule during work; only setup may migrate its choices."""
    revision = parsed["defaults"] or 0
    return {
        "defaults": parsed["defaults"],
        "budget": parsed["budget"],
        "roles": {
            role: list(parsed["roles"].get(role, values)) for role, values in DEFAULTS.items()
        },
        "unrecognized_roles": list(parsed["retired"]),
        "changes": [],
        "effective_effort_ceiling": "xhigh",
        "setup_reminder": None
        if revision == 3
        else {
            "key": digest(canonical(parsed)),
            "frequency": "once per conversation",
            "message": "Keep these existing choices; rerun setup to review defaults revision 3.",
        },
    }


def vendor_id(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeErrorBase("originating model vendor is unknown")
    normalized = value.strip().casefold()
    aliases = {
        "anthropic pbc": "anthropic",
        "anthropic, pbc": "anthropic",
        "open ai": "openai",
        "google deepmind": "google",
        "deepmind": "google",
        "x.ai": "xai",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {
        "unknown",
        "none",
        "auto",
        "inherit-parent",
        "unavailable",
    } or not re.fullmatch(r"[a-z][a-z0-9.-]*", normalized):
        raise RuntimeErrorBase("originating model vendor is unknown")
    return normalized


def migrate_preferences(parsed: dict) -> dict:
    roles = {k: list(parsed["roles"].get(k, v)) for k, v in DEFAULTS.items()}
    changes = [{"role": name, "action": "drop retired role"} for name in parsed["retired"]]
    revision = parsed["defaults"] or 0
    budget = parsed["budget"]
    if revision < 3:
        if budget == "unlimited":
            budget = "large"
            changes.append({"role": "budget", "action": "unlimited -> large"})
        pool = roles["arena cross-judge pool"]
        if len(pool) == 3 and all(
            sum(v.startswith(prefix) for v in pool) == 1
            for prefix in ("claude-fable-", "claude-opus-", "gemini-")
        ):
            roles["arena cross-judge pool"] = list(DEFAULTS["arena cross-judge pool"])
            changes.append(
                {"role": "arena cross-judge pool", "action": "replace recognized pre-v3 default"}
            )
        if revision < 2:
            single = {"feature, refactoring", "bug-fix", "perf-issue", "hillclimb", "swarm workers"}
            for role, values in list(roles.items()):
                replacement = values
                if role in single and len(values) == 1 and values[0].startswith("grok-"):
                    replacement = list(DEFAULTS[role])
                elif role in PANELS:
                    if (
                        len(values) == 2
                        and sum(v.startswith("claude-opus-") for v in values) == 1
                        and sum(v.startswith("grok-") for v in values) == 1
                    ):
                        replacement = list(DEFAULTS[role])
                    else:
                        replacement = [
                            "claude-opus-5-5-high-fast" if v.startswith("grok-") else v
                            for v in values
                        ]
                if replacement != values:
                    roles[role] = replacement
                    changes.append(
                        {"role": role, "action": "replace recognized legacy Grok default"}
                    )
    if budget not in {"large", "medium", "small"}:
        raise RuntimeErrorBase("unsupported model budget")
    return {"defaults": 3, "budget": budget, "roles": roles, "changes": changes}


def parse_slug(slug: str) -> dict:
    match = re.fullmatch(r"(.+)-(low|medium|high|xhigh)(-fast)?", slug)
    if not match:
        raise RuntimeErrorBase(
            "model selection needs a confirmed effort mapping; unknown slug is not normalized"
        )
    prefix, effort, fast = match.groups()
    return {
        "family": prefix,
        "source_family": source_family(prefix),
        "effort": effort,
        "fast": bool(fast),
    }


def source_family(model: str) -> str:
    """Arena's source grouping is distinct from a provider's version identity."""
    name = model.removeprefix("cursor-")
    for prefix in ("claude-fable", "claude", "gemini"):
        if name == prefix or name.startswith(prefix + "-"):
            return prefix
    return name.split("-", 1)[0]


def _is_model(item: dict, prefix: str) -> bool:
    # A native slug need not encode the real model. The discovery mapping must
    # supply the originating model family/version and provider model identity.
    return any(
        name.removeprefix("cursor-") == prefix
        or name.removeprefix("cursor-").startswith(prefix + "-")
        for name in (item["slug"], item["family"], item["provider_model"])
    )


def validate_catalog(catalog: object) -> dict[str, dict]:
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema_version") != 1
        or not isinstance(catalog.get("models"), list)
    ):
        raise RuntimeErrorBase("invalid observed model catalog")
    if not isinstance(catalog.get("observation_id"), str) or not catalog["observation_id"]:
        raise RuntimeErrorBase("catalog needs an actual discovery observation reference")
    # This validates a discovery export; authenticity remains the host driver's job.
    result = {}
    for item in catalog["models"]:
        if (
            not isinstance(item, dict)
            or not {"slug", "family", "vendor", "effort", "fast", "provider_model"} <= item.keys()
        ):
            raise RuntimeErrorBase("model catalog entry lacks observed mapping")
        slug = item["slug"]
        if not isinstance(slug, str) or slug in ALIASES or slug in result:
            raise RuntimeErrorBase("invalid or duplicate discovered model")
        if item["effort"] not in EFFORTS or type(item["fast"]) is not bool:
            raise RuntimeErrorBase("unsupported model effort/speed mapping")
        if any(
            not isinstance(item[k], str) or not item[k]
            for k in ("family", "vendor", "provider_model")
        ):
            raise RuntimeErrorBase("missing provider model identity")
        group = source_family(item["family"])
        known_groups = {"claude-fable", "claude", "gemini"}
        identities = {
            source_family(name) for name in (slug, item["family"], item["provider_model"])
        } & known_groups
        if identities and identities != {group}:
            raise RuntimeErrorBase("source and observed model family identities disagree")
        if source_family(slug) in known_groups:
            try:
                source = parse_slug(slug)
            except RuntimeErrorBase:
                # Native names without an effort suffix still use discovery,
                # while their recognized manufacturer/model constraints apply.
                source = None
            if source is not None and (
                source["family"].removeprefix("cursor-") != item["family"].removeprefix("cursor-")
                or source["effort"] != item["effort"]
                or source["fast"] != item["fast"]
            ):
                raise RuntimeErrorBase("source model identity/effort/speed contradicts discovery")
            if source is not None and source_family(item["provider_model"]) in known_groups:
                model = source["family"].removeprefix("cursor-")
                provider_model = item["provider_model"].removeprefix("cursor-")
                if provider_model != model and not provider_model.startswith(model + "-"):
                    raise RuntimeErrorBase("source and provider model identities disagree")
        if _is_model(item, "claude-opus-5-5") and not item["fast"]:
            raise RuntimeErrorBase("Opus 5.5 requires a verified fast route")
        if group in {"claude-fable", "gemini"} and item["fast"]:
            raise RuntimeErrorBase("source does not define a Fable/Gemini fast variant")
        if group == "gemini" and item["effort"] == "xhigh":
            raise RuntimeErrorBase("Gemini effort exceeds the source ceiling")
        item = {**item, "vendor": vendor_id(item["vendor"]), "source_family": group}
        if group in {"claude", "claude-fable"} and item["vendor"] != "anthropic":
            raise RuntimeErrorBase("Claude origin is Anthropic regardless of transport")
        if group == "gemini" and item["vendor"] != "google":
            raise RuntimeErrorBase("Gemini origin is Google regardless of transport")
        result[slug] = item
    return result


def _role_choices(choices: object, available: dict[str, dict]) -> dict[str, list[str]]:
    if choices is None:
        return {}
    if (
        not isinstance(choices, dict)
        or set(choices) != {"schema_version", "roles"}
        or type(choices["schema_version"]) is not int
        or choices["schema_version"] != 1
        or not isinstance(choices["roles"], dict)
    ):
        raise RuntimeErrorBase("invalid explicit model choices")
    result = {}
    for role, values in choices["roles"].items():
        if role not in DEFAULTS:
            raise RuntimeErrorBase("unknown model role in explicit choices")
        if (
            not isinstance(values, list)
            or not values
            or (role not in PANELS and len(values) != 1)
        ):
            raise RuntimeErrorBase("invalid explicit role cardinality")
        if any(
            not isinstance(value, str) or (value not in ALIASES and value not in available)
            for value in values
        ):
            raise RuntimeErrorBase("explicit model choice is not an observed model or alias")
        result[role] = list(values)
    return result


def model_plan(text: str, catalog: dict, budget: str, *, choices: dict | None = None) -> dict:
    if budget not in {"large", "medium", "small"}:
        raise RuntimeErrorBase("unknown model budget")
    migrated = migrate_preferences(parse_preferences(text))
    available = validate_catalog(catalog)
    explicit = _role_choices(choices, available)
    shift = {"large": 0, "medium": 1, "small": 2}[budget]
    selected = {}
    unresolved = []
    for role, values in migrated["roles"].items():
        # Setup's explicit role choices follow its budget mapping step. Keep
        # those observed choices exact; never rewrite the active rule to plan them.
        if role in explicit:
            selected[role] = list(explicit[role])
            continue
        baseline = parse_slug(DEFAULTS[role][0])["effort"]
        target = EFFORTS[max(0, EFFORTS.index(baseline) - shift)]
        selected[role] = []
        for value in values:
            if value in ALIASES:
                selected[role].append(value)
                continue
            requested = available.get(value)
            if requested is None:
                try:
                    requested = parse_slug(value)
                except RuntimeErrorBase:
                    requested = None
            if requested is None:
                selected[role].append(value)
                unresolved.append(
                    {"role": role, "requested": value, "reason": "unknown effort/family mapping"}
                )
                continue
            family = requested["source_family"]
            effective_target = "high" if family == "gemini" and target == "xhigh" else target
            candidates = [
                (s, data)
                for s, data in available.items()
                if data["source_family"] == family
                and EFFORTS.index(data["effort"]) <= EFFORTS.index(effective_target)
            ]
            if not candidates:
                selected[role].append(value)
                unresolved.append(
                    {
                        "role": role,
                        "requested": value,
                        "reason": "no observed same-family model at or below target",
                    }
                )
                continue
            best = max(
                candidates,
                key=lambda pair: (
                    EFFORTS.index(pair[1]["effort"]),
                    pair[0] == value,
                    pair[1]["family"] == requested["family"],
                    pair[0],
                ),
            )
            selected[role].append(best[0])
    plan = {
        "schema_version": 1,
        "defaults": 3,
        "budget": budget,
        "roles": selected,
        "choices": explicit,
        "changes": migrated["changes"],
        "needs_choice": unresolved,
        "catalog_sha256": digest(canonical(catalog)),
        "source_sha256": digest(text.encode()),
        "catalog_observation": catalog["observation_id"],
        "status": "needs_choice" if unresolved else "awaiting_confirmation",
    }
    plan["plan_sha256"] = digest(canonical(plan))
    return plan


def render_preferences(plan: dict) -> str:
    lines = [
        "---",
        "description: pstack per-role model choices (overrides skill defaults)",
        "alwaysApply: true",
        "---",
        "# pstack model configuration; explicitly loaded by the Codex runtime.",
        "# defaults: 3",
        f"# budget: {plan['budget']} ({ {'large': 'xhigh', 'medium': 'high', 'small': 'medium'}[plan['budget']] })",
    ]
    # Keep the budget form accepted by the source parser.
    lines[-1] = lines[-1].replace(" )", ")")
    for role in DEFAULTS:
        lines.append(role + ": " + ", ".join(plan["roles"][role]))
    return "\n".join(lines) + "\n"


def write_preferences(path: Path, plan: dict, *, approved_plan: str) -> dict:
    check = dict(plan)
    recorded = check.pop("plan_sha256", None)
    if not recorded or digest(canonical(check)) != recorded or recorded != approved_plan:
        raise RuntimeErrorBase("confirmation does not match the displayed model plan")
    if plan.get("status") != "awaiting_confirmation" or plan.get("needs_choice"):
        raise RuntimeErrorBase("unavailable models still need a choice")
    require_external_destination(path)
    current = path.read_text() if path.exists() else ""
    if digest(current.encode()) != plan.get("source_sha256"):
        raise RuntimeErrorBase("model preferences changed after planning")
    if path.is_symlink():
        raise RuntimeErrorBase("model preferences cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_preferences(plan)
    # Exclusive temporary creation followed by atomic replacement avoids partial rules.
    import os
    import tempfile

    fd, temporary = tempfile.mkstemp(prefix=".pstack-models-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"written": str(path), "defaults": 3, "sha256": digest(text.encode())}


def choose_judge(
    pool: list[str],
    catalog: dict,
    author_vendor: str | None,
    *,
    workflow: str,
    rejected: list[str] | None = None,
) -> dict:
    available = validate_catalog(catalog)
    if workflow not in {"arena", "show-me-your-work"}:
        raise RuntimeErrorBase("vendor predicate must be selected by the calling workflow")
    author_vendor = vendor_id(author_vendor) if author_vendor is not None else None
    rejected_models = set(rejected or [])
    visited = set()
    for requested in pool:
        if requested in ALIASES or requested in visited:
            continue
        visited.add(requested)
        choices = []
        if requested in available and requested not in rejected_models:
            choices.append((requested, available[requested]))
        # An absent/rejected source slug still gets its observed same-family
        # recovery before the next configured pool entry. Never invent a model,
        # raise the requested effort ceiling, or retry a rejected selection.
        description = available.get(requested)
        if description is None:
            try:
                description = parse_slug(requested)
            except RuntimeErrorBase:
                description = None
        if description is not None:
            replacements = [
                (slug, item)
                for slug, item in available.items()
                if slug != requested
                and slug not in rejected_models
                and item["source_family"] == description["source_family"]
                and EFFORTS.index(item["effort"]) <= EFFORTS.index(description["effort"])
            ]
            choices.extend(
                sorted(replacements, key=lambda pair: (-EFFORTS.index(pair[1]["effort"]), pair[0]))
            )
        for slug, item in choices:
            if author_vendor is None and workflow != "arena":
                continue
            if author_vendor is not None and item["vendor"] == author_vendor:
                continue
            return {
                "status": "selected_vendor_unchecked" if author_vendor is None else "selected",
                "model": slug,
                "vendor": item["vendor"],
                "requested": requested,
                "fallback": slug != requested,
                "fallback_reason": "observed same-family replacement"
                if slug != requested
                else None,
            }
    if workflow == "arena":
        return {
            "status": "unjudged",
            "reason": "no eligible observed model after same-family recovery; disclose the skipped judge",
        }
    raise RuntimeErrorBase(
        "show-me requires an observed other-vendor reviewer; audit remains incomplete"
    )


def permit_fable(
    *, in_panel: bool, explicitly_named: bool, brief_sha256: str, failures: list[dict]
) -> bool:
    if in_panel or explicitly_named:
        return True
    attempts = {
        r.get("attempt_id")
        for r in failures
        if r.get("brief_sha256") == brief_sha256
        and r.get("model_family") == "claude-opus-5-5"
        and r.get("effort") == "xhigh"
        and r.get("result") == "failed"
        and r.get("check")
        and r.get("evidence_id")
        and r.get("attempt_id")
    }
    return len(attempts) >= 2
