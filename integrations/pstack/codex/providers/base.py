"""Provider-owned execution facts are separate from requested worker settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderUnavailable(RuntimeError):
    pass


class ExecutionProvider(Protocol):
    """Implemented by a separately installed, qualified provider driver.

    launch must use the persisted token, inspect must read authoritative provider
    state, and terminate must return a request receipt, never assumed termination.
    No default endpoint or claimed native Cloud history is supplied here.
    """

    def launch(self, *, token: str, request: dict) -> dict: ...
    def inspect(self, *, provider_ids: dict) -> dict: ...
    def terminate(self, *, provider_ids: dict) -> dict: ...


@dataclass(frozen=True)
class ProviderRegistration:
    driver: ExecutionProvider
    version: str
    capabilities: frozenset[str]
    qualification_ref: str


class ProviderRegistry:
    """Trusted service configuration only, never populated by a worker receipt."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(self, name: str, registration: ProviderRegistration) -> None:
        if not name or not registration.version or not registration.qualification_ref:
            raise ValueError("provider identity, version and qualification reference required")
        if "native_cloud_history" in registration.capabilities:
            raise ValueError("execution drivers cannot certify native Cloud history")
        if name in self._providers:
            raise ValueError("provider already registered")
        self._providers[name] = registration

    def require(self, name: str, capabilities: set[str]) -> ProviderRegistration:
        provider = self._providers.get(name)
        if provider is None or not capabilities <= provider.capabilities:
            raise ProviderUnavailable("required provider capability is not configured")
        return provider

    def capabilities(self) -> dict:
        return {
            "native_cloud_history": False,
            "providers": {
                name: {
                    "version": p.version,
                    "capabilities": sorted(p.capabilities),
                    "qualification_ref": p.qualification_ref,
                }
                for name, p in sorted(self._providers.items())
            },
        }
