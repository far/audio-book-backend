"""ElevenLabs voice listing. The adapter had no tests at all, and
`list_voices` is the part most likely to fail in the field: it depends on
a live API, a valid key, and a response shape we don't control.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.infrastructure.tts.elevenlabs_provider import (
    _FALLBACK_VOICE_ID,
    ElevenLabsProvider,
)


def _mock_transport(provider: ElevenLabsProvider, handler: Any) -> None:
    """Swaps in a fake transport so no real request is made."""
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, **kwargs)

    httpx.AsyncClient.__init__ = patched  # type: ignore[method-assign]
    provider._restore = lambda: setattr(httpx.AsyncClient, "__init__", original)  # type: ignore[attr-defined]


@pytest.fixture
def provider() -> Any:
    made = ElevenLabsProvider("key")
    yield made
    restore = getattr(made, "_restore", None)
    if restore:
        restore()


async def test_lists_the_accounts_voices_with_their_names(provider: ElevenLabsProvider) -> None:
    """A picker showing `21m00Tcm4TlvDq8ikWAM` is unusable -- the name is
    the whole point of listing."""
    _mock_transport(
        provider,
        lambda request: httpx.Response(
            200,
            json={
                "voices": [
                    {"voice_id": "v1", "name": "Rachel", "labels": {"language": "en"}},
                    {"voice_id": "v2", "name": "Domi", "labels": {}},
                ]
            },
        ),
    )

    voices = await provider.list_voices()

    assert [(v.id, v.name) for v in voices] == [("v1", "Rachel"), ("v2", "Domi")]
    assert all(v.provider == "elevenlabs" for v in voices)


async def test_a_bad_key_falls_back_instead_of_failing(provider: ElevenLabsProvider) -> None:
    """`/tts/providers` lists every provider, so one bad key must not take
    the endpoint down for the others."""
    _mock_transport(provider, lambda request: httpx.Response(401, json={"detail": "invalid key"}))

    voices = await provider.list_voices()

    assert [v.id for v in voices] == [_FALLBACK_VOICE_ID]


async def test_a_network_failure_falls_back(provider: ElevenLabsProvider) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    _mock_transport(provider, boom)

    voices = await provider.list_voices()

    assert [v.id for v in voices] == [_FALLBACK_VOICE_ID]


async def test_a_successful_list_is_fetched_once(provider: ElevenLabsProvider) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"voices": [{"voice_id": "v1", "name": "Rachel"}]})

    _mock_transport(provider, handler)

    await provider.list_voices()
    await provider.list_voices()

    assert calls == 1, "called on every /tts/providers request -- must be cached"


async def test_a_failure_is_not_cached(provider: ElevenLabsProvider) -> None:
    """Otherwise a key fixed after a failed attempt needs a restart."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    _mock_transport(provider, handler)

    await provider.list_voices()
    await provider.list_voices()

    assert calls == 2
