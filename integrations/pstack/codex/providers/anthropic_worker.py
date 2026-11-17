"""Pinned Claude Agent SDK worker driver, isolated from the native coordinator.

Only explicit invocation starts inference. The parent supervisor constructs the
entire child environment; SDK env overlays are not used as secret isolation.
This implements candidate/judge/audit/trial execution, not native Cloud history
or an AWS deployment. The service owns launch idempotency before calling it.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Callable

SDK_VERSION = "0.2.182"
API_VERSION = "2.8.0"
SDK_COMMIT = "4720d367f7db9d5df8a166c74d7f36a538ac8c34"
API_COMMIT = "5139cf2e7d07aa618a6c30b7e0c712f10ccb5ad9"
ROLES = {"candidate", "judge", "audit", "trial", "grader"}
EFFORTS = {"low", "medium", "high", "xhigh"}
MAX_OUTPUT = 2 * 1024 * 1024


class DriverError(RuntimeError):
    pass


def validate_request(request: dict) -> None:
    if request.get("role") not in ROLES:
        raise DriverError("unsupported provider worker role")
    if not isinstance(request.get("prompt"), str) or not request["prompt"]:
        raise DriverError("explicit organic prompt is required")
    if len(request["prompt"].encode()) > MAX_OUTPUT:
        raise DriverError("prompt exceeds the driver bound")
    if not isinstance(request.get("model"), str) or not request["model"]:
        raise DriverError("explicit available model is required")
    if request.get("effort") not in EFFORTS:
        raise DriverError("effort must use the supported source ceiling")
    turns = request.get("max_turns")
    budget = request.get("max_budget_usd")
    if isinstance(turns, bool) or not isinstance(turns, int) or not 1 <= turns <= 100:
        raise DriverError("max_turns must be bounded")
    if (isinstance(budget, bool) or not isinstance(budget, (int, float))
            or not math.isfinite(budget) or not 0 < budget <= 100):
        raise DriverError("explicit finite USD budget is required")
    if not isinstance(request.get("output_schema"), dict):
        raise DriverError("structured result schema is required")
    pending = [request["output_schema"]]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                if keyword in item:
                    ref = item[keyword]
                    if not isinstance(ref, str) or not ref.startswith("#"):
                        raise DriverError("result schema cannot load external references")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if any(key in request for key in ("env", "mcp_servers", "settings", "cwd", "resume", "tools")):
        raise DriverError("job input cannot configure provider process authority")


def validate_structured_result(value, schema: dict) -> None:
    import jsonschema
    from referencing import Registry

    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)
    # Registry's default retriever always raises. Never use jsonschema's legacy
    # automatic remote resolver, including for a future reference keyword.
    validator(schema, registry=Registry()).validate(value)


async def execute_sdk_job(request: dict, *, sdk, catalog, cwd: Path,
                          validate_result: Callable, broker_tools: list | None = None,
                          verified_fast_settings: dict | None = None) -> dict:
    """Run in a secret-minimal trusted driver process, never in a task repository.

    catalog is the actual Anthropic Models API client. broker_tools, when supplied
    by service code, are SDK tool objects invoking separately isolated task workers.
    They must not expose this process's filesystem, environment or arbitrary URLs.
    A request cannot supply callback implementations or MCP servers.
    """
    validate_request(request)
    model = catalog.models.retrieve(request["model"])
    if getattr(model, "lifecycle", None) != "active":
        raise DriverError("requested model is not active in the provider catalog")
    capabilities = getattr(model, "capabilities", None)
    effort = getattr(capabilities, "effort", None)
    supported = getattr(effort, request["effort"], None)
    if not getattr(effort, "supported", False) or not getattr(supported, "supported", False):
        raise DriverError("catalog does not establish requested effort support")
    if request.get("requires_task_tools") and not broker_tools:
        raise DriverError("required isolated task tools are not configured")
    if request.get("require_fast") and verified_fast_settings is None:
        raise DriverError("a qualified fast-mode setting is required; no flag is guessed")
    observations = {"effort": set(), "models": set(), "init": None}
    allowed = [f"mcp__task__{tool.name}" for tool in (broker_tools or [])]

    async def observe_hook(data, tool_use_id, context):
        level = data.get("effort", {}).get("level")
        if level:
            observations["effort"].add(level)
        if data.get("hook_event_name") == "PreToolUse" and data.get("tool_name") not in allowed:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "permissionDecision": "deny",
                                           "permissionDecisionReason": "tool is outside worker scope"}}
        return {}

    session = str(uuid.uuid4())
    servers = {}
    if broker_tools:
        servers["task"] = sdk.create_sdk_mcp_server(name="task", version="1.0.0", tools=broker_tools)
    kwargs = {
        "tools": [], "allowed_tools": allowed, "mcp_servers": servers,
        "strict_mcp_config": True, "permission_mode": "dontAsk",
        "setting_sources": [], "skills": [], "plugins": [], "agents": {},
        "continue_conversation": False, "resume": None, "session_id": session,
        "model": model.id, "fallback_model": None, "effort": request["effort"],
        "max_turns": request["max_turns"], "max_budget_usd": request["max_budget_usd"],
        "cwd": str(cwd), "max_buffer_size": MAX_OUTPUT, "stderr": lambda line: None,
        "output_format": {"type": "json_schema", "schema": request["output_schema"]},
        "hooks": {
            "PreToolUse": [sdk.HookMatcher(hooks=[observe_hook])],
            "Stop": [sdk.HookMatcher(hooks=[observe_hook])],
        },
    }
    if verified_fast_settings is not None:
        kwargs["settings"] = json.dumps(verified_fast_settings, sort_keys=True)
    options = sdk.ClaudeAgentOptions(**kwargs)
    result = None
    async with sdk.ClaudeSDKClient(options=options) as client:
        await client.query(request["prompt"])
        async for message in client.receive_response():
            if isinstance(message, sdk.SystemMessage) and message.subtype == "init":
                init = message.data
                if init.get("session_id") != session or init.get("apiKeySource") != "ANTHROPIC_API_KEY":
                    raise DriverError("SDK session or first-party credential provenance differs")
                if set(init.get("tools", [])) != set(allowed) or init.get("skills") or init.get("plugins"):
                    raise DriverError("SDK exposed ambient tools, skills or plugins")
                observations["init"] = {
                    key: init.get(key) for key in ("model", "claude_code_version", "fast_mode_state")
                }
                if init.get("model"):
                    observations["models"].add(init["model"])
            if isinstance(message, sdk.AssistantMessage):
                if message.error:
                    raise DriverError("provider assistant reported an API error")
                observations["models"].add(message.model)
            if isinstance(message, sdk.ResultMessage):
                result = message
                observations["models"].update((message.model_usage or {}).keys())
    if result is None or observations["init"] is None:
        raise DriverError("missing provider init or terminal result")
    if (result.is_error or result.subtype != "success" or result.session_id != session
            or result.terminal_reason not in {None, "completed"} or result.permission_denials):
        raise DriverError("provider result is failed, incomplete, cancelled or denied")
    if not observations["models"]:
        raise DriverError("no actual provider model identity observed")
    observed_models = []
    for observed in sorted(observations["models"]):
        resolved = catalog.models.retrieve(observed)
        if resolved.id != model.id:
            raise DriverError("observed provider model differs from the selected canonical model")
        observed_models.append(resolved.id)
    if observations["effort"] != {request["effort"]}:
        raise DriverError("effective hook effort is missing or differs from requested effort")
    if request.get("require_fast") and observations["init"]["fast_mode_state"] != "on":
        raise DriverError("provider did not establish active fast mode")
    if result.total_cost_usd is None or result.total_cost_usd > request["max_budget_usd"]:
        raise DriverError("provider cost is missing or exceeds the granted budget")
    validate_result(result.structured_output, request["output_schema"])
    output = {
        "state": "completed", "provider": "anthropic", "originating_vendor": "anthropic",
        "session_id": session, "requested_model": request["model"], "canonical_model": model.id,
        "observed_models": sorted(set(observed_models)), "requested_effort": request["effort"],
        "observed_effort": sorted(observations["effort"]), "sdk_version": SDK_VERSION,
        "sdk_commit": SDK_COMMIT, "api_version": API_VERSION, "api_commit": API_COMMIT,
        "cli": observations["init"], "cost_usd": result.total_cost_usd,
        "usage": result.usage, "model_usage": result.model_usage,
        "terminal_reason": result.terminal_reason, "result": result.structured_output,
        "native_cloud_history": False, "worker_cleanup": "provider_session_closed",
    }
    if len(json.dumps(output, allow_nan=False).encode()) > MAX_OUTPUT:
        raise DriverError("provider result exceeds output bound")
    return output


def isolated_environment(credential: str, home: Path, adapter_root: Path) -> dict[str, str]:
    if not credential or "\n" in credential or "\r" in credential:
        raise DriverError("invalid explicitly supplied provider credential")
    return {
        "PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8",
        "PYTHONPATH": str(adapter_root), "PYTHONDONTWRITEBYTECODE": "1",
        "ANTHROPIC_API_KEY": credential,
    }


def run_isolated(request: dict, *, credential: str, timeout_seconds: float = 300) -> dict:
    """Execute once in a fresh owned process group with a bounded wall clock/output.

    The bridge must persist the launch token first. A lost launch acknowledgement
    is reconciled there; this function never retries an SDK run automatically.
    Terminating this driver process is not proof an external task VM terminated.
    """
    validate_request(request)
    if not sys.platform.startswith("linux"):
        raise DriverError("isolated provider execution needs the qualified Linux supervisor")
    if not 0 < timeout_seconds <= 28800:
        raise DriverError("invalid driver lifetime")
    encoded_request = json.dumps(request, allow_nan=False).encode()
    if len(encoded_request) > MAX_OUTPUT:
        raise DriverError("complete driver input exceeds bound")
    adapter_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="pstack-driver-") as temporary:
        home = Path(temporary)
        process = subprocess.Popen(
            [sys.executable, "-m", "providers.process_supervisor", "--",
             sys.executable, "-m", "providers.anthropic_worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=isolated_environment(credential, home, adapter_root), cwd=home, start_new_session=True,
        )
        selector = selectors.DefaultSelector()
        started = time.monotonic()
        output = bytearray()
        try:
            incoming = memoryview(encoded_request)
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise DriverError("driver deadline exceeded; external cleanup remains unverified")
                for key, _ in selector.select(min(remaining, 0.2)):
                    if key.fileobj is process.stdin:
                        try:
                            written = os.write(process.stdin.fileno(), incoming[:65536])
                        except BrokenPipeError as exc:
                            raise DriverError("driver stopped before accepting its bounded input") from exc
                        incoming = incoming[written:]
                        if not incoming:
                            selector.unregister(process.stdin)
                            process.stdin.close()
                        continue
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    output.extend(chunk)
                    if len(output) > MAX_OUTPUT:
                        raise DriverError("driver exceeded output bound")
            # Keep the leader unreaped until its owned group is fenced. Otherwise a
            # dead leader can leave CLI descendants alive (or its PID can be reused).
            terminal = None
            while terminal is None:
                terminal = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                if terminal is None:
                    if time.monotonic() - started >= timeout_seconds:
                        raise DriverError("driver deadline exceeded")
                    time.sleep(0.01)
            if terminal.si_code != os.CLD_EXITED or terminal.si_status != 0:
                raise DriverError("provider driver did not complete; inspect scoped service diagnostics")
            try:
                result = json.loads(output)
            except (UnicodeError, ValueError) as exc:
                raise DriverError("provider driver did not return a valid receipt") from exc
            if not isinstance(result, dict) or result.get("state") != "completed":
                raise DriverError("provider driver did not return a complete receipt")
            return result
        finally:
            selector.close()
            # The private supervisor must stay alive to reap its adopted children.
            # It forwards TERM and enforces its own bounded descendant cleanup.
            try:
                os.kill(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired as exc:
                os.kill(process.pid, signal.SIGKILL)
                process.wait(timeout=1)
                raise DriverError("driver supervisor cleanup is unverified") from exc
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_OUTPUT + 1)
        if len(raw) > MAX_OUTPUT:
            raise DriverError("driver input exceeds bound")
        request = json.loads(raw)
        validate_request(request)
        if (importlib.metadata.version("claude-agent-sdk") != SDK_VERSION
                or importlib.metadata.version("anthropic") != API_VERSION):
            raise DriverError("driver SDK versions differ from the reviewed pins")
        import anthropic
        import claude_agent_sdk as sdk
        with anthropic.Anthropic() as catalog:
            result = asyncio.run(execute_sdk_job(
                request, sdk=sdk, catalog=catalog, cwd=Path.cwd(),
                validate_result=validate_structured_result,
            ))
        print(json.dumps(result, allow_nan=False))
        return 0
    except Exception:
        # Neither credentials, raw provider errors, nor prompts are printed.
        print('{"state":"incomplete","error":"provider_driver_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
