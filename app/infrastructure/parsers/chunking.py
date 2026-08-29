"""Sentence-level chunking with asymmetric first-chunk sizing (plan.md
Milestone 2): the first chunk of a chapter is a single short sentence so
the very first thing a listener hears arrives as fast as possible; later
chunks are grouped larger to reduce request/synthesis overhead.
"""

from __future__ import annotations

import re
import uuid

from app.domain.entities import Chunk

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")

_FIRST_CHUNK_SENTENCES = 1
_LATER_CHUNK_SENTENCES = 3


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    sentences = _SENTENCE_BOUNDARY.split(text)
    return [s.strip() for s in sentences if s.strip()]


def chunk_block_text(
    chapter_id: str,
    text: str,
    start_index: int = 0,
    first_chunk_is_short: bool = True,
) -> list[Chunk]:
    """Chunks one block of prose, numbering from `start_index`.

    Chunks never span blocks: a paragraph break is a hard boundary, so the
    reader can highlight within the paragraph the listener is looking at.
    `first_chunk_is_short` carries the asymmetric sizing -- the caller
    passes it only for the first prose block of a chapter, since that's the
    one whose latency the listener actually feels.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    groups: list[list[str]] = []
    i = 0
    if first_chunk_is_short:
        groups.append(sentences[:_FIRST_CHUNK_SENTENCES])
        i = _FIRST_CHUNK_SENTENCES
    while i < len(sentences):
        groups.append(sentences[i : i + _LATER_CHUNK_SENTENCES])
        i += _LATER_CHUNK_SENTENCES

    chunks: list[Chunk] = []
    for offset, group in enumerate(g for g in groups if g):
        chunks.append(
            Chunk(
                id=str(uuid.uuid4()),
                chapter_id=chapter_id,
                index=start_index + offset,
                text=" ".join(group),
            )
        )
    return chunks


def chunk_chapter_text(chapter_id: str, text: str) -> list[Chunk]:
    """Chunks a whole chapter as one undifferentiated run of prose.

    Retained for callers that have no block structure to work from; the
    parser uses `chunk_block_text` per block instead.
    """
    return chunk_block_text(chapter_id, text)
