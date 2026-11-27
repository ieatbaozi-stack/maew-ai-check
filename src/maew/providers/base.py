"""Base provider abstraction and pluggable registry.

Designed so adding new AI providers (OpenRouter, GitHub Copilot, Codex, etc.)
only requires implementing ``Provider`` and registering it in ``ProviderRegistry``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import UsageSnapshot


class Provider(ABC):
    id: str = ""
    display_name: str = ""
    short_label: str = ""
    kind: str = "cli"  # "cli" | "local_logs" | "web" | "api_key"

    @abstractmethod
    def fetch(self) -> UsageSnapshot:
        """Synchronously collect a usage snapshot (called on a worker thread)."""
        raise NotImplementedError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Provider | None:
        return self._providers.get(provider_id)

    def all(self) -> list[Provider]:
        return list(self._providers.values())

    def ids(self) -> list[str]:
        return list(self._providers.keys())
