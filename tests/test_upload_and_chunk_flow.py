"""Integration test of the audio pipeline (plan.md Milestone 6): upload ->
extract -> synthesize -> chunk fetch, through the real HTTP layer.

Uses a dependency override to swap in FakeTTSProvider instead of real
Piper/ffmpeg -- fast and deterministic, and doesn't require the voice model
to be downloaded. See test_piper_provider_real.py for the one test that
exercises real synthesis.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_provider_registry
from app.infrastructure.tts.registry import ProviderRegistry
from app.main import app
from tests.conftest import FakeTTSProvider, build_epub_bytes


def _client_with_fake_provider() -> tuple[TestClient, FakeTTSProvider]:
    fake = FakeTTSProvider()
    registry = ProviderRegistry()
    registry.register(fake)
    app.dependency_overrides[get_provider_registry] = lambda: registry
    return TestClient(app), fake


def test_full_upload_to_chunk_fetch_flow() -> None:
    client, fake = _client_with_fake_provider()
    try:
        upload_response = client.post(
            "/upload", files={"file": ("test.epub", build_epub_bytes(), "application/epub+zip")}
        )
        assert upload_response.status_code == 200
        book = upload_response.json()
        assert len(book["chapters"]) == 1
        first_chunk = book["chapters"][0]["chunks"][0]

        chunk_response = client.get(f"/tts/chunk/{first_chunk['id']}", params={"provider": "fake"})
        assert chunk_response.status_code == 200
        assert chunk_response.content == f"AUDIO({first_chunk['text']})".encode()
        assert fake.calls == [first_chunk["text"]]

        session_response = client.get(f"/session/{book['id']}")
        assert session_response.status_code == 200
        assert session_response.json()["id"] == book["id"]
    finally:
        app.dependency_overrides.clear()


def test_upload_rejects_wrong_extension() -> None:
    client, _ = _client_with_fake_provider()
    try:
        response = client.post("/upload", files={"file": ("test.pdf", b"not an epub", "application/pdf")})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_upload_rejects_bad_magic_bytes() -> None:
    client, _ = _client_with_fake_provider()
    try:
        response = client.post(
            "/upload", files={"file": ("fake.epub", b"not a zip at all", "application/epub+zip")}
        )
        assert response.status_code == 422
        assert "magic bytes" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_fetching_unknown_chunk_returns_404() -> None:
    client, _ = _client_with_fake_provider()
    try:
        response = client.get("/tts/chunk/does-not-exist", params={"provider": "fake"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_fetching_unknown_session_returns_404() -> None:
    client, _ = _client_with_fake_provider()
    try:
        response = client.get("/session/does-not-exist")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
