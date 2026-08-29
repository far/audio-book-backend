from __future__ import annotations

import io

import pytest
from ebooklib import epub

from app.application.ports import SynthesisResult, TTSProvider
from app.domain.entities import TTSSettings, Voice


class FakeTTSProvider(TTSProvider):
    """Stub provider for tests that don't need real Piper/ffmpeg -- fast,
    deterministic, and works without the voice model or ffmpeg installed."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult:
        self.calls.append(text)
        return SynthesisResult(audio_bytes=f"AUDIO({text})".encode(), mime_type="audio/wav")

    async def list_voices(self) -> list[Voice]:
        return [Voice(id="fake-voice", provider=self.name, name="Fake Voice")]


@pytest.fixture
def fake_provider() -> FakeTTSProvider:
    return FakeTTSProvider()


def build_epub_bytes(
    *,
    title: str = "Test Book",
    chapters: list[tuple[str, str]] | None = None,
    with_image: bool = False,
) -> bytes:
    """Builds a minimal in-memory EPUB. chapters is a list of (heading, body)
    pairs; body should be long enough to clear _MIN_CHAPTER_WORDS.

    `with_image` adds an image item under `images/` and references it from
    every chapter with a chapter-relative src, which is the case that
    exercises href resolution."""
    if chapters is None:
        chapters = [("Chapter One", _default_body())]

    book = epub.EpubBook()
    book.set_identifier("test-book-id")
    book.set_title(title)
    book.set_language("en")

    if with_image:
        image = epub.EpubItem(
            uid="img1",
            file_name="images/plate.png",
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n",
        )
        book.add_item(image)

    items = []
    for i, (heading, body) in enumerate(chapters):
        item = epub.EpubHtml(title=heading, file_name=f"text/chap{i}.xhtml", lang="en")
        picture = '<img src="../images/plate.png" alt="A plate"/>' if with_image else ""
        item.content = f"<h1>{heading}</h1><p>{body}</p>{picture}"
        book.add_item(item)
        items.append(item)

    book.toc = tuple(epub.Link(item.file_name, item.title, item.file_name) for item in items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def _default_body(n: int = 20) -> str:
    return " ".join(f"This is sentence number {i} in the chapter." for i in range(n))
