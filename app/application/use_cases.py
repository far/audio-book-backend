"""Use cases: application logic, depending only on ports (domain/ + this
module's own abstractions). Concretes are wired at the composition root
(app/api/deps.py), never imported here directly.
"""

from __future__ import annotations

import asyncio
import uuid

from app.application.ports import BookParser, SessionStore, TTSProvider
from app.application.result import Err, Ok, Result
from app.domain.entities import (
    Block,
    Book,
    Chapter,
    Chunk,
    HeadingBlock,
    Segment,
    TextBlock,
    TTSSettings,
    chunk_ids_of,
)
from app.domain.errors import (
    ChunkNotFoundError,
    EmptyBookError,
    InvalidUploadError,
    ProviderError,
    UnsupportedFormatError,
)


class IngestBook:
    """Milestone 2: parse an upload into a Book and persist it in the session store.

    Books longer than `max_characters` are truncated rather than rejected --
    the reader gets the first part of the book, up to the budget, instead of
    an outright failure. `max_characters` still exists to bound synthesis
    cost per session (an unbounded upload is an unbounded bill against paid
    providers), it just no longer blocks the upload entirely.
    """

    def __init__(self, parsers: list[BookParser], session_store: SessionStore, max_characters: int) -> None:
        self._parsers = parsers
        self._session_store = session_store
        self._max_characters = max_characters

    async def execute(
        self, filename: str, content: bytes
    ) -> Result[Book, InvalidUploadError | UnsupportedFormatError | EmptyBookError]:
        if not content:
            return Err(InvalidUploadError(reason="empty file"))

        parser = next((p for p in self._parsers if p.can_parse(filename, content)), None)
        if parser is None:
            suffix = filename.rsplit(".", 1)[-1] if "." in filename else filename
            return Err(UnsupportedFormatError(format=suffix))

        book_id = str(uuid.uuid4())
        try:
            # Off the event loop: parsing is CPU-bound (zip inflate, then
            # BeautifulSoup over every chapter) and measured at ~1.25s for a
            # 0.3MB EPUB. Run inline it froze the whole service for that
            # long -- health checks and other listeners' audio included --
            # which on a single-vCPU host is the difference between a slow
            # upload and an unresponsive server.
            book = await asyncio.to_thread(parser.parse, book_id, content)
        except Exception as exc:  # noqa: BLE001 -- parser failures are all "invalid upload" to us
            return Err(InvalidUploadError(reason=str(exc)))

        book = self._truncate_to_budget(book)

        if not book.chapters or book.first_chapter() is None:
            return Err(EmptyBookError())

        await self._session_store.save_book(book)
        return Ok(book)

    def _truncate_to_budget(self, book: Book) -> Book:
        """Keeps whole chunks (never cuts mid-sentence) up to the character
        budget, in chapter/block order, then drops everything after.

        Blocks are pruned to match: a TextBlock keeps only the chunk IDs
        that survived, and one left with none is dropped along with any
        headings or images past the cutoff. A block referencing a chunk
        that no longer exists would render as tappable text whose audio can
        never be fetched, so the two have to be truncated together.
        """
        remaining = self._max_characters
        kept_chapters: list[Chapter] = []

        for chapter in book.chapters:
            if remaining <= 0:
                break

            chunks_by_id = {c.id: c for c in chapter.chunks}
            kept_blocks: list[Block] = []
            kept_chunks: list[Chunk] = []

            for block in chapter.blocks:
                ids = chunk_ids_of(block)
                if not ids:
                    # Images and code cost nothing to synthesize, so they
                    # ride along rather than being dropped for a budget
                    # they don't consume.
                    kept_blocks.append(block)
                    continue

                dropped: set[str] = set()
                for chunk_id in ids:
                    chunk = chunks_by_id.get(chunk_id)
                    if chunk is None:
                        continue
                    if remaining <= 0:
                        dropped.add(chunk_id)
                        continue
                    kept_chunks.append(chunk)
                    remaining -= len(chunk.text)

                kept_blocks.append(_without_chunks(block, dropped))

            if kept_chunks:
                kept_chapters.append(
                    Chapter(
                        id=chapter.id,
                        title=chapter.title,
                        order=chapter.order,
                        chunks=tuple(kept_chunks),
                        blocks=tuple(kept_blocks),
                    )
                )

        return Book(id=book.id, title=book.title, chapters=tuple(kept_chapters))


def _without_chunks(block: Block, dropped: set[str]) -> Block:
    """Strips the given chunks from a block without removing their text --
    truncation bounds synthesis cost, not what the reader can see."""
    if not dropped:
        return block
    match block:
        case TextBlock(segments=segments):
            return TextBlock(
                segments=tuple(
                    Segment(text=s.text) if s.chunk_id in dropped else s for s in segments
                )
            )
        case HeadingBlock(text=text, level=level, chunk_ids=chunk_ids):
            return HeadingBlock(
                text=text, level=level, chunk_ids=tuple(c for c in chunk_ids if c not in dropped)
            )
        case _:
            return block


class SynthesizeChunk:
    """Milestone 3/4: resolve a chunk ID to text (ADR-4), synthesize via the
    caching-decorated provider, and return audio bytes.

    `provider` is expected to already be wrapped in CachingTTSProvider by the
    composition root -- this use case doesn't know or care that caching is
    happening, which is the point of the decorator (Milestone 3.3)."""

    def __init__(self, provider: TTSProvider, session_store: SessionStore) -> None:
        self._provider = provider
        self._session_store = session_store

    async def execute(self, chunk_id: str, settings: TTSSettings) -> Result[bytes, ChunkNotFoundError | ProviderError]:
        text = await self._session_store.get_chunk_text(chunk_id)
        if text is None:
            return Err(ChunkNotFoundError(chunk_id=chunk_id))

        try:
            result = await self._provider.synthesize(text, settings)
        except Exception as exc:  # noqa: BLE001 -- provider failures surface as ProviderError
            return Err(ProviderError(provider=self._provider.name, reason=str(exc)))

        return Ok(result.audio_bytes)
