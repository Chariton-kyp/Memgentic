"""Query intent detection — extract implicit filters from natural language queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class QueryIntent:
    raw_query: str
    clean_query: str
    implied_content_types: list[str] = field(default_factory=list)
    implied_topics: list[str] = field(default_factory=list)
    time_filter_since: datetime | None = None


_DECISION_PATTERNS = [
    r"\b(?:what did we|did we|have we|when did we)\s+(?:decide|decided|choose|chose|pick|picked)\b",
    r"\b(?:our|the)\s+decision\s+(?:about|on|for)\b",
    r"\bwhy did we (?:go with|choose|pick)\b",
]

_LEARNING_PATTERNS = [
    r"\b(?:what did (?:we|i)|when did (?:we|i))\s+(?:learn|learned|discover|discovered|find out)\b",
    r"\b(?:we|i)\s+(?:learned|discovered|found out)\b",
]

_PREFERENCE_PATTERNS = [
    r"\b(?:user|my|our)\s+(?:preference|convention|style|way)\b",
    r"\bhow do (?:we|i) usually\b",
    r"\bour coding (?:style|convention|standard)\b",
]

_BUGFIX_PATTERNS = [
    r"\b(?:how did we|when did we)\s+fix\b",
    r"\bprevious (?:bug|error|issue)\b",
    r"\bsimilar (?:bug|error|issue)\b",
]

_TIME_PATTERNS: dict[str, timedelta] = {
    r"\btoday\b": timedelta(days=1),
    r"\byesterday\b": timedelta(days=2),
    r"\bthis week\b": timedelta(days=7),
    r"\blast week\b": timedelta(days=14),
    r"\bthis month\b": timedelta(days=30),
    r"\blast month\b": timedelta(days=60),
    r"\brecently\b": timedelta(days=7),
}

# Words/phrases stripped from the clean query (longest first to avoid leftover fragments)
_FILTER_WORDS = sorted(
    [
        "what did we",
        "when did we",
        "have we",
        "did we",
        "decide",
        "decided",
        "decision",
        "choose",
        "chose",
        "learn",
        "learned",
        "discover",
        "discovered",
        "preference",
        "convention",
        "today",
        "yesterday",
        "this week",
        "last week",
        "this month",
        "last month",
        "recently",
        "about",
    ],
    key=len,
    reverse=True,
)


def parse_query_intent(query: str) -> QueryIntent:
    """Extract implicit filters from a natural language query."""
    if not query:
        return QueryIntent(raw_query=query, clean_query=query)

    lower = query.lower()
    content_types: list[str] = []

    if any(re.search(p, lower) for p in _DECISION_PATTERNS):
        content_types.append("decision")
    if any(re.search(p, lower) for p in _LEARNING_PATTERNS):
        content_types.append("learning")
    if any(re.search(p, lower) for p in _PREFERENCE_PATTERNS):
        content_types.append("preference")
    if any(re.search(p, lower) for p in _BUGFIX_PATTERNS):
        content_types.append("bug_fix")

    time_since: datetime | None = None
    for pattern, delta in _TIME_PATTERNS.items():
        if re.search(pattern, lower):
            time_since = datetime.now(UTC) - delta
            break

    clean = lower
    for word in _FILTER_WORDS:
        clean = re.sub(r"\b" + re.escape(word) + r"\b", " ", clean)
    clean = " ".join(clean.split()).strip()
    if not clean:
        clean = query

    return QueryIntent(
        raw_query=query,
        clean_query=clean,
        implied_content_types=content_types,
        implied_topics=[],
        time_filter_since=time_since,
    )
