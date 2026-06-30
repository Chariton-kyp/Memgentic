"""Cheap, embedding-free grounding check for distilled recall surfaces.

The enriched ingest distills 1-5 self-contained facts per chunk. Before we
promote that distillation to the embedded + displayed recall surface, we verify
it is actually *anchored* in the verbatim source — a guard against the LLM
hallucinating a fact (a wrong identifier, an invented number) that would then
out-rank the real content. This is a lexical token-overlap heuristic: no
embedding, no LLM, runs in microseconds on the hot path.
"""

from __future__ import annotations

import re

# A deliberately tiny stopword set — just the function words that would
# otherwise inflate overlap for free. Not a linguistics-grade list; the goal is
# only to stop "the/and/to" from making a hallucination look grounded.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at",
        "for", "with", "by", "is", "are", "was", "were", "be", "been", "being",
        "it", "its", "this", "that", "these", "those", "as", "from", "we", "i",
        "you", "they", "he", "she", "human", "assistant",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _content_tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens with the tiny stopword set removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def is_grounded(distilled: str, source: str, threshold: float = 0.5) -> bool:
    """True when at least ``threshold`` of distilled content tokens appear in source.

    ``distilled`` and ``source`` are compared on lowercased alphanumeric tokens
    after dropping a small stopword set. An empty/whitespace/stopword-only
    distillation is never grounded (nothing to anchor).
    """
    distilled_tokens = _content_tokens(distilled)
    if not distilled_tokens:
        return False
    source_tokens = set(_TOKEN_RE.findall(source.lower()))
    hits = sum(1 for t in distilled_tokens if t in source_tokens)
    return (hits / len(distilled_tokens)) >= threshold
