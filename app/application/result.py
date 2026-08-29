"""Minimal Result type. Expected failures are values; exceptions are for bugs.

Chosen over a dependency (e.g. `returns`) because the vocabulary needed
here is tiny: callers match on `Err` and `unwrap` at the API boundary.
There were `map` and `is_ok` too -- nothing ever called them, and a
combinator API in a codebase that doesn't otherwise chain is just surface.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def unwrap(self) -> T:
        return self.value


@dataclass(frozen=True, slots=True)
class Err[E: Exception]:
    error: E

    def unwrap(self) -> object:
        raise self.error


type Result[T, E: Exception] = Ok[T] | Err[E]
