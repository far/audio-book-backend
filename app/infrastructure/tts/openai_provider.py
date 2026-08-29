"""OpenAI TTS adapter. Paid API -- registered only when its API key is
configured (see api/deps.py), so it is absent rather than broken when it
isn't set up.
"""

from __future__ import annotations

import httpx

from app.application.ports import SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice
from app.domain.errors import ProviderError

_API_URL = "https://api.openai.com/v1/audio/speech"


class OpenAITTSProvider(TTSProvider):
    name = "openai"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": "tts-1", "input": text, "voice": settings.voice_id},
            )
        if response.status_code != 200:
            raise ProviderError(provider=self.name, reason=f"HTTP {response.status_code}: {response.text[:200]}")
        return SynthesisResult(audio_bytes=response.content, mime_type="audio/mpeg")

    async def list_voices(self) -> list[Voice]:
        # Fixed set, documented by OpenAI -- no endpoint to query.
        return [
            Voice(id=v, provider=self.name, name=v.capitalize(), language="en")
            for v in ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
        ]
