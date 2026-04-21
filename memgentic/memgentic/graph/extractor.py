"""LLM-backed subject-predicate-object triple extractor.

Called from the ingestion pipeline after enriched/dual memories are
persisted. Proposes triples with ``status="proposed"`` so a human (or a
future auto-confirm heuristic) must validate them before they surface in
query results. Predicates are normalised to snake_case; subjects and
objects are fuzzy-matched against existing entities via rapidfuzz when
available, falling back to :mod:`difflib` when the optional dependency
is missing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field

from memgentic.graph.temporal import Chronograph
from memgentic.models import Memory

logger = structlog.get_logger()

# Confidence assigned to every LLM-proposed triple unless the LLM returns
# a higher value. User-validated triples go to 1.0; hand-added triples
# inherit whatever ``confidence`` the caller specifies.
_DEFAULT_CONFIDENCE = 0.7

# Minimum rapidfuzz / difflib ratio to count as an alias match when
# resolving subjects/objects back to existing entities.
_FUZZY_MATCH_THRESHOLD = 90


class _ExtractedTripleSchema(BaseModel):
    """Per-triple row returned by the LLM."""

    subject: str = Field(description="Entity that is the subject of the fact")
    predicate: str = Field(description="Short verb phrase describing the relationship")
    object: str = Field(description="Entity, concept or value that is the object")
    valid_from: str | None = Field(
        default=None,
        description="Optional ISO 8601 date when the fact became true",
    )
    confidence: float | None = Field(
        default=None,
        description="Extractor confidence in the range 0.0 to 1.0",
    )


class ExtractedTriples(BaseModel):
    """Structured LLM output wrapping a list of triples."""

    triples: list[_ExtractedTripleSchema] = Field(default_factory=list)


@dataclass
class ProposedTriple:
    """Result of extraction before it is persisted."""

    subject: str
    predicate: str
    object: str
    valid_from: date | None
    confidence: float
    source_memory_id: str | None
    proposer: str = "llm"


_PROMPT_TEMPLATE = """\
Extract factual subject-predicate-object triples from the text below.

Guidelines:
- Only include clear factual relationships (people, projects, tools, decisions).
- Use short, verb-based predicates in English (e.g. "works_on", "decided",
  "prefers", "uses", "located_in"). Lowercase, snake_case preferred.
- Keep subjects and objects concise (2-6 words). Prefer the form a human
  would write in a knowledge graph.
- If the text mentions when a fact became true, include ``valid_from`` as
  an ISO 8601 date (YYYY-MM-DD). Otherwise leave it null.
- Confidence should be 0.0-1.0. 0.9+ only for facts stated explicitly.
- Return at most 8 triples. Skip speculation.

Text:
\"\"\"{content}\"\"\"
"""


def _normalize_predicate(raw: str) -> str:
    """Lowercase + snake_case a predicate string."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", raw.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "related_to"


def _fuzzy_ratio(a: str, b: str) -> float:
    """Return a 0-100 similarity score, preferring rapidfuzz when installed."""
    try:
        from rapidfuzz import fuzz

        return float(fuzz.WRatio(a, b))
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100.0


async def _resolve_entity(name: str, chronograph: Chronograph) -> str:
    """Map a free-form name to an existing entity canonical form.

    Returns the closest existing entity name (for ``add_triple`` to reuse
    the same entity row) or the original string when no match is strong
    enough. Canonical lowercasing still happens in ``Chronograph``.
    """
    candidate = name.strip()
    if not candidate:
        return candidate
    try:
        existing = await chronograph.list_entities(limit=500)
    except Exception:  # pragma: no cover — defensive
        return candidate
    if not existing:
        return candidate
    best_name: str | None = None
    best_score = 0.0
    for ent in existing:
        score = _fuzzy_ratio(candidate, ent.name)
        for alias in ent.aliases:
            score = max(score, _fuzzy_ratio(candidate, alias))
        if score > best_score:
            best_score = score
            best_name = ent.name
    if best_name and best_score >= _FUZZY_MATCH_THRESHOLD:
        return best_name
    return candidate


