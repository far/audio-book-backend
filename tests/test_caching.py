import os
from pathlib import Path
from unittest.mock import patch

from app.application.ports import AudioCache
from app.domain.entities import TTSSettings
from app.infrastructure.cache.filesystem_cache import FilesystemAudioCache
from app.infrastructure.tts.caching import CachingTTSProvider, cache_key
from tests.conftest import FakeTTSProvider


class InMemoryCache(AudioCache):
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.get_calls = 0
        self.put_calls = 0

    async def get(self, key: str) -> bytes | None:
        self.get_calls += 1
        return self.store.get(key)

    async def put(self, key: str, audio_bytes: bytes) -> None:
        self.put_calls += 1
        self.store[key] = audio_bytes


async def test_cache_miss_then_hit_only_synthesizes_once() -> None:
    fake = FakeTTSProvider()
    cache = InMemoryCache()
    provider = CachingTTSProvider(fake, cache)
    settings = TTSSettings(provider="fake", voice_id="fake-voice")

    result1 = await provider.synthesize("hello world", settings)
    result2 = await provider.synthesize("hello world", settings)

    assert result1.audio_bytes == result2.audio_bytes
    assert fake.calls == ["hello world"]  # only synthesized once


def test_cache_key_excludes_speed_by_construction() -> None:
    # Speed isn't a parameter of cache_key at all -- per ADR-3, keying on it
    # would re-synthesize the whole book on every speed change.
    key1 = cache_key("some text", "piper", "en_US-lessac-medium")
    key2 = cache_key("some text", "piper", "en_US-lessac-medium")
    assert key1 == key2


def test_cache_key_differs_by_voice() -> None:
    key1 = cache_key("some text", "piper", "voice-a")
    key2 = cache_key("some text", "piper", "voice-b")
    assert key1 != key2


def test_cache_key_differs_by_provider() -> None:
    key1 = cache_key("some text", "piper", "voice-a")
    key2 = cache_key("some text", "elevenlabs", "voice-a")
    assert key1 != key2


async def test_put_does_not_rescan_the_directory_every_time(tmp_path: Path) -> None:
    """Eviction needs the cache's total size, and recomputing it per write
    meant a stat() per cached file -- 29ms at 8,000 files, on the event
    loop, growing with uptime. The total is tracked instead."""
    cache = FilesystemAudioCache(tmp_path, max_total_bytes=10 * 1024 * 1024)
    blob = b"x" * 1024

    for i in range(50):
        await cache.put(f"warm{i}", blob)

    scans = 0
    original = FilesystemAudioCache._measure_total

    def counting_measure(self: FilesystemAudioCache) -> int:
        nonlocal scans
        scans += 1
        return original(self)

    with patch.object(FilesystemAudioCache, "_measure_total", counting_measure):
        for i in range(50):
            await cache.put(f"more{i}", blob)

    assert scans == 0, "well under budget -- no directory walk should happen"


async def test_evicts_oldest_first_when_over_budget(tmp_path: Path) -> None:
    blob = b"x" * 1024
    cache = FilesystemAudioCache(tmp_path, max_total_bytes=5 * 1024)

    for i in range(10):
        await cache.put(f"k{i}", blob)
        # Distinct mtimes, so "oldest" is well defined on coarse-grained
        # filesystems.
        os.utime(tmp_path / f"k{i}.audio", (i, i))

    await cache.put("newest", blob)

    assert await cache.get("k0") is None, "the oldest entry should have gone first"
    assert await cache.get("newest") == blob
    total = sum(f.stat().st_size for f in tmp_path.glob("*.audio"))
    assert total <= 5 * 1024


async def test_get_returns_none_for_a_missing_key(tmp_path: Path) -> None:
    cache = FilesystemAudioCache(tmp_path)

    assert await cache.get("never-written") is None
