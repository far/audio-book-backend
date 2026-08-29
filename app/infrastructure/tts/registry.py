"""Provider registry -- lookup by name. Adding a provider means one new
adapter file + one entry here, nothing else (OCP check, plan.md Milestone
3.1 and CLAUDE.md OCP section)."""

from __future__ import annotations

from app.application.ports import TTSProvider
from app.domain.errors import ProviderError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TTSProvider] = {}

    def register(self, provider: TTSProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> TTSProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ProviderError(provider=name, reason="not registered")
        return provider

    def list_names(self) -> list[str]:
        return sorted(self._providers.keys())
