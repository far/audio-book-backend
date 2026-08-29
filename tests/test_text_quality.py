"""The prose test decides what gets voiced, so its bias matters more than
its accuracy: skipping a sentence the listener wanted is worse than
voicing an awkward one. These cases pin that bias down.
"""

from __future__ import annotations

import pytest

from app.infrastructure.parsers.text_quality import is_prose_like


@pytest.mark.parametrize(
    "text",
    [
        "The quick brown fox jumps over the lazy dog.",
        "It was, he said, a rather peculiar business.",
        "Dr. Watson arrived at 221B Baker Street in 1881.",
        # Proper nouns, loan words and archaic spellings would all miss a
        # dictionary lookup; shape-based scoring passes them.
        "Zarathustra spake thus unto Nietzsche's Übermensch.",
        "She earned 15 percent on the second quarter's revenue.",
        "OK.",
    ],
)
def test_ordinary_prose_is_readable(text: str) -> None:
    assert is_prose_like(text)


@pytest.mark.parametrize(
    "text",
    [
        "x = (a + b) / (c - d) * 100;",
        "for (int i = 0; i < n; i++) { sum += arr[i]; }",
        "f(x) = ax^2 + bx + c",
        "SELECT * FROM users WHERE id = 42 AND status <> 'x';",
        "$ git commit -m 'wip' && git push --force",
        "|| ++ >>= <<= ~^ %$#",
    ],
)
def test_expressions_and_snippets_are_skipped(text: str) -> None:
    assert not is_prose_like(text)


def test_empty_text_is_not_readable() -> None:
    assert not is_prose_like("   ")


def test_a_sentence_mentioning_a_symbol_stays_readable() -> None:
    """Borderline by design: prose that happens to name an operator is
    still prose, and voicing it awkwardly beats silently skipping it."""
    assert is_prose_like("The plus sign (+) denotes addition in most notations.")
