"""Filesystem-backed AudioCache with LRU-by-mtime eviction
(plan.md Milestone 3.3 "cache eviction policy").
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.application.ports import AudioCache


class FilesystemAudioCache(AudioCache):
    """Caches synthesized audio on disk, bounded by total size.

    Two things this deliberately avoids, both of which it used to do:

    **Scanning the directory on every write.** Eviction needs the total
    size, and recomputing it meant a `glob` plus a `stat` per file on each
    `put` -- measured at 0.8ms for 200 files, 7.6ms for 2,000 and 29ms for
    8,000, all of it on the event loop. A 500MB cache is tens of thousands
    of chunks, so the cost grew unbounded with uptime. The total is now
    tracked in memory and the directory is only walked when it says we are
    over budget.

    **Blocking file I/O in a coroutine.** Reads and writes run in a thread,
    so a slow disk stalls one request rather than the whole service.
    """

    def __init__(self, cache_dir: Path, max_total_bytes: int = 500 * 1024 * 1024) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_total_bytes = max_total_bytes
        self._lock = asyncio.Lock()
        self._total_bytes: int | None = None  # None until first measured

    def _path_for(self, key: str) -> Path:
        # Keys are already hash-derived (see caching.py); safe as a filename.
        return self._cache_dir / f"{key}.audio"

    async def get(self, key: str) -> bytes | None:
        path = self._path_for(key)
        try:
            # Touch for LRU, then read. Both off the loop, and outside the
            # lock: reads don't mutate the size accounting, so serialising
            # them would only add latency.
            return await asyncio.to_thread(self._read_and_touch, path)
        except FileNotFoundError:
            return None

    @staticmethod
    def _read_and_touch(path: Path) -> bytes:
        data = path.read_bytes()
        path.touch()  # bump mtime for LRU
        return data

    async def put(self, key: str, audio_bytes: bytes) -> None:
        async with self._lock:
            written = await asyncio.to_thread(self._write, self._path_for(key), audio_bytes)
            if self._total_bytes is None:
                self._total_bytes = await asyncio.to_thread(self._measure_total)
            else:
                self._total_bytes += written

            if self._total_bytes > self._max_total_bytes:
                self._total_bytes = await asyncio.to_thread(self._evict)

    @staticmethod
    def _write(path: Path, audio_bytes: bytes) -> int:
        previous = path.stat().st_size if path.exists() else 0
        path.write_bytes(audio_bytes)
        return len(audio_bytes) - previous

    def _measure_total(self) -> int:
        return sum(f.stat().st_size for f in self._cache_dir.glob("*.audio"))

    def _evict(self) -> int:
        """Drops oldest-first until under budget. Returns the new total.

        Re-measures from disk rather than trusting the running count: this
        is the one path where being wrong matters, and it is rare enough to
        afford the walk.
        """
        files = sorted(self._cache_dir.glob("*.audio"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        for f in files:
            if total <= self._max_total_bytes:
                break
            try:
                total -= f.stat().st_size
                f.unlink()
            except FileNotFoundError:
                continue  # evicted concurrently; the size was already counted out
        return total
