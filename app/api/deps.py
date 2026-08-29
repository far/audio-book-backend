"""Composition root: concretes are wired here only (plan.md Milestone 1.1
DIP rule). Routers depend on these via FastAPI's Depends(), never
constructing infrastructure themselves.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.api.config import settings
from app.application.ports import BookParser, SessionStore, TTSProvider
from app.application.use_cases import IngestBook
from app.infrastructure.cache.filesystem_cache import FilesystemAudioCache
from app.infrastructure.parsers.epub_parser import EbooklibParser
from app.infrastructure.session_store import InMemorySessionStore
from app.infrastructure.tts.caching import CachingTTSProvider
from app.infrastructure.tts.encoding import EncodingTTSProvider
from app.infrastructure.tts.piper_provider import PiperProvider
from app.infrastructure.tts.registry import ProviderRegistry


@lru_cache
def get_worker_pool() -> ThreadPoolExecutor:
    # Shared by Piper inference and Opus transcoding -- both are blocking
    # CPU work that must never run inline in a request handler.
    return ThreadPoolExecutor(max_workers=settings.synthesis_worker_pool_size)


@lru_cache
def get_session_store() -> SessionStore:
    return InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)


@lru_cache
def get_audio_cache() -> FilesystemAudioCache:
    return FilesystemAudioCache(settings.tmp_dir / "audio_cache")


@lru_cache
def get_parsers() -> list[BookParser]:
    return [EbooklibParser(max_uncompressed_bytes=settings.max_epub_uncompressed_bytes)]


def _build_provider(base: TTSProvider) -> TTSProvider:
    """Wraps a raw provider with the decorators every provider gets:
    encoding to Opus, then caching outside it, so a cache hit costs neither
    an API call nor a transcode.

    There was a retry decorator here too. Removed: Piper is the default and
    its failures are deterministic (a missing model, a missing ffmpeg), so
    retrying never helped the common case, and a failed chunk isn't fatal --
    the reader can tap the paragraph again. Reintroduce it only if a paid
    provider's transient failures actually prove to be a problem.
    """
    encoded = EncodingTTSProvider(base, get_worker_pool())
    return CachingTTSProvider(encoded, get_audio_cache())


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()

    piper = PiperProvider(settings.voice_path, get_worker_pool())
    registry.register(_build_provider(piper))

    # Registered only when their key is configured, so `/tts/providers`
    # never offers something that would fail on first use.
    if settings.elevenlabs_api_key:
        from app.infrastructure.tts.elevenlabs_provider import ElevenLabsProvider

        registry.register(_build_provider(ElevenLabsProvider(settings.elevenlabs_api_key)))
    if settings.openai_api_key:
        from app.infrastructure.tts.openai_provider import OpenAITTSProvider

        registry.register(_build_provider(OpenAITTSProvider(settings.openai_api_key)))

    return registry


def get_ingest_book_use_case() -> IngestBook:
    return IngestBook(
        parsers=get_parsers(),
        session_store=get_session_store(),
        max_characters=settings.max_characters_per_session,
    )

