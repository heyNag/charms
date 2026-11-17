"""SDK tools proxy only to the separately configured secret-free task worker."""

from __future__ import annotations

import asyncio
import json

from .anthropic_worker import DriverError, MAX_OUTPUT

OPERATIONS = {"read", "exec", "write", "artifact"}


def make_remote_tools(sdk, *, client, job_id: str, epoch: int, contract_sha256: str,
                      schemas: dict[str, dict], allowed: frozenset[str]):
    """Trusted service wiring, never a job-supplied callback or endpoint.

    The actual worker broker must authenticate this capability, enforce filesystem,
    network and deadline policy, and return original operation receipts. The local
    control service deliberately does not advertise worker.operation: it lacks a
    deployed isolated task worker. Configuring this client is not certification.
    """
    if not allowed <= OPERATIONS or set(schemas) != set(allowed) or not contract_sha256:
        raise DriverError("explicit scoped worker operations and schemas required")
    tools = []
    for operation in sorted(allowed):
        async def callback(arguments, operation=operation):
            encoded = json.dumps(arguments, allow_nan=False).encode()
            if len(encoded) > MAX_OUTPUT:
                raise DriverError("worker operation arguments exceed bound")
            result = await asyncio.to_thread(client.call, "worker.operation", {
                "job_id": job_id, "epoch": epoch, "contract_sha256": contract_sha256,
                "operation": operation, "arguments": arguments,
            })
            if (result.get("job_id") != job_id or result.get("contract_sha256") != contract_sha256
                    or result.get("operation") != operation or not result.get("receipt_id")):
                raise DriverError("worker receipt does not match the scoped operation")
            body = json.dumps(result, allow_nan=False)
            if len(body.encode()) > MAX_OUTPUT:
                raise DriverError("worker output exceeds bound; use a scoped artifact")
            return {"content": [{"type": "text", "text": body}],
                    "isError": result.get("state") != "completed"}
        tools.append(sdk.tool(operation, f"Use the scoped task worker to {operation}.",
                              schemas[operation])(callback))
    return tools
