#!/usr/bin/env python3
"""Resolve pstack instructions and external configuration; never modify the payload."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from history import unavailable_history  # noqa: E402
from integrity import (  # noqa: E402
    RuntimeErrorBase,
    load_json,
    resolve_locator,
    resolve_skill,
    resolve_resource,
    require_external_destination,
    verify_payload,
)
from models import read_preferences, model_plan, parse_preferences, write_preferences  # noqa: E402
from profiles import DEFAULT_CONFIG, load_profile  # noqa: E402
from workers import worker_brief  # noqa: E402


def config_home() -> Path:
    return Path.home() / ".config" / "pstack"


def _present(path: Path) -> bool:
    # A dangling configured link must fail when read, never become an absent
    # configuration that silently selects defaults or an unmodified body.
    return path.exists() or path.is_symlink()


def _overrides(args: argparse.Namespace) -> Path | None:
    configured = None
    if _present(args.config):
        configured = load_profile(args.config)["profile"].get("override_registry")
    if args.overrides is not None:
        return args.overrides
    if configured:
        return Path(configured)
    default = config_home() / "overrides.json"
    return default if _present(default) else None


def _runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path)
    parser.add_argument("--locator", type=Path)
    parser.add_argument("--surface", choices=["desktop", "cloud", "cli"], default="desktop")
    parser.add_argument("--expected-manifest")
    parser.add_argument("--expected-upstream")
    parser.add_argument("--expected-version")


def _verified(args: argparse.Namespace) -> tuple[Path, dict]:
    root = args.root
    pin = args.expected_manifest
    if args.locator:
        locator = resolve_locator(args.locator, surface=args.surface, supplied_root=root)
        root = locator["root"]
        if pin is not None and pin != locator["expected_manifest"]:
            raise RuntimeErrorBase("explicit manifest pin conflicts with installation locator")
        pin = locator["expected_manifest"]
    elif args.surface == "cloud":
        raise RuntimeErrorBase("Cloud needs an explicit external installation locator")
    if root is None:
        raise RuntimeErrorBase("supply the known installed --root or an external --locator")
    if hasattr(args, "config") and _present(args.config):
        configured_root = load_profile(args.config)["profile"].get("runtime_root")
        if configured_root is not None and Path(configured_root).resolve() != root.resolve():
            raise RuntimeErrorBase("selected profile belongs to another runtime root")
    result = verify_payload(
        root,
        expected_manifest=pin,
        expected_upstream=args.expected_upstream,
        expected_version=args.expected_version,
    )
    return Path(result["root"]), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Check the complete installed payload")
    _runtime_arguments(verify)
    resolve = commands.add_parser(
        "resolve", help="Resolve direct and internal calls through one body selector"
    )
    resolve.add_argument("skill")
    _runtime_arguments(resolve)
    resolve.add_argument("--overrides", type=Path)
    resolve.add_argument("--models", type=Path, default=config_home() / "models.mdc")
    resolve.add_argument("--config", type=Path, default=config_home() / "config.toml")
    resource = commands.add_parser(
        "resource",
        help="Resolve a relative helper or sibling skill using the selected body registry",
    )
    resource.add_argument("skill")
    resource.add_argument("reference")
    _runtime_arguments(resource)
    resource.add_argument("--overrides", type=Path)
    resource.add_argument("--config", type=Path, default=config_home() / "config.toml")
    profile = commands.add_parser(
        "profile", help="Inspect configured settings; this does not authenticate capabilities"
    )
    profile.add_argument("--config", type=Path, default=config_home() / "config.toml")
    profile.add_argument("--select")
    initialize = commands.add_parser(
        "init", help="Create only the default profile in an external configuration file"
    )
    initialize.add_argument("--config", type=Path, default=config_home() / "config.toml")
    brief = commands.add_parser(
        "worker", help="Build a source-faithful ordinary or Benny worker kickoff"
    )
    _runtime_arguments(brief)
    brief.add_argument("--overrides", type=Path)
    brief.add_argument("--config", type=Path, default=config_home() / "config.toml")
    brief.add_argument("--task-file", type=Path, required=True)
    brief.add_argument(
        "--role", choices=["poteto-agent", "comment-sicko", "generic"], default="poteto-agent"
    )
    brief.add_argument("--policy", choices=["ordinary", "benny"], default="ordinary")
    commands.add_parser("history", help="Report the unresolved native-history producer boundary")
    models = commands.add_parser(
        "models", help="Plan and explicitly confirm external nine-role preferences"
    )
    model_commands = models.add_subparsers(dest="model_command", required=True)
    plan = model_commands.add_parser("plan")
    plan.add_argument("--file", type=Path, default=config_home() / "models.mdc")
    plan.add_argument("--catalog", type=Path, required=True)
    plan.add_argument("--budget", choices=["large", "medium", "small"], required=True)
    plan.add_argument("--choices", type=Path)
    write = model_commands.add_parser("write")
    write.add_argument("--file", type=Path, default=config_home() / "models.mdc")
    write.add_argument("--plan", type=Path, required=True)
    write.add_argument("--approved-plan", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            _, result = _verified(args)
        elif args.command == "resolve":
            root, verification = _verified(args)
            result = resolve_skill(
                root, args.skill, overrides=_overrides(args), verified=verification
            )
            result["verification"] = verification
            if _present(args.models):
                result["model_preferences"] = read_preferences(
                    parse_preferences(args.models.read_text(encoding="utf-8"))
                )
                result["model_preferences"]["path"] = str(args.models.resolve())
                result["model_preferences"]["activation"] = (
                    "explicit runtime read; provider choices still need actual discovery"
                )
            else:
                result["model_preferences"] = {
                    "status": "not_configured",
                    "path": str(args.models),
                    "note": "Source role defaults require an observed model mapping before dispatch.",
                }
            result["deployment"] = (
                load_profile(args.config)
                if _present(args.config)
                else {
                    "status": "not_configured",
                    "initial_profile": "default",
                    "capability_status": "unverified",
                }
            )
        elif args.command == "resource":
            root, verification = _verified(args)
            result = resolve_resource(
                root, args.skill, args.reference, overrides=_overrides(args), verified=verification
            )
        elif args.command == "profile":
            result = load_profile(args.config, selected=args.select)
        elif args.command == "init":
            require_external_destination(args.config)
            if args.config.is_symlink():
                raise RuntimeErrorBase("configuration cannot be a symlink")
            # Generated runtime is three levels below the selected host root.
            runtime_root = Path(__file__).resolve().parents[3]
            if (
                args.config.resolve().is_relative_to(runtime_root)
                and (runtime_root / "payload-manifest.json").exists()
            ):
                raise RuntimeErrorBase("configuration must be outside the installed payload")
            args.config.parent.mkdir(parents=True, exist_ok=True)
            with args.config.open("x", encoding="utf-8") as handle:
                handle.write(DEFAULT_CONFIG)
            result = {
                "created": str(args.config),
                "active_profile": "default",
                "capability_status": "unverified",
            }
        elif args.command == "worker":
            root, verification = _verified(args)
            result = {
                "kickoff": worker_brief(
                    root,
                    args.task_file.read_text(encoding="utf-8"),
                    role=args.role,
                    policy=args.policy,
                    overrides=_overrides(args),
                    verified=verification,
                    config=args.config,
                    surface=args.surface,
                    locator=args.locator,
                ),
                "payload_sha256": verification["manifest_sha256"],
                "isolation": "requires actual host enforcement",
            }
        elif args.command == "history":
            result = unavailable_history()
        elif args.model_command == "plan":
            text = args.file.read_text(encoding="utf-8") if _present(args.file) else ""
            result = model_plan(
                text,
                load_json(args.catalog),
                args.budget,
                choices=load_json(args.choices) if args.choices is not None else None,
            )
        else:
            result = write_preferences(
                args.file, load_json(args.plan), approved_plan=args.approved_plan
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (RuntimeErrorBase, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(f"pstack: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
