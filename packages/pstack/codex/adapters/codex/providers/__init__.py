"""Explicit provider integration boundary; no provider is enabled by default."""

from .base import ProviderRegistry, ProviderUnavailable

__all__ = ["ProviderRegistry", "ProviderUnavailable"]
