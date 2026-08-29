"""Decides whether a sentence is prose worth voicing.

Formulas, inline code, identifier soup and tables of symbols all read
terribly aloud -- a TTS voice spells out punctuation and mangles
identifiers, producing a stretch of noise the listener can't follow.
Those runs are shown on the page and skipped by the voice.

**No dictionary is involved.** A real lexicon would mean shipping and
maintaining per-language word lists, and would misfire on proper nouns,
archaic spellings and loan words -- all of which are perfectly readable.
Instead this measures whether text is *shaped* like prose: mostly
alphabetic tokens, few symbols, vowels where words have vowels. That's
language-agnostic across the Latin-script languages Piper voices and
cheap enough to run per sentence at ingest.

The thresholds are deliberately permissive. Skipping a sentence the
listener wanted is a worse failure than voicing an awkward one, so
anything borderline stays readable.
"""

from __future__ import annotations

import re

# A token that looks like a word: letters, optionally with an internal
# apostrophe or hyphen, and any trailing punctuation.
_WORD = re.compile(r"^[^\W\d_]+(?:['’\-][^\W\d_]+)*[.,;:!?)\"'’\]]*$", re.UNICODE)

_VOWELS = set("aeiouyàáâäãåèéêëìíîïòóôöõùúûüAEIOUY")

# Below this share of word-shaped tokens, the text is something other than
# a sentence -- an expression, a code line, a column of data.
_MIN_WORD_RATIO = 0.6

# Symbols that make a voice stumble: operators, brackets, backslashes.
# Ordinary sentence punctuation is excluded, so prose scores near zero.
_AWKWARD = re.compile(r"[<>{}\[\]\\|/=+*^~_`@$%#&]")
_MAX_AWKWARD_RATIO = 0.05

# A run of letters with no vowel at all is an acronym, a variable, or
# markup -- not a spoken word. Short tokens are exempt ("by", "km").
_MIN_VOWEL_TOKEN_LENGTH = 4


def _is_word_shaped(token: str) -> bool:
    if not _WORD.match(token):
        return False
    letters = [c for c in token if c.isalpha()]
    return len(letters) < _MIN_VOWEL_TOKEN_LENGTH or any(c in _VOWELS for c in letters)


def is_prose_like(text: str) -> bool:
    """True if [text] reads as a sentence rather than as an expression."""
    tokens = text.split()
    if not tokens:
        return False

    word_ratio = sum(1 for t in tokens if _is_word_shaped(t)) / len(tokens)
    if word_ratio < _MIN_WORD_RATIO:
        return False

    stripped = text.replace(" ", "")
    return not stripped or len(_AWKWARD.findall(stripped)) / len(stripped) <= _MAX_AWKWARD_RATIO
