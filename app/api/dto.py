"""API-boundary DTOs. Domain entities never cross this line directly --
keeps domain/ ignorant of Pydantic/FastAPI (dependency rule, CLAUDE.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.domain.entities import (
    Block,
    Book,
    Chapter,
    Chunk,
    CodeBlock,
    HeadingBlock,
    ImageBlock,
    Segment,
    TextBlock,
)


class ChunkDTO(BaseModel):
    id: str
    index: int
    text: str

    @classmethod
    def from_domain(cls, chunk: Chunk) -> ChunkDTO:
        return cls(id=chunk.id, index=chunk.index, text=chunk.text)


class SegmentDTO(BaseModel):
    """A run of a paragraph plus the chunk that voices it, or null when it
    is shown but never spoken (a formula, an inline snippet, or text past
    the synthesis budget)."""

    text: str
    chunk_id: str | None = None

    @classmethod
    def from_domain(cls, segment: Segment) -> SegmentDTO:
        return cls(text=segment.text, chunk_id=segment.chunk_id)


class BlockDTO(BaseModel):
    """One renderable element of a chapter, tagged by `kind` so the client
    can match on it exhaustively (the Dart side mirrors this as a sealed
    class). A block is selectable for synthesis where it carries chunk IDs
    -- `text` through its segments, `heading` directly; `image` and `code`
    are shown but never read aloud."""

    kind: Literal["text", "heading", "image", "code"]
    segments: list[SegmentDTO] = []
    chunk_ids: list[str] = []
    text: str = ""
    level: int = 0
    src: str = ""
    alt: str = ""

    @classmethod
    def from_domain(cls, block: Block) -> BlockDTO:
        match block:
            case TextBlock(segments=segments):
                return cls(kind="text", segments=[SegmentDTO.from_domain(s) for s in segments])
            case HeadingBlock(text=text, level=level, chunk_ids=chunk_ids):
                return cls(kind="heading", text=text, level=level, chunk_ids=list(chunk_ids))
            case ImageBlock(src=src, alt=alt):
                return cls(kind="image", src=src, alt=alt)
            case CodeBlock(text=text):
                return cls(kind="code", text=text)


class ChapterDTO(BaseModel):
    id: str
    title: str
    order: int
    # Printed page the chapter starts on; null unless the book carries
    # page markers from a print edition.
    page: str | None = None
    chunks: list[ChunkDTO]
    blocks: list[BlockDTO]

    @classmethod
    def from_domain(cls, chapter: Chapter) -> ChapterDTO:
        return cls(
            id=chapter.id,
            title=chapter.title,
            order=chapter.order,
            page=chapter.page,
            chunks=[ChunkDTO.from_domain(c) for c in chapter.chunks],
            blocks=[BlockDTO.from_domain(b) for b in chapter.blocks],
        )


class BookDTO(BaseModel):
    id: str
    title: str
    chapters: list[ChapterDTO]
    first_chapter_id: str | None

    @classmethod
    def from_domain(cls, book: Book) -> BookDTO:
        first = book.first_chapter()
        return cls(
            id=book.id,
            title=book.title,
            chapters=[ChapterDTO.from_domain(c) for c in book.chapters],
            first_chapter_id=first.id if first else None,
        )


class ErrorDTO(BaseModel):
    error: str
    detail: str
