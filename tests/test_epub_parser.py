import pytest
from bs4 import BeautifulSoup

from app.domain.entities import HeadingBlock, ImageBlock
from app.domain.errors import InvalidUploadError
from app.infrastructure.parsers.epub_parser import EbooklibParser
from tests.conftest import build_epub_bytes


def test_can_parse_epub_by_extension() -> None:
    parser = EbooklibParser()
    assert parser.can_parse("book.epub", b"anything")
    assert not parser.can_parse("book.pdf", b"anything")


def test_parses_title_and_chapter() -> None:
    parser = EbooklibParser()
    content = build_epub_bytes(title="My Book")
    book = parser.parse("book-1", content)

    assert book.title == "My Book"
    assert len(book.chapters) == 1
    assert book.chapters[0].title == "Chapter One"


def test_heading_is_read_aloud_and_kept_out_of_the_body_chunks() -> None:
    """A listener expects to hear "Chapter One" before the chapter, so the
    heading is its own chunk -- but it must not be glued onto the first
    paragraph, which is what flattening the chapter to text used to do."""
    parser = EbooklibParser()
    content = build_epub_bytes(chapters=[("Chapter One", "This is the real body text sentence one. " * 10)])
    book = parser.parse("book-1", content)

    chapter = book.chapters[0]
    heading = next(b for b in chapter.blocks if isinstance(b, HeadingBlock))
    by_id = {c.id: c for c in chapter.chunks}

    assert [by_id[cid].text for cid in heading.chunk_ids] == ["Chapter One"]
    body_chunks = [c for c in chapter.chunks if c.id not in heading.chunk_ids]
    assert all("Chapter One" not in c.text for c in body_chunks)


def test_first_chapter_is_the_lowest_order() -> None:
    parser = EbooklibParser()
    content = build_epub_bytes(
        chapters=[
            ("Chapter One", "This is the real body text sentence one. " * 10),
            ("Chapter Two", "This is the real body text sentence two. " * 10),
        ]
    )
    book = parser.parse("book-1", content)

    first = book.first_chapter()
    assert first is not None
    assert first.title == "Chapter One"


def test_short_fragment_is_treated_as_front_matter_not_a_chapter() -> None:
    parser = EbooklibParser()
    content = build_epub_bytes(
        chapters=[
            ("Half Title", "Just a few words here."),  # below _MIN_CHAPTER_WORDS
            ("Chapter One", "This is the real body text sentence one. " * 10),
        ]
    )
    book = parser.parse("book-1", content)

    assert len(book.chapters) == 1
    assert book.chapters[0].title == "Chapter One"


def test_rejects_non_zip_content() -> None:
    parser = EbooklibParser()
    with pytest.raises(InvalidUploadError):
        parser.parse("book-1", b"this is not a zip file at all")


def test_rejects_empty_content() -> None:
    parser = EbooklibParser()
    with pytest.raises(InvalidUploadError):
        parser.parse("book-1", b"")


def test_images_survive_parsing_with_archive_relative_paths() -> None:
    """Images used to be decomposed outright. They now come through as
    ImageBlocks whose src the client can look up in the EPUB it holds --
    resolved against the chapter document, not the archive root."""
    book = EbooklibParser().parse("book-1", build_epub_bytes(with_image=True))

    blocks = book.chapters[0].blocks
    image = next(b for b in blocks if isinstance(b, ImageBlock))
    assert image.src == "images/plate.png"
    assert image.alt == "A plate"
    # Headings survive too, and neither is readable.
    assert any(isinstance(b, HeadingBlock) for b in blocks)


def test_chapters_follow_spine_order_not_manifest_order() -> None:
    """`get_items_of_type` yields manifest order, which routinely differs
    from reading order -- chapters came out shuffled in the contents list.
    The spine is what declares reading order."""
    import io

    import ebooklib
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("x")
    book.set_title("T")
    book.set_language("en")
    body = " ".join(f"Sentence number {i} of ordinary body text." for i in range(30))

    items = {}
    # Added to the manifest back-to-front, as real books often are.
    for name in ["Chapter Three", "Chapter One", "Chapter Two"]:
        item = epub.EpubHtml(title=name, file_name=f"{name.replace(' ', '_')}.xhtml", lang="en")
        item.content = f"<h1>{name}</h1><p>{body}</p>"
        book.add_item(item)
        items[name] = item

    reading_order = ["Chapter One", "Chapter Two", "Chapter Three"]
    book.spine = [items[n] for n in reading_order]
    book.toc = tuple(epub.Link(items[n].file_name, n, items[n].file_name) for n in reading_order)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    buf = io.BytesIO()
    epub.write_epub(buf, book)

    parsed = EbooklibParser().parse("book-1", buf.getvalue())

    assert [c.title for c in sorted(parsed.chapters, key=lambda c: c.order)] == reading_order
    first = parsed.first_chapter()
    assert first is not None and first.title == "Chapter One"

    manifest_order = [i.get_id() for i in ebooklib.epub.read_epub(io.BytesIO(buf.getvalue())).get_items_of_type(ebooklib.ITEM_DOCUMENT)]
    assert manifest_order[0] != parsed.chapters[0].id, "test is vacuous if the two orders agree"


def test_zip_bomb_cap_is_configurable() -> None:
    """The cap is injected by the composition root rather than read from
    config in the parser -- infrastructure may not import `api.config`."""
    content = build_epub_bytes()

    assert EbooklibParser(max_uncompressed_bytes=200 * 1024 * 1024).parse("book-1", content).chapters

    with pytest.raises(InvalidUploadError):
        EbooklibParser(max_uncompressed_bytes=10).parse("book-1", content)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        # The common split that left the contents list reading "1", "2", "3".
        ("<h2>1</h2><h3>The Beginning</h3>", "1 The Beginning"),
        ("<h2>IV</h2><h3>Roman</h3>", "IV Roman"),
        ("<h1>42.</h1><h2>Trailing dot</h2>", "42. Trailing dot"),
        # A heading that names something stops on its own.
        ("<h1>Chapter One</h1><h2>A section</h2>", "Chapter One"),
        ("<h1>7</h1>", "7"),
    ],
)
def test_a_numeric_heading_takes_the_next_one_with_it(html: str, expected: str) -> None:
    assert EbooklibParser._chapter_title(BeautifulSoup(html, "html.parser")) == expected


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<span epub:type="pagebreak" title="42"/>', "42"),
        ('<a role="doc-pagebreak" aria-label="88"></a>', "88"),
        ('<span epub:type="pagebreak" id="page_7"/>', "7"),
        ("<p>no markers here</p>", None),
    ],
)
def test_reads_the_printed_page_from_page_markers(html: str, expected: str | None) -> None:
    """The label lives in an attribute, not the text -- the marker renders
    as nothing. Absent entirely in reflowable-only books."""
    assert EbooklibParser._first_page(BeautifulSoup(html, "html.parser")) == expected
