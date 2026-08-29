"""Domain errors -- expected failure cases, not bugs.

Used with Result (see application/result.py): a use case returns
Err(SomeDomainError(...)) for anything the caller should handle, and only
raises for genuine bugs.
"""

from dataclasses import dataclass


class DomainError(Exception):
    """Base for all expected-failure errors returned via Result."""


@dataclass(frozen=True, slots=True)
class InvalidUploadError(DomainError):
    reason: str


@dataclass(frozen=True, slots=True)
class UnsupportedFormatError(DomainError):
    format: str


@dataclass(frozen=True, slots=True)
class EmptyBookError(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ChunkNotFoundError(DomainError):
    chunk_id: str


@dataclass(frozen=True, slots=True)
class ProviderError(DomainError):
    provider: str
    reason: str
