"""CachingTTSProvider: Decorator pattern -- wraps any TTSProvider, written
once instead of per adapter (plan.md Milestone 3.3, CLAUDE.md Decorator).

Cache key is hash(text + provider + voice) -- NOT chunk ID (a chunk ID is
session-scoped and not content-derived, see ADR-4) and NOT speed (speed is
applied client-side per ADR-3, so keying on it would re-synthesize the whole
book on every speed change).
"""

from __future__ import annotations

import hashlib

from app.application.ports import AudioCache, SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice


def cache_key(text: str, provider: str, voice_id: str) -> str:
    digest = hashlib.sha256(f"{provider}:{voice_id}:{text}".encode()).hexdigest()
    return f"{provider}:{voice_id}:{digest}"


class CachingTTSProvider(TTSProvider):
    def __init__(self, wrapped: TTSProvider, cache: AudioCache) -> None:
        self._wrapped = wrapped
        self._cache = cache
        self.name = wrapped.name

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        key = cache_key(text, settings.provider, settings.voice_id)

        cached = await self._cache.get(key)
        if cached is not None:
            return SynthesisResult(audio_bytes=cached)

        result = await self._wrapped.synthesize(text, settings)
        await self._cache.put(key, result.audio_bytes)
        return result

    async def list_voices(self) -> list[Voice]:
        return await self._wrapped.list_voices()
