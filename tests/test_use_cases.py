import asyncio
import time

from app.application.ports import BookParser
from app.application.result import Err, Ok
from app.application.use_cases import IngestBook, SynthesizeChunk
from app.domain.entities import Book, Chapter, Chunk, TTSSettings
from app.domain.errors import ChunkNotFoundError, EmptyBookError, UnsupportedFormatError
from app.infrastructure import session_store
from app.infrastructure.parsers.epub_parser import EbooklibParser
from app.infrastructure.session_store import InMemorySessionStore
from tests.conftest import FakeTTSProvider, build_epub_bytes


async def test_ingest_book_rejects_unsupported_format() -> None:
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=InMemorySessionStore(), max_characters=500_000)
    result = await use_case.execute("book.pdf", b"whatever")
    assert isinstance(result, Err)
    assert isinstance(result.error, UnsupportedFormatError)


async def test_ingest_book_rejects_empty_content() -> None:
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=InMemorySessionStore(), max_characters=500_000)
    result = await use_case.execute("book.epub", b"")
    assert isinstance(result, Err)


async def test_ingest_book_success_saves_to_session_store() -> None:
    store = InMemorySessionStore()
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=store, max_characters=500_000)

    result = await use_case.execute("book.epub", build_epub_bytes())
    assert isinstance(result, Ok)

    book = result.value
    assert await store.get_book(book.id) is not None


async def test_ingest_book_truncates_rather_than_rejects_oversized_books() -> None:
    store = InMemorySessionStore()
    # Two chapters, well over a tiny character budget -- should keep only
    # as many whole chunks as fit, not reject the upload outright.
    content = build_epub_bytes(
        chapters=[
            ("Chapter One", "This is a real body sentence one. " * 30),
            ("Chapter Two", "This is a real body sentence two. " * 30),
        ]
    )
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=store, max_characters=50)

    result = await use_case.execute("book.epub", content)
    assert isinstance(result, Ok)

    book = result.value
    total_chars = sum(len(chunk.text) for chapter in book.chapters for chunk in chapter.chunks)
    # Never cuts mid-chunk, so the kept text can run a bit over budget --
    # but must be far smaller than the untruncated book, and never empty.
    assert 0 < total_chars < 200
    assert book.chapters[0].title == "Chapter One"


async def test_ingest_book_truncation_never_cuts_a_chunk_in_half() -> None:
    store = InMemorySessionStore()
    content = build_epub_bytes(chapters=[("Chapter One", "This is a real body sentence one. " * 30)])
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=store, max_characters=10)

    result = await use_case.execute("book.epub", content)
    assert isinstance(result, Ok)

    book = result.value
    # Even with a budget smaller than a single chunk, at least one whole
    # chunk is kept -- truncation trims chunks, it doesn't mangle them.
    assert len(book.chapters[0].chunks) >= 1
    assert book.chapters[0].chunks[0].text  # non-empty, untruncated sentence


class _EmptyBookParser(BookParser):
    def can_parse(self, filename: str, content: bytes) -> bool:
        return True

    def parse(self, book_id: str, content: bytes) -> Book:
        return Book(id=book_id, title="Empty", chapters=())


async def test_ingest_book_rejects_book_with_no_chapters() -> None:
    use_case = IngestBook(parsers=[_EmptyBookParser()], session_store=InMemorySessionStore(), max_characters=500_000)
    result = await use_case.execute("book.epub", b"anything")
    assert isinstance(result, Err)
    assert isinstance(result.error, EmptyBookError)


async def test_synthesize_chunk_not_found() -> None:
    fake_provider = FakeTTSProvider()
    store = InMemorySessionStore()
    use_case = SynthesizeChunk(provider=fake_provider, session_store=store)

    result = await use_case.execute("nonexistent-id", TTSSettings(provider="fake", voice_id="fake-voice"))
    assert isinstance(result, Err)
    assert isinstance(result.error, ChunkNotFoundError)


async def test_synthesize_chunk_success() -> None:
    fake_provider = FakeTTSProvider()
    store = InMemorySessionStore()
    chunk = Chunk(id="chunk-1", chapter_id="chap-1", index=0, text="Hello there.")
    book = Book(id="book-1", title="T", chapters=(Chapter(id="chap-1", title="C1", order=0, chunks=(chunk,)),))
    await store.save_book(book)

    use_case = SynthesizeChunk(provider=fake_provider, session_store=store)
    result = await use_case.execute("chunk-1", TTSSettings(provider="fake", voice_id="fake-voice"))

    assert isinstance(result, Ok)
    assert result.value == b"AUDIO(Hello there.)"
    assert fake_provider.calls == ["Hello there."]


async def test_upload_does_not_block_the_event_loop() -> None:
    """Parsing is CPU-bound and used to run inline in the coroutine, so an
    upload froze every other request for its duration. On one vCPU that is
    the difference between a slow upload and a dead service."""
    store = InMemorySessionStore()
    body = " ".join(f"Sentence number {i} of the chapter body." for i in range(400))
    content = build_epub_bytes(chapters=[(f"Chapter {i}", body) for i in range(25)])
    use_case = IngestBook(parsers=[EbooklibParser()], session_store=store, max_characters=10_000_000)

    ticks = 0

    async def heartbeat() -> None:
        # Stands in for every other request the server should still serve.
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        result = await use_case.execute("book.epub", content)
    finally:
        beat.cancel()

    assert isinstance(result, Ok)
    assert ticks > 0, "the event loop made no progress during the upload"


async def test_playing_a_chunk_keeps_the_session_alive() -> None:
    """The TTL sweep used to only see `get_book`, which a client calls once
    when the socket opens. A listener past the TTL therefore had the book
    deleted mid-chapter, and every later chunk 404'd."""
    store = InMemorySessionStore()
    book = Book(
        id="b1",
        title="B",
        chapters=(Chapter(id="c1", title="One", order=0, chunks=(Chunk(id="k1", chapter_id="c1", index=0, text="hi"),)),),
    )
    await store.save_book(book)

    # Pretend the session was last touched longer ago than the TTL allows.
    store._last_touched["b1"] = time.monotonic() - (session_store._DEFAULT_SESSION_TTL_SECONDS + 60)

    assert await store.get_chunk_text("k1") == "hi"
    assert await store.cleanup_expired() == 0
    assert await store.get_book("b1") is not None
