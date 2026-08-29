"""`/tts/providers` is what the client's picker is built from, so what it
does and doesn't list is a contract, not a detail."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_provider_registry
from app.infrastructure.tts.registry import ProviderRegistry
from app.main import app
from tests.conftest import FakeTTSProvider


def test_lists_only_registered_providers_with_voice_names() -> None:
    """A provider missing its API key is never registered, so it can't be
    offered and then fail -- the picker simply doesn't show it."""
    registry = ProviderRegistry()
    registry.register(FakeTTSProvider())
    app.dependency_overrides[get_provider_registry] = lambda: registry
    try:
        response = TestClient(app).get("/tts/providers")

        assert response.status_code == 200
        assert response.json() == [{"name": "fake", "voices": [{"id": "fake-voice", "name": "Fake Voice"}]}]
    finally:
        app.dependency_overrides.clear()
