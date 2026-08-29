"""The reader shows the document, not just its text: blocks must come back
in document order, with images and headings preserved in place and only
prose carrying chunk IDs.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.application.use_cases import IngestBook
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
    chunk_ids_of,
)
from app.infrastructure.parsers.document_blocks import extract_blocks

_CHAPTER_HTML = """
<html><body>
  <h1>Chapter One</h1>
  <p>The first sentence. The second sentence. The third sentence.</p>
  <img src="../images/plate.png" alt="A plate"/>
  <p>A later paragraph.</p>
  <script>ignored()</script>
</body></html>
"""


_CHAPTER_HTML_WITH_CODE = """
<html><body>
  <h1>Chapter One</h1>
  <p>Some prose here.</p>
  <pre>def demo():
    print(1)</pre>
  <img src="images/plate.png" alt="A plate"/>
</body></html>
"""


def _blocks(html: str = _CHAPTER_HTML, href: str = "text/ch1.xhtml") -> tuple[list[Block], list[Chunk]]:
    return extract_blocks("chap-1", href, BeautifulSoup(html, "html.parser"))


def test_blocks_preserve_document_order_and_kind() -> None:
    blocks, _ = _blocks()

    assert [type(b) for b in blocks] == [HeadingBlock, TextBlock, ImageBlock, TextBlock]
    assert isinstance(blocks[0], HeadingBlock)
    assert (blocks[0].text, blocks[0].level) == ("Chapter One", 1)


def test_image_src_is_resolved_against_the_chapter_not_the_archive_root() -> None:
    """`../images/plate.png` from `text/ch1.xhtml` is `images/plate.png` at
    the archive root -- the client looks it up by that key."""
    blocks, _ = _blocks()

    image = next(b for b in blocks if isinstance(b, ImageBlock))
    assert image.src == "images/plate.png"
    assert image.alt == "A plate"


def test_images_and_code_are_shown_but_never_read() -> None:
    """Prose and headings are voiced; images and code listings are
    rendered and skipped -- a synthesized listing is minutes of
    unintelligible punctuation."""
    blocks, chunks = _blocks(_CHAPTER_HTML_WITH_CODE)

    readable = [b for b in blocks if chunk_ids_of(b)]
    assert all(isinstance(b, (TextBlock, HeadingBlock)) for b in readable)
    assert all(not chunk_ids_of(b) for b in blocks if isinstance(b, (ImageBlock, CodeBlock)))
    # Every chunk belongs to exactly one block, and nothing else is readable.
    assert sorted(cid for b in blocks for cid in chunk_ids_of(b)) == sorted(c.id for c in chunks)
    assert not any("print(" in c.text for c in chunks)


def test_code_keeps_its_own_whitespace() -> None:
    """Indentation is meaningful in a listing, so it is not collapsed the
    way prose is."""
    blocks, _ = _blocks(_CHAPTER_HTML_WITH_CODE)

    code = next(b for b in blocks if isinstance(b, CodeBlock))
    assert "    print(1)" in code.text


def test_chunks_never_span_paragraphs() -> None:
    """A paragraph break is a hard chunk boundary: the listener's highlight
    has to stay inside the paragraph they're looking at."""
    blocks, chunks = _blocks()

    text_blocks = [b for b in blocks if isinstance(b, TextBlock)]
    first = " ".join(s.text for s in text_blocks[0].segments)
    assert "later paragraph" not in first
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_first_chunk_of_the_chapter_is_a_single_sentence() -> None:
    """ADR-3's asymmetric sizing survives the move to per-block chunking --
    it applies once per chapter, not once per paragraph. The chapter opens
    on its heading, which is a chunk of its own."""
    _, chunks = _blocks()

    assert chunks[0].text == "Chapter One"
    assert chunks[1].text == "The first sentence."
    assert chunks[2].text.startswith("The second sentence.")


def test_scripts_and_styles_are_dropped() -> None:
    blocks, chunks = _blocks()

    assert "ignored" not in " ".join(c.text for c in chunks)
    assert len(blocks) == 4


def test_truncation_unvoices_dropped_text_without_hiding_it() -> None:
    """Truncation bounds synthesis cost, not what the reader can see: text
    past the budget stays on the page as an unvoiced segment rather than
    vanishing, and no block is left pointing at a chunk that's gone."""
    chunks = tuple(Chunk(id=f"c{i}", chapter_id="chap-1", index=i, text="x" * 40) for i in range(4))
    chapter = Chapter(
        id="chap-1",
        title="One",
        order=0,
        chunks=chunks,
        blocks=(
            TextBlock(segments=(Segment("x" * 40, "c0"), Segment("x" * 40, "c1"))),
            HeadingBlock(text="Later", level=2, chunk_ids=()),
            TextBlock(segments=(Segment("x" * 40, "c2"), Segment("x" * 40, "c3"))),
        ),
    )
    ingest = IngestBook(parsers=[], session_store=None, max_characters=60)  # type: ignore[arg-type]

    truncated = ingest._truncate_to_budget(Book(id="book-1", title="B", chapters=(chapter,)))

    kept = truncated.chapters[0]
    assert [c.id for c in kept.chunks] == ["c0", "c1"]
    # Every chunk ID a block still points at resolves to a kept chunk...
    referenced = {cid for b in kept.blocks for cid in chunk_ids_of(b)}
    assert referenced == {c.id for c in kept.chunks}
    # ...but all four paragraphs' worth of text is still displayed.
    shown = [s for b in kept.blocks if isinstance(b, TextBlock) for s in b.segments]
    assert len(shown) == 4
    assert [s.chunk_id for s in shown] == ["c0", "c1", None, None]
