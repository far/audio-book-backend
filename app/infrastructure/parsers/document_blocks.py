"""Turns a chapter's HTML into an ordered list of renderable blocks.

The reader shows the document roughly as an EPUB reader would -- headings
and images in place, not stripped -- while only prose is selectable for
synthesis. That means the parser can't flatten a chapter to one string:
it has to preserve document order across three kinds of block (see
domain.entities.Block).

Deliberately *not* a general HTML renderer. Inline markup (emphasis,
links, footnote markers) is flattened to its text, and tables are read as
their text content rather than laid out as tables. Rendering arbitrary
book CSS faithfully is a different project; this keeps the document
recognisable and the reading order correct, which is what the listener
needs.
"""

from __future__ import annotations

import posixpath

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.domain.entities import (
    Block,
    Chunk,
    CodeBlock,
    HeadingBlock,
    ImageBlock,
    Segment,
    TextBlock,
)

from .chunking import chunk_block_text, split_sentences
from .text_quality import is_prose_like

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

# Shown verbatim, never voiced: a synthesized listing is minutes of
# unintelligible punctuation.
_CODE_TAGS = {"pre", "code", "kbd", "samp"}

# Walked through rather than rendered -- their children are the real blocks.
_CONTAINER_TAGS = {"body", "html", "div", "section", "article", "main", "figure", "ul", "ol", "dl", "blockquote"}

# Never rendered: not ours to execute, or furniture that duplicates the
# chapter list we build ourselves.
_DROPPED_TAGS = ["script", "style", "nav", "head", "link", "meta"]


def _image_block(img: Tag, chapter_href: str) -> ImageBlock | None:
    src = img.get("src")
    if not isinstance(src, str) or not src:
        return None
    alt = img.get("alt")
    if src.startswith(("http://", "https://", "data:")):
        # Already addressable as-is; no archive lookup needed.
        return ImageBlock(src=src, alt=alt if isinstance(alt, str) else "")
    # EPUB srcs are relative to the *chapter document*, so they're resolved
    # against it here -- `../images/x.png` in `text/ch1.xhtml` is
    # `images/plate.png` at the archive root, which is the key the client
    # looks up in the .epub it still holds. Doing this in the parser keeps
    # EPUB path semantics in the one place that already understands them.
    href = posixpath.normpath(posixpath.join(posixpath.dirname(chapter_href), src))
    return ImageBlock(src=href.lstrip("/"), alt=alt if isinstance(alt, str) else "")


class _BlockBuilder:
    def __init__(self, chapter_id: str, chapter_href: str) -> None:
        self._chapter_id = chapter_id
        self._chapter_href = chapter_href
        self.blocks: list[Block] = []
        self.chunks: list[Chunk] = []
        self._prose_started = False

    def _chunk(self, text: str, *, short_first: bool = False) -> list[Chunk]:
        return chunk_block_text(self._chapter_id, text, start_index=len(self.chunks), first_chunk_is_short=short_first)

    def _add_prose(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            return

        segments: list[Segment] = []
        # Sentences are partitioned into runs of readable and unreadable
        # rather than judged one at a time, so a formula sitting between two
        # sentences doesn't split the prose around it into single-sentence
        # chunks (see ADR-3 on why chunk size matters).
        for readable, run in _runs(split_sentences(text)):
            joined = " ".join(run)
            if not readable:
                segments.append(Segment(text=joined))
                continue
            # Only the chapter's opening *paragraph* gets the short first
            # chunk (ADR-3) -- it's the one whose synthesis latency the
            # listener waits on. A heading ahead of it is a chunk of its
            # own and already short, so it doesn't consume the allowance.
            chunks = self._chunk(joined, short_first=not self._prose_started)
            if not chunks:
                segments.append(Segment(text=joined))
                continue
            self._prose_started = True
            self.chunks.extend(chunks)
            segments.extend(Segment(text=c.text, chunk_id=c.id) for c in chunks)

        if segments:
            self.blocks.append(TextBlock(segments=tuple(segments)))

    def _add_heading(self, text: str, level: int) -> None:
        chunks = self._chunk(text)
        self.chunks.extend(chunks)
        self.blocks.append(HeadingBlock(text=text, level=level, chunk_ids=tuple(c.id for c in chunks)))

    def visit(self, node: Tag) -> None:
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()

            if name == "img":
                image = _image_block(child, self._chapter_href)
                if image is not None:
                    self.blocks.append(image)
                continue

            if name in _HEADING_TAGS:
                text = " ".join(child.get_text(separator=" ", strip=True).split())
                if text:
                    self._add_heading(text, _HEADING_TAGS[name])
                continue

            if name in _CODE_TAGS:
                # Whitespace is meaningful in a listing, so it is kept as
                # written rather than collapsed the way prose is.
                code = child.get_text()
                if code.strip():
                    self.blocks.append(CodeBlock(text=code))
                continue

            # Images nested inside a block still get their own block, in
            # place, before that block's prose -- a figure's picture should
            # not disappear just because it sits inside a <p>.
            nested_images = [img for img in child.find_all("img") if isinstance(img, Tag)]

            if name in _CONTAINER_TAGS:
                self.visit(child)
                continue

            for img in nested_images:
                image = _image_block(img, self._chapter_href)
                if image is not None:
                    self.blocks.append(image)

            self._add_prose(child.get_text(separator=" ", strip=True))


def _runs(sentences: list[str]) -> list[tuple[bool, list[str]]]:
    """Groups consecutive sentences by whether they can be read aloud."""
    runs: list[tuple[bool, list[str]]] = []
    for sentence in sentences:
        readable = is_prose_like(sentence)
        if runs and runs[-1][0] == readable:
            runs[-1][1].append(sentence)
        else:
            runs.append((readable, [sentence]))
    return runs


def extract_blocks(chapter_id: str, chapter_href: str, soup: BeautifulSoup) -> tuple[list[Block], list[Chunk]]:
    """Returns the chapter's blocks in document order, plus every chunk
    they reference (also in reading order -- `Chunk.index` is the playback
    order, so it must match)."""
    for tag in soup(_DROPPED_TAGS):
        tag.decompose()

    builder = _BlockBuilder(chapter_id, chapter_href)
    builder.visit(soup.body or soup)
    return builder.blocks, builder.chunks
