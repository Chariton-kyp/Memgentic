"""Greek text normalization helpers for accent-insensitive matching.

Used by hybrid retrieval (FTS5 / trigram paths) so that "Δικηγορικό",
"δικηγορικο", and "ΔΙΚΗΓΟΡΙΚΟ" all match the same stored text. Pure
stdlib (re + unicodedata) — no extra dependency, importable from any
Memgentic module.

Patterns adapted from a sibling project (EllinCRM hybrid_search). The
Greek accent map and stopword list are deliberately conservative: we
strip diacritics and lowercase, but we do NOT stem. Aggressive stemming
loses retrieval signal on agglutinative Greek inflections (e.g.
"τιμολόγιο" vs "τιμολόγια") that FTS5's `unicode61` tokeniser already
handles via prefix matching.

Public API
----------
- :func:`normalize_greek_text` — accent-strip + lowercase
- :func:`tokenize_for_search` — split + filter (optionally drop stopwords)
- :data:`GREEK_STOPWORDS` — exposed for callers that build their own
  query strategies (e.g. tsquery construction in PostgreSQL adapters)
"""

from __future__ import annotations

import re
import unicodedata

# Direct character mapping is faster than NFD+combining-class for the
# common ASCII-Greek mix we see in conversation text. The unicodedata
# pass below catches anything the table missed (non-Greek diacritics,
# uppercase rare characters, etc.).
GREEK_ACCENT_MAP: dict[str, str] = {
    # Lowercase
    "ά": "α",
    "έ": "ε",
    "ή": "η",
    "ί": "ι",
    "ό": "ο",
    "ύ": "υ",
    "ώ": "ω",
    # Uppercase
    "Ά": "α",
    "Έ": "ε",
    "Ή": "η",
    "Ί": "ι",
    "Ό": "ο",
    "Ύ": "υ",
    "Ώ": "ω",
    # Dialytika (dieresis) — single + combined-with-tonos forms
    "ϊ": "ι",
    "ΐ": "ι",
    "ϋ": "υ",
    "ΰ": "υ",
    "Ϊ": "ι",
    "Ϋ": "υ",
}

# Conservative Greek + English stopword set. Used by tokenise_for_search
# only when the caller opts in via ``remove_stopwords=True`` so semantic
# embedders (which still want function words) are unaffected.
GREEK_STOPWORDS: frozenset[str] = frozenset(
    {
        # Articles
        "ο",
        "η",
        "το",
        "οι",
        "τα",
        "των",
        "του",
        "της",
        "τον",
        "την",
        # Prepositions
        "σε",
        "από",
        "για",
        "με",
        "προς",
        "κατά",
        "μετά",
        "χωρίς",
        "στο",
        "στη",
        "στον",
        "στην",
        # Conjunctions
        "και",
        "ή",
        "αλλά",
        "ότι",
        "αν",
        "όταν",
        "ενώ",
        "επειδή",
        # Pronouns
        "αυτό",
        "αυτός",
        "αυτή",
        "εγώ",
        "εσύ",
        "εμείς",
        "εσείς",
        # Common verbs / particles
        "είναι",
        "ήταν",
        "έχω",
        "έχει",
        "πρέπει",
        "μπορώ",
        "μπορεί",
        "πως",
        "πώς",
        "πού",
        "που",
        "να",
        "θα",
        "δε",
        "δεν",
        "μη",
        "μην",
        # English (mixed-language conversation text is the norm here)
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "and",
        "or",
        "but",
        "if",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
    }
)

_NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def normalize_greek_text(text: str) -> str:
    """Lower-case and strip Greek/Latin diacritics for fuzzy matching.

    Two passes:

    1. Direct table lookup for the common Greek tonos / dialytika set
       — fast and predictable.
    2. NFD decomposition + combining-class filter to catch anything the
       table missed (non-Greek diacritics, archaic accents, etc.).

    Returns an empty string on falsy input. The result is suitable for
    SQLite ``LIKE``, ``glob``, and FTS5 ``MATCH 'query*'`` queries.
    """
    if not text:
        return ""

    text = text.lower()
    for accented, plain in GREEK_ACCENT_MAP.items():
        text = text.replace(accented, plain)

    # NFD decomposition + drop combining marks. unicodedata.category(c)
    # returning "Mn" identifies a non-spacing mark.
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text


def tokenize_for_search(
    text: str,
    *,
    remove_stopwords: bool = False,
    min_token_length: int = 2,
) -> list[str]:
    """Tokenise text for keyword search.

    Splits on non-word characters (Unicode-aware), filters short tokens
    and optionally drops stopwords. Used by callers that build manual
    BM25 / FTS5 / trigram queries; semantic-only callers should NOT use
    this — embedders work better on raw text.

    Args:
        text: Input text.
        remove_stopwords: When True, drop tokens in :data:`GREEK_STOPWORDS`.
            Default False to stay neutral for embedder pipelines.
        min_token_length: Minimum token length to keep (default 2 chars).

    Returns:
        List of normalised tokens, lower-cased and accent-stripped.
    """
    if not text:
        return []

    normalized = normalize_greek_text(text)
    tokens = _NON_WORD_RE.split(normalized)

    out: list[str] = []
    for token in tokens:
        if len(token) < min_token_length:
            continue
        if remove_stopwords and token in GREEK_STOPWORDS:
            continue
        out.append(token)
    return out
