"""Shows what the parser makes of a book, and whether its images resolve.

    uv run python tools/inspect_book.py /path/to/your.epub

Prints, per chapter, the block kinds in document order and every image src,
then checks each src against the archive the way the Flutter client does
(exact match, then unique path-suffix match). Answers, in one run, whether
missing images are a parsing problem or a lookup problem.
"""

from __future__ import annotations

import posixpath
import sys
import zipfile
from collections import Counter

from app.domain.entities import ImageBlock, chunk_ids_of
from app.infrastructure.parsers.epub_parser import EbooklibParser


def _resolve(href: str, entries: list[str]) -> str:
    """Mirrors EpubArchiveAssets.read in lib/data/datasources/."""
    normalised = [e[2:] if e.startswith("./") else e.lstrip("/") for e in entries]
    if href in normalised:
        return "exact match"
    suffixed = [e for e in normalised if e.endswith(f"/{href}")]
    if len(suffixed) == 1:
        return f"suffix match -> {suffixed[0]}"
    if suffixed:
        return f"AMBIGUOUS ({len(suffixed)} candidates) -- renders as alt text"
    return "NOT IN ARCHIVE -- renders as alt text"


def main(path: str) -> None:
    with open(path, "rb") as fh:
        content = fh.read()

    with zipfile.ZipFile(path) as zf:
        entries = [i.filename for i in zf.infolist() if not i.is_dir()]

    images_in_archive = [e for e in entries if posixpath.splitext(e)[1].lower() in {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}]
    print(f"archive: {len(entries)} entries, {len(images_in_archive)} look like images")
    for entry in images_in_archive[:10]:
        print(f"   {entry}")
    print()

    book = EbooklibParser().parse("book-1", content)
    print(f"book: {book.title!r}  chapters: {len(book.chapters)}")

    chapter_ids = [c.id for c in book.chapters]
    duplicates = len(chapter_ids) - len(set(chapter_ids))
    print(f"duplicate chapter IDs: {duplicates}" + ("   <-- breaks the WS chapter lookup" if duplicates else ""))
    print()

    total_images = 0
    for chapter in book.chapters:
        kinds = Counter(type(b).__name__ for b in chapter.blocks)
        readable = sum(len(chunk_ids_of(b)) for b in chapter.blocks)
        print(f"[{chapter.order}] {chapter.id!r} {chapter.title[:40]!r}")
        print(f"    blocks={dict(kinds)}  chunks={len(chapter.chunks)} (referenced {readable})")
        # The first chunks are what playback starts with, so their text is
        # the direct answer to "why is this chapter reading the wrong thing".
        for chunk in chapter.chunks[:3]:
            print(f"    plays[{chunk.index}] {chunk.text[:70]!r}")
        for block in chapter.blocks:
            if isinstance(block, ImageBlock):
                total_images += 1
                print(f"    image src={block.src!r}  {_resolve(block.src, entries)}")

    print()
    print(f"{total_images} ImageBlock(s) across the book.")
    if not total_images and images_in_archive:
        print("The archive HAS images but the parser produced none -- the markup they")
        print("sit in isn't being walked (SVG-wrapped covers, or image-only pages")
        print("dropped by the 50-word chapter filter).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
