"""In-memory SessionStore. Accepted v1 tradeoff: precludes horizontal
scaling (plan.md Milestone 1.3). Revisit with Redis if multi-instance is
ever needed -- until then this is the only SessionStore implementation.
"""

from __future__ import annotations

import asyncio
import time

from app.application.ports import SessionStore
from app.domain.entities import Book

_DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 2  # 2 hours


class InMemorySessionStore(SessionStore):
    def __init__(self, ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS) -> None:
        # Injected rather than read from config: infrastructure may not
        # import `api.config` (dependency rule).
        self._ttl_seconds = ttl_seconds
        self._books: dict[str, Book] = {}
        self._chunk_text: dict[str, str] = {}
        self._chunk_book: dict[str, str] = {}
        self._last_touched: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def save_book(self, book: Book) -> None:
        async with self._lock:
            self._books[book.id] = book
            self._last_touched[book.id] = time.monotonic()
            for chapter in book.chapters:
                for chunk in chapter.chunks:
                    self._chunk_text[chunk.id] = chunk.text
                    self._chunk_book[chunk.id] = book.id

    async def get_book(self, book_id: str) -> Book | None:
        async with self._lock:
            book = self._books.get(book_id)
            if book is not None:
                self._last_touched[book_id] = time.monotonic()
            return book

    async def get_chunk_text(self, chunk_id: str) -> str | None:
        async with self._lock:
            text = self._chunk_text.get(chunk_id)
            if text is not None:
                # Fetching audio counts as using the session. The TTL used
                # to only see `get_book`, which a client calls once when the
                # socket opens -- so anyone listening for longer than the
                # TTL had their book swept out mid-chapter, after which
                # every remaining chunk 404'd.
                book_id = self._chunk_book.get(chunk_id)
                if book_id is not None:
                    self._last_touched[book_id] = time.monotonic()
            return text

    async def cleanup_expired(self) -> int:
        """TTL sweep -- call periodically (e.g. from a background task)."""
        now = time.monotonic()
        async with self._lock:
            expired = [
                book_id
                for book_id, touched in self._last_touched.items()
                if now - touched > self._ttl_seconds
            ]
            for book_id in expired:
                self._books.pop(book_id, None)
                self._last_touched.pop(book_id, None)
                stale_chunks = [cid for cid, bid in self._chunk_book.items() if bid == book_id]
                for cid in stale_chunks:
                    self._chunk_text.pop(cid, None)
                    self._chunk_book.pop(cid, None)
            return len(expired)