def _parse_valid_from(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


async def _call_llm(memory: Memory, llm: Any) -> ExtractedTriples:
    """Invoke the LLM once and coerce its output to :class:`ExtractedTriples`.

    Uses ``generate_structured`` when available (LangChain tool calling);
    otherwise falls back to a plain prompt + JSON parse so tests that
    stub out the LLM stay simple.
    """
    prompt = _PROMPT_TEMPLATE.format(content=memory.content[:4000])
    result: Any = None
    if hasattr(llm, "generate_structured"):
        try:
            result = await llm.generate_structured(prompt, ExtractedTriples)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("chronograph.extractor.structured_failed", error=str(exc))
            result = None
    if result is None and hasattr(llm, "generate"):
        try:
            text = await llm.generate(prompt)
        except Exception as exc:
            logger.warning("chronograph.extractor.generate_failed", error=str(exc))
            return ExtractedTriples(triples=[])
        if not text:
            return ExtractedTriples(triples=[])
        try:
            stripped = text.strip()
            if stripped.startswith("```"):
                stripped = re.sub(r"^```[a-zA-Z]*", "", stripped).strip()
                if stripped.endswith("```"):
                    stripped = stripped[:-3].strip()
            payload = json.loads(stripped)
            if isinstance(payload, list):
                payload = {"triples": payload}
            result = ExtractedTriples.model_validate(payload)
        except Exception as exc:
            logger.warning("chronograph.extractor.parse_failed", error=str(exc))
            return ExtractedTriples(triples=[])
    if isinstance(result, ExtractedTriples):
        return result
    return ExtractedTriples(triples=[])


async def extract_triples(
    memory: Memory, llm: Any, chronograph: Chronograph
) -> list[ProposedTriple]:
    """Extract proposed triples for ``memory`` and return the normalised list.

    The extractor does not persist anything; callers should iterate the
    returned list and invoke :meth:`Chronograph.add_triple` so the
    transaction boundary stays under their control (pipeline + CLI
    backfill + REST extract share the same code path).
    """
    if not getattr(llm, "available", False):
        return []
    response = await _call_llm(memory, llm)
    proposed: list[ProposedTriple] = []
    for row in response.triples:
        subject = (row.subject or "").strip()
        raw_predicate = (row.predicate or "").strip()
        obj = (row.object or "").strip()
        if not subject or not raw_predicate or not obj:
            continue
        predicate = _normalize_predicate(raw_predicate)
        resolved_subject = await _resolve_entity(subject, chronograph)
        resolved_object = await _resolve_entity(obj, chronograph)
        raw_confidence = row.confidence if row.confidence is not None else _DEFAULT_CONFIDENCE
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = _DEFAULT_CONFIDENCE
        confidence = max(0.0, min(1.0, confidence))
        proposed.append(
            ProposedTriple(
                subject=resolved_subject,
                predicate=predicate,
                object=resolved_object,
                valid_from=_parse_valid_from(row.valid_from),
                confidence=confidence,
                source_memory_id=memory.id,
            )
        )
    return proposed


async def store_proposed(
    proposed: list[ProposedTriple],
    chronograph: Chronograph,
    workspace_id: str | None = None,
) -> list[str]:
    """Persist a batch of proposed triples — returns the stored ids."""
    ids: list[str] = []
    for p in proposed:
        triple = await chronograph.add_triple(
            subject=p.subject,
            predicate=p.predicate,
            object=p.object,
            valid_from=p.valid_from,
            confidence=p.confidence,
            source_memory_id=p.source_memory_id,
            proposer=p.proposer,
            status="proposed",
            workspace_id=workspace_id,
        )
        ids.append(triple.id)
    return ids
