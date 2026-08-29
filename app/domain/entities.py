"""Domain entities. No imports beyond stdlib -- see CLAUDE.md dependency rule."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Voice:
    """A voice a provider can synthesize with.

    `name` is what a person picks from; `id` is what the provider's API
    takes. For ElevenLabs those differ entirely ("Rachel" vs. a 20-char
    opaque ID), so listing only IDs made the choice unusable.
    """

    id: str
    provider: str
    name: str = ""
    language: str = "en"

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class Chunk:
    """A sentence-sized unit of chapter text with a stable, session-scoped ID.

    Per ADR-4: `id` is not a cache key. The cache key is derived separately
    from (text, provider, voice) -- see application/caching.py.
    """

    id: str
    chapter_id: str
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of a paragraph, and the chunk that voices it -- or None.

    Text is shown whether or not it can be read aloud, so display and
    playback are separate concerns: a formula or an inline code snippet
    mid-paragraph is rendered in place and skipped by the voice, and so is
    anything truncation dropped for budget. Without this split, making
    something unreadable would delete it from the page.
    """

    text: str
    chunk_id: str | None = None


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A paragraph, in reading order. Its voiced segments are its chunks;
    the rest is shown but never spoken."""

    segments: tuple[Segment, ...]


@dataclass(frozen=True, slots=True)
class HeadingBlock:
    """Read aloud like prose, but rendered as a heading.

    A listener expects to hear "Chapter One" before the chapter -- the
    heading being *also* used as the chapter title is a display detail,
    not a reason to skip it.
    """

    text: str
    level: int
    chunk_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CodeBlock:
    """Shown verbatim, never read aloud. Synthesizing a listing produces
    minutes of unintelligible punctuation, so code is displayed and
    skipped rather than voiced."""

    text: str


@dataclass(frozen=True, slots=True)
class ImageBlock:
    """`src` is the image's path *within the EPUB archive*, normalised to
    archive-root relative.

    The client renders images straight out of the uploaded file it still
    holds, so this is a lookup key into that archive, not a URL. Resolving
    it here rather than client-side is what keeps EPUB path semantics
    (srcs are relative to the chapter document, not the archive root) in
    the parser that already understands them.
    """

    src: str
    alt: str = ""


# A chapter is an ordered list of these: the reader shows the document as
# it appears in the book, and only TextBlocks are selectable for synthesis.
# Union rather than one class with optional fields so both sides get
# exhaustive matching (the Dart side mirrors this as a sealed class).
Block = TextBlock | HeadingBlock | ImageBlock | CodeBlock


def chunk_ids_of(block: "Block") -> tuple[str, ...]:
    """Chunks a block is read from, empty for blocks that are shown but
    never voiced. Written once here so callers don't have to know which
    kinds are readable -- that set has already changed once."""
    match block:
        case TextBlock(segments=segments):
            return tuple(s.chunk_id for s in segments if s.chunk_id is not None)
        case HeadingBlock(chunk_ids=chunk_ids):
            return chunk_ids
        case _:
            return ()


@dataclass(frozen=True, slots=True)
class Chapter:
    id: str
    title: str
    order: int
    # Printed page this chapter starts on, when the book carries page
    # markers from a print edition. None for reflowable-only books.
    page: str | None = None
    chunks: tuple[Chunk, ...] = field(default_factory=tuple)
    blocks: tuple[Block, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Book:
    id: str
    title: str
    chapters: tuple[Chapter, ...] = field(default_factory=tuple)

    def first_chapter(self) -> Chapter | None:
        if not self.chapters:
            return None
        return min(self.chapters, key=lambda c: c.order)



@dataclass(frozen=True, slots=True)
class TTSSettings:
    provider: str
    voice_id: str
    language: str = "en"
