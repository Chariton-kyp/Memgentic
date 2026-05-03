"""Question-aware feature extraction for retrieval-time boosting.

Memory-recall queries carry implicit signals that a generic dense
embedder smooths away. Three signals consistently move the recall
needle when extracted upfront and used to bias scoring:

1. **Temporal references** ("two months ago", "πριν δύο μήνες"). The
   user is asking about a specific time window; candidates whose
   ``created_at`` lands inside that window deserve a boost regardless
   of cosine similarity.
2. **Quoted phrases** (`'foo bar'`, `"foo bar"`, `«foo bar»`). The
   user is asking for an EXACT match; substring-containing candidates
   deserve a boost.
3. **Proper nouns** (``Maria``, ``Cursor``, ``Memgentic``). Names
   carry strong identity signal that gets diluted in a 600M-parameter
   sentence embedding; boost candidates that mention any extracted
   name.

This module is **pure**: no I/O, no model calls. It returns a small
dataclass of extracted features. Callers (retrieval / bench runner)
combine those features with each candidate's payload to compute a
multiplicative boost.

Bilingual: every regex covers Greek and English forms. Memgentic's
target user works in both languages, so a boost system that only
triggers on English queries undercuts the cross-tool memory promise.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Temporal references — relative ("two months ago") + absolute ("in 2024")
# ---------------------------------------------------------------------------

# Token → days mapping. Conservative set; aliases collapse to canonical.
_TIME_UNIT_DAYS: dict[str, float] = {
    # English
    "second": 1 / 86400,
    "seconds": 1 / 86400,
    "minute": 1 / 1440,
    "minutes": 1 / 1440,
    "hour": 1 / 24,
    "hours": 1 / 24,
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
    "year": 365.0,
    "years": 365.0,
    # Greek (singular + plural genitive used in "πριν δύο μηνών" forms)
    "δευτερόλεπτο": 1 / 86400,
    "δευτερόλεπτα": 1 / 86400,
    "λεπτό": 1 / 1440,
    "λεπτά": 1 / 1440,
    "ώρα": 1 / 24,
    "ώρες": 1 / 24,
    "μέρα": 1.0,
    "μέρες": 1.0,
    "ημέρα": 1.0,
    "ημέρες": 1.0,
    "εβδομάδα": 7.0,
    "εβδομάδες": 7.0,
    "μήνα": 30.0,
    "μήνας": 30.0,
    "μήνες": 30.0,
    "μηνών": 30.0,
    "χρόνο": 365.0,
    "χρόνος": 365.0,
    "χρόνια": 365.0,
    "έτος": 365.0,
    "έτη": 365.0,
    "ετών": 365.0,
}

# Number words to integer. Used so "two months ago" matches "2 months ago".
_NUMBER_WORDS: dict[str, int] = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    # Greek
    "ένα": 1, "ένας": 1, "μία": 1, "μια": 1, "δύο": 2, "δυο": 2,
    "τρία": 3, "τρεις": 3, "τέσσερα": 4, "τέσσερις": 4,
    "πέντε": 5, "έξι": 6, "επτά": 7, "εφτά": 7, "οκτώ": 8, "οχτώ": 8,
    "εννέα": 9, "εννιά": 9, "δέκα": 10,
}

# Pattern: (number-word OR digits) followed by a unit then optional "ago"/"πριν".
# We accept either ordering ("two months ago" / "πριν δύο μήνες").
_RELATIVE_TIME_RE = re.compile(
    r"\b(?:"
    r"(?P<en_amount>\d+|" + "|".join(re.escape(w) for w in _NUMBER_WORDS) + r")"
    r"\s+(?P<en_unit>" + "|".join(re.escape(u) for u in _TIME_UNIT_DAYS) + r")"
    r"\s+ago"
    r"|"
    r"πριν\s+(?P<el_amount>\d+|" + "|".join(re.escape(w) for w in _NUMBER_WORDS) + r")"
    r"\s+(?P<el_unit>" + "|".join(re.escape(u) for u in _TIME_UNIT_DAYS) + r")"
    r")\b",
    flags=re.IGNORECASE,
)

# Common implicit anchors → days back from now.
_IMPLICIT_ANCHORS: dict[str, float] = {
    "today": 0.0, "yesterday": 1.0, "this week": 3.5, "last week": 7.0,
    "last month": 30.0, "this month": 15.0, "last year": 365.0,
    "σήμερα": 0.0, "χθες": 1.0, "εχθές": 1.0,
    "αυτή την εβδομάδα": 3.5, "την περασμένη εβδομάδα": 7.0,
    "τον προηγούμενο μήνα": 30.0, "τον περασμένο μήνα": 30.0,
    "πέρυσι": 365.0, "πέρσι": 365.0,
}

# Absolute year — "in 2024", "το 2024", "2024".
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d{2}|21\d{2})\b")


# ---------------------------------------------------------------------------
# Quoted phrases — single, double, guillemets (Greek typography uses « »)
# ---------------------------------------------------------------------------
#
# The regex deliberately requires at least 2 characters inside the quotes so
# stray apostrophes ("don't") don't fire. Curly quotes are normalised to
# straight before matching.
_QUOTE_NORMALISATIONS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'",
    "“": '"', "”": '"', "„": '"',
    "«": '"', "»": '"',  # Greek/French guillemets → "
})
_QUOTED_RE = re.compile(r"""(?P<q>['"])(?P<inner>.{2,80}?)(?P=q)""")


# ---------------------------------------------------------------------------
# Proper nouns — capitalised tokens >= 3 chars
# ---------------------------------------------------------------------------
#
# Allows Greek capitals via a dedicated character class. Skips a small list of
# sentence-initial words (What/Who/Where/Πώς/Τι etc.) so "What did Maria say"
# extracts only "Maria".
_PROPER_NOUN_RE = re.compile(
    r"\b[A-ZΑ-ΩΆΈΉΊΌΎΏΪΫ][A-Za-zΑ-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰ]{2,30}\b"
)
_QUERY_INITIAL_STOPWORDS: frozenset[str] = frozenset(
    {
        # English question/imperative starts
        "What", "Who", "Where", "When", "Why", "How", "Which", "Whose",
        "Does", "Did", "Do", "Can", "Could", "Would", "Should", "Find",
        "Get", "Tell", "Show", "List", "Search", "Recall",
        # Greek
        "Τι", "Ποιος", "Ποια", "Ποιο", "Πού", "Πότε", "Γιατί", "Πώς",
        "Δείξε", "Βρες", "Πες", "Δες", "Θυμήσου",
        # Other commons
        "The", "An", "A",
    }
)


@dataclass(frozen=True)
class QueryFeatures:
    """Extracted features from a user query, ready for retrieval boosting.

    Each field is independently usable; callers can ignore signals they
    don't have payload data for (e.g. ``temporal_reference_days`` is
    only useful when candidates carry a ``created_at`` field).
    """

    # Temporal: how many days back the query likely refers to. ``None``
    # when no temporal reference was detected; multiple references take
    # the SHORTEST distance (most specific anchor).
    temporal_reference_days: float | None = None

    # Quoted exact phrases the user wants to match verbatim.
    quoted_phrases: tuple[str, ...] = ()

    # Capitalised proper nouns (people, projects, products).
    proper_nouns: tuple[str, ...] = ()

    # Detected absolute year (2024, 2026, ...). ``None`` when absent.
    absolute_year: int | None = None


def _word_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


def extract_features(query: str, *, now: _dt.datetime | None = None) -> QueryFeatures:
    """Run all extractors over the query and return a populated dataclass.

    Args:
        query: Raw user query text.
        now: Override "now" for deterministic tests. Defaults to current
            UTC time. Only used when the query carries a relative
            temporal reference like "two months ago".
    """
    if not query:
        return QueryFeatures()

    normalised = query.translate(_QUOTE_NORMALISATIONS)

    # --- Temporal -------------------------------------------------------
    temporal_days: float | None = None
    relative_match = _RELATIVE_TIME_RE.search(query)
    if relative_match:
        amount_token = relative_match.group("en_amount") or relative_match.group("el_amount")
        unit_token = (
            relative_match.group("en_unit") or relative_match.group("el_unit") or ""
        ).lower()
        amount = _word_to_int(amount_token or "")
        if amount is not None and unit_token in _TIME_UNIT_DAYS:
            temporal_days = amount * _TIME_UNIT_DAYS[unit_token]

    if temporal_days is None:
        lower_q = query.lower()
        for phrase, days in _IMPLICIT_ANCHORS.items():
            if phrase in lower_q and (temporal_days is None or days < temporal_days):
                temporal_days = days

    year_match = _YEAR_RE.search(query)
    absolute_year = int(year_match.group(1)) if year_match else None
    if temporal_days is None and absolute_year is not None:
        ref_now = now or _dt.datetime.now(tz=_dt.UTC)
        temporal_days = max((ref_now.year - absolute_year) * 365.0, 0.0)

    # --- Quoted phrases -------------------------------------------------
    quoted = tuple(
        m.group("inner").strip()
        for m in _QUOTED_RE.finditer(normalised)
        if m.group("inner").strip()
    )

    # --- Proper nouns ---------------------------------------------------
    nouns: list[str] = []
    for m in _PROPER_NOUN_RE.finditer(query):
        token = m.group(0)
        # Skip if it's a sentence-initial question word.
        if m.start() == 0 and token in _QUERY_INITIAL_STOPWORDS:
            continue
        # Skip when it's part of a quoted span (quoted handles it).
        if any(token in q for q in quoted):
            continue
        nouns.append(token)

    return QueryFeatures(
        temporal_reference_days=temporal_days,
        quoted_phrases=quoted,
        proper_nouns=tuple(dict.fromkeys(nouns)),  # dedupe, preserve order
        absolute_year=absolute_year,
    )
