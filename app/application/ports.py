"""Ports: abstract interfaces implemented by infrastructure/, depended on by
use cases. See CLAUDE.md SOLID section -- ISP keeps TTSProvider narrow;
optional abilities are separate opt-in protocols, not stubbed fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.domain.entities import Book, TTSSettings, Voice


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    audio_bytes: bytes
    mime_type: str = "audio/wav"


@dataclass(frozen=True, slots=True)
class TimingSpan:
    start_ms: int
    end_ms: int
    text: str


class TTSProvider(ABC):
    """Narrow port: audio is mandatory, nothing else is. Per ADR-2."""

    name: str

    @abstractmethod
    async def synthesize(self, text: str, settings: TTSSettings) -> SynthesisResult: ...

    @abstractmethod
    async def list_voices(self) -> list[Voice]: ...


@runtime_checkable
class SupportsTimings(Protocol):
    """Opt-in capability -- only providers that can actually report timings
    implement this. Per ADR-2, most won't; callers must check with
    isinstance() rather than assume every provider has it."""

    async def synthesize_with_timings(
        self, text: str, settings: TTSSettings
    ) -> tuple[SynthesisResult, list[TimingSpan]]: ...


class BookParser(ABC):
    @abstractmethod
    def can_parse(self, filename: str, content: bytes) -> bool: ...

    @abstractmethod
    def parse(self, book_id: str, content: bytes) -> Book: ...


class AudioCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    async def put(self, key: str, audio_bytes: bytes) -> None: ...


class SessionStore(ABC):
    """In-memory-only in v1 (see plan.md Milestone 1.1) -- kept as a port
    only because Redis is a named future path, not by reflex."""

    @abstractmethod
    async def save_book(self, book: Book) -> None: ...

    @abstractmethod
    async def get_book(self, book_id: str) -> Book | None: ...

    @abstractmethod
    async def get_chunk_text(self, chunk_id: str) -> str | None: ...
