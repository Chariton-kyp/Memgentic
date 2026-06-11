"""Auto-dream — LLM-driven memory consolidation pipeline.

This module requires the ``[intelligence]`` extras (langgraph + a langchain
provider). Importing it on a base install fails fast with ``ImportError``;
the CLI and MCP layers gate the import in a try/except so the user gets a
clear "install memgentic[intelligence]" hint instead of a stack trace.

A dream is an asynchronous LLM pass over the live memory store that proposes
patches (merge / supersede / archive_stale / normalize_date / insert_insight /
update_field). The live ``memories`` table is **never** mutated by the pipeline
itself — patches are persisted in their own table with status ``proposed`` and
applied only when the user explicitly calls ``apply_dream``.

This mirrors Anthropic's Managed Agents ``dream`` resource semantics: input is
immutable, output is reviewable, the user always has the final word.

Pipeline (LangGraph):

    orient  -> gather_signal -> consolidate -> index

* orient: deterministic SQL inventory (no LLM)
* gather_signal: LLM scan over recent session bundles for the project;
  surfaces corrections / preferences / patterns / dated decisions
* consolidate: LLM clusters live memories and proposes patches (uses a
  separate stronger LLMClient when ANTHROPIC_API_KEY is configured, falls
  back to the default LLMClient otherwise)
* index: persist DreamRun + DreamPatch rows; never touches memories
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from memgentic.config import MemgenticSettings
from memgentic.models import (
    DESTRUCTIVE_DREAM_ACTIONS,
    CaptureMethod,
    ContentType,
    DreamPatch,
    DreamPatchAction,
    DreamPatchStatus,
    DreamRun,
    DreamStatus,
    Memory,
    MemoryStatus,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.processing.dream_prompts import (
    CONSOLIDATE_SYSTEM,
    CONSOLIDATE_USER_TEMPLATE,
    GATHER_SIGNAL_SYSTEM,
    GATHER_SIGNAL_USER_TEMPLATE,
)
from memgentic.processing.llm import LLMClient

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Structured-output schemas for LLM phases
# ---------------------------------------------------------------------------


class _DatedDecision(BaseModel):
    fact: str
    date: str = Field(description="ISO 8601 date YYYY-MM-DD")


class SignalReport(BaseModel):
    """Output of Phase 2 — Gather Signal."""

    corrections: list[str] = Field(default_factory=list)
    preference_changes: list[str] = Field(default_factory=list)
    recurring_patterns: list[str] = Field(default_factory=list)
    decisions_with_dates: list[_DatedDecision] = Field(default_factory=list)


class ProposedPatch(BaseModel):
    """One proposed patch produced by Phase 3 — Consolidate."""

    action: DreamPatchAction
    target_memory_ids: list[str] = Field(default_factory=list)
    new_content: str | None = None
    new_metadata: dict | None = None
    evidence: str = Field(description="Why this patch is safe.")


class PatchSet(BaseModel):
    """Output of Phase 3 — Consolidate."""

    patches: list[ProposedPatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass
class ApplyReport:
    """Summary of an ``apply_dream`` invocation."""

    dream_id: str
    applied: int = 0
    skipped_destructive: int = 0
    inserted_memories: list[str] = field(default_factory=list)
    superseded_memories: list[str] = field(default_factory=list)
    archived_memories: list[str] = field(default_factory=list)
    chronograph_triples: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class DreamState(TypedDict, total=False):
    """LangGraph state threaded through all dream phases."""

    # Inputs
    project: str
    instructions: str
    limit_sessions: int
    user_id: str

    # Wired-in resources (non-serializable; treated as Any)
    metadata_store: Any
    embedder: Any
    settings: Any
    signal_llm: Any  # default LLMClient
    consolidate_llm: Any  # Anthropic-routed LLMClient or fallback to default

    # Outputs filled by nodes
    dream_run: Any  # DreamRun in flight
    inventory: dict
    handoffs: list[dict]
    signal_report: dict
    patches: list[dict]
    errors: list[str]
    usage_input_tokens: int
    usage_output_tokens: int


# ---------------------------------------------------------------------------
# LLM clients per phase — model-name based routing
# ---------------------------------------------------------------------------
#
# Phase 2 (Gather Signal) and Phase 3 (Consolidate) each have their own
# configurable model. Routing is driven entirely by the model NAME so a user
# can mix providers freely — e.g. cheap Haiku for Phase 2, local Qwen for
# Phase 3, or vice-versa.
#
# Routing rules (case-insensitive prefix match on the model name):
#   - ``claude-*`` / ``anthropic/...``  → Anthropic API (langchain-anthropic)
#   - ``gemini-*`` / ``models/gemini-*`` → Google API (langchain-google-genai)
#   - ``gpt-*`` / ``openai/...``         → OpenAI-compatible endpoint
#                                          (langchain-openai, requires
#                                          ``openai_compat_base_url``)
#   - empty string                       → default LLMClient chain
#                                          (Gemini → OpenAI-compat → Ollama)
#   - anything else                      → treated as an Ollama tag
#                                          (e.g. ``qwen3.6:35b-a3b``,
#                                          ``gemma4:e4b``, ``llama3.1:8b``)
#
# Each builder returns an LLMClient on success or None on failure. The
# top-level ``_build_phase_llm`` dispatches by name and gracefully falls back
# to the default LLMClient on any builder failure — so a misconfigured
# provider never crashes the pipeline, it just degrades to heuristics.


def _build_anthropic_client(
    settings: MemgenticSettings,
    model: str,
    *,
    phase_label: str,
) -> LLMClient | None:
    """Try to build an Anthropic-routed LLMClient. Returns None on any failure
    so the caller can fall back to the default tier."""
    if not settings.anthropic_api_key:
        logger.info(
            f"dream.{phase_label}_llm.anthropic_skipped",
            reason="no ANTHROPIC_API_KEY",
            model=model,
        )
        return None
    try:
        from langchain_anthropic import ChatAnthropic

        client = LLMClient(settings)
        # ``model_name`` is the constructor alias of the ``model`` field —
        # pyright only sees the alias in the synthesized signature.
        client._model = ChatAnthropic(  # type: ignore[attr-defined]
            model_name=model,
            api_key=settings.anthropic_api_key,
            temperature=0,
        )
        client._provider_kind = "anthropic"  # type: ignore[attr-defined]
        logger.info(f"dream.{phase_label}_llm.anthropic", model=model)
        return client
    except ImportError:
        logger.warning(
            f"dream.{phase_label}.fallback",
            reason="langchain_anthropic not installed",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dream.{phase_label}.fallback", reason=str(exc))
    return None


def _build_gemini_client(
    settings: MemgenticSettings,
    model: str,
    *,
    phase_label: str,
) -> LLMClient | None:
    """Build a Gemini-routed LLMClient via langchain-google-genai."""
    if not settings.google_api_key:
        logger.info(
            f"dream.{phase_label}_llm.gemini_skipped",
            reason="no GOOGLE_API_KEY",
            model=model,
        )
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        client = LLMClient(settings)
        # Strip the ``models/`` prefix langchain doesn't always like.
        clean_model = model.removeprefix("models/")
        client._model = ChatGoogleGenerativeAI(  # type: ignore[attr-defined]
            model=clean_model,
            google_api_key=settings.google_api_key,
        )
        client._provider_kind = "google"  # type: ignore[attr-defined]
        logger.info(f"dream.{phase_label}_llm.gemini", model=clean_model)
        return client
    except ImportError:
        logger.warning(
            f"dream.{phase_label}.fallback",
            reason="langchain_google_genai not installed",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dream.{phase_label}.fallback", reason=str(exc))
    return None


def _build_openai_compat_client(
    settings: MemgenticSettings,
    model: str,
    *,
    phase_label: str,
) -> LLMClient | None:
    """Build an OpenAI-compatible LLMClient (LM Studio / vLLM / llama.cpp)."""
    if not settings.openai_compat_base_url:
        logger.info(
            f"dream.{phase_label}_llm.openai_compat_skipped",
            reason="no MEMGENTIC_OPENAI_COMPAT_BASE_URL",
            model=model,
        )
        return None
    try:
        from langchain_openai import ChatOpenAI

        client = LLMClient(settings)
        # Build kwargs as a plain dict (mirrors ``LLMClient`` in ``llm.py``):
        # langchain-openai is an optional extra whose constructor signature
        # drifts across versions (``max_tokens`` vs the newer
        # ``max_completion_tokens`` alias), so bypass static signature checks
        # the same way the default client does.
        kwargs: dict[str, Any] = {
            "model": model,
            "base_url": settings.openai_compat_base_url,
            "api_key": settings.openai_compat_api_key,
            "temperature": 0,
            # OpenAI-style cap on completion length — reuse Ollama's budget.
            "max_tokens": settings.ollama_num_predict,
        }
        client._model = ChatOpenAI(**kwargs)  # type: ignore[attr-defined]
        client._provider_kind = "openai_compat"  # type: ignore[attr-defined]
        logger.info(
            f"dream.{phase_label}_llm.openai_compat",
            model=model,
            base_url=settings.openai_compat_base_url,
        )
        return client
    except ImportError:
        logger.warning(
            f"dream.{phase_label}.fallback",
            reason="langchain_openai not installed",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dream.{phase_label}.fallback", reason=str(exc))
    return None


def _build_ollama_client(
    settings: MemgenticSettings,
    model: str,
    *,
    phase_label: str,
) -> LLMClient | None:
    """Build an Ollama-routed LLMClient with the explicit model tag.

    Note: this differs from ``LLMClient._try_ollama_llm`` which uses the
    project-wide ``settings.local_llm_model``. Here we override the tag so
    Phase 2 and Phase 3 can use distinct local models (e.g. tiny gemma4:e2b
    for Phase 2, MoE qwen3.6:35b-a3b for Phase 3).
    """
    if not settings.enable_local_llm:
        logger.info(
            f"dream.{phase_label}_llm.ollama_skipped",
            reason="MEMGENTIC_ENABLE_LOCAL_LLM=false",
            model=model,
        )
        return None
    try:
        from langchain_ollama import ChatOllama

        kwargs: dict = {
            "model": model,
            "base_url": settings.ollama_url,
            "temperature": 0,
            "num_ctx": settings.ollama_num_ctx,
            "num_predict": settings.ollama_num_predict,
        }
        if settings.ollama_num_threads > 0:
            kwargs["num_thread"] = settings.ollama_num_threads

        client = LLMClient(settings)
        client._model = ChatOllama(**kwargs)  # type: ignore[attr-defined]
        client._provider_kind = "ollama"  # type: ignore[attr-defined]
        logger.info(f"dream.{phase_label}_llm.ollama", model=model)
        return client
    except ImportError:
        logger.warning(
            f"dream.{phase_label}.fallback",
            reason="langchain_ollama not installed",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"dream.{phase_label}.fallback", reason=str(exc))
    return None


def _detect_provider(model: str) -> str:
    """Classify a model name into a provider key used by the dispatcher.

    Returns one of: ``anthropic``, ``gemini``, ``openai_compat``, ``ollama``.
    Empty strings return ``""`` so the caller can fall back to the default
    LLMClient chain.
    """
    if not model:
        return ""
    lower = model.lower()
    if lower.startswith("claude-") or lower.startswith("anthropic/"):
        return "anthropic"
    if lower.startswith("gemini-") or lower.startswith("models/gemini-"):
        return "gemini"
    if lower.startswith("gpt-") or lower.startswith("openai/") or lower.startswith("o1-"):
        return "openai_compat"
    # Anything else — treat as an Ollama tag. Ollama tags conventionally
    # contain a colon (``family:size``) but bare names like ``llama3`` are
    # also valid Ollama identifiers, so we don't filter on that.
    return "ollama"


def _build_phase_llm(
    settings: MemgenticSettings,
    raw_model: str,
    phase_label: str,
) -> LLMClient | None:
    """Dispatch a phase model name to the right provider builder.

    Returns the built LLMClient or None when the dispatch yields nothing
    (empty model name, or all matching builders failed). The caller is
    expected to fall back to the default ``LLMClient(settings)`` chain in
    that case.
    """
    provider = _detect_provider(raw_model)
    if provider == "anthropic":
        return _build_anthropic_client(settings, raw_model, phase_label=phase_label)
    if provider == "gemini":
        return _build_gemini_client(settings, raw_model, phase_label=phase_label)
    if provider == "openai_compat":
        return _build_openai_compat_client(settings, raw_model, phase_label=phase_label)
    if provider == "ollama":
        return _build_ollama_client(settings, raw_model, phase_label=phase_label)
    return None  # empty model name → caller uses default LLMClient


def create_consolidate_llm(settings: MemgenticSettings) -> LLMClient:
    """Build the LLMClient for Phase 3 (Consolidate).

    Routing follows ``_build_phase_llm`` rules — see the module docstring at
    the top of the LLM section for the prefix → provider table. Falls back
    to the default LLMClient (Gemini → OpenAI-compat → Ollama → heuristics)
    when the configured model is empty or its provider builder fails. The
    heuristic fallback is always available so this function never raises.
    """
    raw = settings.dream_consolidate_model or ""
    client = _build_phase_llm(settings, raw, "consolidate")
    if client is not None:
        return client
    logger.info("dream.consolidate_llm.default", configured=raw)
    return LLMClient(settings)


def create_signal_llm(settings: MemgenticSettings) -> LLMClient:
    """Build the LLMClient for Phase 2 (Gather Signal).

    Same routing rules as ``create_consolidate_llm`` but reads
    ``dream_signal_model``. Phase 2 is a single bulk-scan call per dream so
    cheap-and-fast is the right default (Haiku, Gemini Flash-Lite, or a tiny
    local model like ``gemma4:e2b``).
    """
    raw = settings.dream_signal_model or ""
    client = _build_phase_llm(settings, raw, "signal")
    if client is not None:
        return client
    logger.info("dream.signal_llm.default", configured=raw)
    return LLMClient(settings)


# ---------------------------------------------------------------------------
# Phase 1 — Orient
# ---------------------------------------------------------------------------


async def orient_node(state: DreamState) -> dict:
    """Build a deterministic inventory + recent-session bundle for the project."""
    metadata_store = state["metadata_store"]
    project = state.get("project", "")
    user_id = state.get("user_id", "")
    limit_sessions = int(state.get("limit_sessions", 10))

    config = SessionConfig(include_projects=[project] if project else [])
    memories = await metadata_store.get_memories_by_filter(
        session_config=config, limit=10000, user_id=user_id
    )

    sources = Counter(m.source.platform.value for m in memories)
    content_types = Counter(m.content_type.value for m in memories)

    since = datetime.now(UTC) - timedelta(days=14)
    handoffs = await metadata_store.get_recent_session_handoffs(
        since=since,
        session_config=config,
        limit_sessions=limit_sessions,
        memories_per_session=8,
        user_id=user_id,
    )

    inventory = {
        "n_memories": len(memories),
        "source_breakdown": dict(sources),
        "content_type_breakdown": dict(content_types),
        "memory_ids": [m.id for m in memories],
    }
    logger.info(
        "dream.orient",
        project=project or "(all)",
        n_memories=len(memories),
        n_handoffs=len(handoffs),
    )
    return {"inventory": inventory, "handoffs": handoffs}


# ---------------------------------------------------------------------------
# Phase 2 — Gather Signal
# ---------------------------------------------------------------------------


def _format_handoffs(handoffs: list[dict]) -> str:
    if not handoffs:
        return "(no recent sessions)"
    blocks = []
    for h in handoffs:
        head = (
            f"[{h.get('platform', '?')}] {h.get('session_title') or h.get('session_id') or '?'} "
            f"(last_activity={h.get('last_activity')!s})"
        )
        bullets = []
        for m in h.get("memories", [])[:5]:
            content = (m.content if isinstance(m, Memory) else m.get("content", "")) or ""
            bullets.append(f"  - {content[:200]}")
        blocks.append(head + "\n" + "\n".join(bullets))
    return "\n\n".join(blocks)


async def gather_signal_node(state: DreamState) -> dict:
    """LLM pass over the recent session bundles to surface high-signal items."""
    llm: LLMClient = state.get("signal_llm")  # type: ignore[assignment]
    handoffs = state.get("handoffs", [])
    project = state.get("project") or "(all)"
    errors: list[str] = list(state.get("errors", []))
    total_in = int(state.get("usage_input_tokens", 0))
    total_out = int(state.get("usage_output_tokens", 0))

    if not llm or not llm.available:
        logger.info("dream.gather.no_llm", reason="LLM unavailable; empty signal report")
        return {
            "signal_report": SignalReport().model_dump(),
            "errors": errors,
            "usage_input_tokens": total_in,
            "usage_output_tokens": total_out,
        }

    today = datetime.now(UTC).date().isoformat()
    user_prompt = GATHER_SIGNAL_USER_TEMPLATE.format(
        today=today,
        n_sessions=len(handoffs),
        project=project,
        sessions_block=_format_handoffs(handoffs),
    )
    full_prompt = GATHER_SIGNAL_SYSTEM + "\n\n" + user_prompt

    try:
        result, usage = await llm.generate_structured_with_usage(full_prompt, SignalReport)
        total_in += int(usage.get("input_tokens", 0))
        total_out += int(usage.get("output_tokens", 0))
        if isinstance(result, SignalReport):
            logger.info(
                "dream.gather",
                corrections=len(result.corrections),
                preferences=len(result.preference_changes),
                patterns=len(result.recurring_patterns),
                dated=len(result.decisions_with_dates),
                usage_in=int(usage.get("input_tokens", 0)),
                usage_out=int(usage.get("output_tokens", 0)),
            )
            return {
                "signal_report": result.model_dump(),
                "errors": errors,
                "usage_input_tokens": total_in,
                "usage_output_tokens": total_out,
            }
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"gather_signal: {exc}")
        logger.warning("dream.gather.failed", error=str(exc))

    return {
        "signal_report": SignalReport().model_dump(),
        "errors": errors,
        "usage_input_tokens": total_in,
        "usage_output_tokens": total_out,
    }


# ---------------------------------------------------------------------------
# Phase 3 — Consolidate
# ---------------------------------------------------------------------------


def _cluster_memories(memories: list[Memory]) -> list[list[Memory]]:
    """Cheap topic-based clustering — group memories sharing a topic.

    A memory belongs to the first cluster whose topic intersects its own.
    Memories with no topics form their own singleton clusters.
    """
    clusters: list[list[Memory]] = []
    cluster_topics: list[set[str]] = []
    singletons: list[list[Memory]] = []

    for mem in memories:
        topics = {t.lower() for t in mem.topics if t}
        if not topics:
            singletons.append([mem])
            continue

        placed = False
        for idx, ct in enumerate(cluster_topics):
            if topics & ct:
                clusters[idx].append(mem)
                cluster_topics[idx] |= topics
                placed = True
                break
        if not placed:
            clusters.append([mem])
            cluster_topics.append(topics)

    # Cap cluster size — Phase 3 is the expensive call; runaway clusters
    # blow tokens. 25 is a heuristic budget.
    capped: list[list[Memory]] = []
    for cluster in clusters:
        if len(cluster) <= 25:
            capped.append(cluster)
        else:
            for i in range(0, len(cluster), 25):
                capped.append(cluster[i : i + 25])
    capped.extend(singletons)
    return capped


def _format_cluster(cluster: list[Memory]) -> str:
    rows = []
    for mem in cluster:
        rows.append(
            f"  - id={mem.id} src={mem.source.platform.value} "
            f"created={mem.created_at.date().isoformat()} "
            f"content={mem.content[:300]!r}"
        )
    return "\n".join(rows)


def _cosine_hints(cluster: list[Memory]) -> str:
    """Cheap textual similarity hints to feed the LLM (NOT the source of truth)."""
    if len(cluster) < 2:
        return "(no pairs)"
    hints: list[str] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(cluster):
        a_words = set(a.content.lower().split())
        for b in cluster[i + 1 :]:
            key = tuple(sorted([a.id, b.id]))
            if key in seen:
                continue
            seen.add(key)  # type: ignore[arg-type]
            b_words = set(b.content.lower().split())
            if not a_words or not b_words:
                continue
            overlap = len(a_words & b_words) / max(1, math.sqrt(len(a_words) * len(b_words)))
            if overlap >= 0.5:
                hints.append(f"  - {a.id[:8]} vs {b.id[:8]}: jaccard~{overlap:.2f}")
    return "\n".join(hints) if hints else "(no high-similarity pairs)"


async def consolidate_node(state: DreamState) -> dict:
    """LLM proposes patches per topic cluster."""
    metadata_store = state["metadata_store"]
    llm: LLMClient = state.get("consolidate_llm")  # type: ignore[assignment]
    project = state.get("project", "")
    project_label = project or "(all)"
    user_id = state.get("user_id", "")
    inventory = state.get("inventory", {})
    signal_report = state.get("signal_report") or {}
    instructions = state.get("instructions", "")
    errors: list[str] = list(state.get("errors", []))

    config = SessionConfig(include_projects=[project] if project else [])
    memories = await metadata_store.get_memories_by_filter(
        session_config=config, limit=10000, user_id=user_id
    )
    clusters = _cluster_memories(memories)

    all_proposed: list[ProposedPatch] = []
    today = datetime.now(UTC).date().isoformat()
    total_in = int(state.get("usage_input_tokens", 0))
    total_out = int(state.get("usage_output_tokens", 0))

    if not llm or not llm.available:
        logger.info("dream.consolidate.no_llm", reason="LLM unavailable; no patches proposed")
        return {
            "patches": [],
            "errors": errors,
            "usage_input_tokens": total_in,
            "usage_output_tokens": total_out,
        }

    valid_ids = set(inventory.get("memory_ids", []) or [m.id for m in memories])

    # Bound the number of LLM calls — one per cluster, but cap at 20 for v0.
    for cluster in clusters[:20]:
        cluster_block = _format_cluster(cluster)
        user_prompt = CONSOLIDATE_USER_TEMPLATE.format(
            today=today,
            project=project_label,
            n_memories=inventory.get("n_memories", len(memories)),
            source_breakdown=inventory.get("source_breakdown", {}),
            content_type_breakdown=inventory.get("content_type_breakdown", {}),
            signal_block=signal_report,
            cluster_block=cluster_block,
            similarity_hints=_cosine_hints(cluster),
            instructions=instructions or "(none)",
        )
        full_prompt = CONSOLIDATE_SYSTEM + "\n\n" + user_prompt

        try:
            result, usage = await llm.generate_structured_with_usage(full_prompt, PatchSet)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"consolidate: {exc}")
            logger.warning("dream.consolidate.failed", error=str(exc))
            continue

        total_in += int(usage.get("input_tokens", 0))
        total_out += int(usage.get("output_tokens", 0))

        if not isinstance(result, PatchSet):
            continue

        for patch in result.patches:
            # Drop patches that reference unknown memory ids — guards against
            # LLM hallucination of identifiers.
            if patch.target_memory_ids and not (set(patch.target_memory_ids) <= valid_ids):
                logger.debug(
                    "dream.consolidate.dropped_unknown_ids",
                    patch_action=patch.action.value,
                    target_ids=patch.target_memory_ids,
                )
                continue
            all_proposed.append(patch)

    logger.info(
        "dream.consolidate",
        clusters=len(clusters),
        patches_proposed=len(all_proposed),
        usage_in=total_in,
        usage_out=total_out,
    )

    return {
        "patches": [p.model_dump() for p in all_proposed],
        "errors": errors,
        "usage_input_tokens": total_in,
        "usage_output_tokens": total_out,
    }


# ---------------------------------------------------------------------------
# Phase 4 — Prune & Index
# ---------------------------------------------------------------------------


async def index_node(state: DreamState) -> dict:
    """Persist the dream run + patches. Never mutates ``memories``."""
    metadata_store = state["metadata_store"]
    run: DreamRun = state["dream_run"]
    proposed = state.get("patches", [])
    inventory = state.get("inventory", {})
    handoffs = state.get("handoffs", [])

    run.input_memory_count = int(inventory.get("n_memories", 0))
    run.input_session_ids = [h.get("session_id") or h.get("file_path") or "" for h in handoffs]
    run.status = DreamStatus.COMPLETED
    run.ended_at = datetime.now(UTC)
    run.usage_input_tokens = int(state.get("usage_input_tokens", 0))
    run.usage_output_tokens = int(state.get("usage_output_tokens", 0))

    patches: list[DreamPatch] = []
    for raw in proposed:
        try:
            patches.append(
                DreamPatch(
                    dream_id=run.id,
                    action=DreamPatchAction(raw["action"]),
                    target_memory_ids=list(raw.get("target_memory_ids") or []),
                    new_content=raw.get("new_content"),
                    new_metadata=raw.get("new_metadata"),
                    evidence=raw.get("evidence"),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("dream.index.bad_patch", error=str(exc), raw=raw)

    await metadata_store.update_dream_run(
        run.id,
        status=run.status,
        ended_at=run.ended_at,
        input_memory_count=run.input_memory_count,
        input_session_ids=run.input_session_ids,
        usage_input_tokens=run.usage_input_tokens,
        usage_output_tokens=run.usage_output_tokens,
    )
    if patches:
        await metadata_store.create_dream_patches(patches)

    logger.info(
        "dream.index",
        dream_id=run.id,
        patches=len(patches),
        memories=run.input_memory_count,
        usage_in=run.usage_input_tokens,
        usage_out=run.usage_output_tokens,
    )
    return {"patches": [p.model_dump() for p in patches]}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_dream_graph():
    """Compile the dream LangGraph state machine."""
    graph = StateGraph(DreamState)
    graph.add_node("orient", orient_node)
    graph.add_node("gather", gather_signal_node)
    graph.add_node("consolidate", consolidate_node)
    graph.add_node("index", index_node)
    graph.add_edge(START, "orient")
    graph.add_edge("orient", "gather")
    graph.add_edge("gather", "consolidate")
    graph.add_edge("consolidate", "index")
    graph.add_edge("index", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def run_dream(
    *,
    project: str,
    metadata_store,
    embedder,
    settings: MemgenticSettings,
    signal_llm: LLMClient | None = None,
    consolidate_llm: LLMClient | None = None,
    signal_model: str | None = None,
    consolidate_model: str | None = None,
    instructions: str = "",
    limit_sessions: int | None = None,
    user_id: str = "",
) -> DreamRun:
    """Create a DreamRun, execute the pipeline, persist patches.

    Per-run model overrides
    -----------------------
    ``signal_model`` and ``consolidate_model`` accept any of the routing
    prefixes documented in the LLM-clients section: ``claude-*``,
    ``gemini-*``, ``gpt-*`` / ``openai/*``, or any other string that's
    treated as an Ollama tag (e.g. ``qwen3.6:35b-a3b``). When None, the
    factory falls back to ``settings.dream_signal_model`` /
    ``settings.dream_consolidate_model``. Pre-built LLMClients passed
    explicitly via ``signal_llm`` / ``consolidate_llm`` win over both.

    Returns the completed (or failed) DreamRun. Inspect ``run.status`` to
    distinguish success from failure; patches are queryable via
    ``metadata_store.get_dream_patches(run.id)``.
    """
    if instructions and len(instructions) > 4096:
        raise ValueError("instructions must be ≤ 4096 characters")

    if signal_llm is None:
        if signal_model is not None:
            client = _build_phase_llm(settings, signal_model, "signal")
            signal_llm = client if client is not None else LLMClient(settings)
        else:
            signal_llm = create_signal_llm(settings)
    if consolidate_llm is None:
        if consolidate_model is not None:
            client = _build_phase_llm(settings, consolidate_model, "consolidate")
            consolidate_llm = client if client is not None else LLMClient(settings)
        else:
            consolidate_llm = create_consolidate_llm(settings)

    # Record the model that drives the *Consolidate* phase — that's where
    # patches are produced. Per-run overrides take priority over settings.
    # Phase 2's model is informational only and reflected in logs.
    if consolidate_model is not None:
        model_name = consolidate_model
    elif getattr(consolidate_llm, "_provider_kind", None) == "anthropic":
        model_name = settings.dream_consolidate_model
    elif getattr(consolidate_llm, "_provider_kind", None) == "ollama":
        # Ollama path: the LLMClient was built either with explicit
        # ``settings.dream_consolidate_model`` (Ollama tag) or fell back
        # to ``settings.local_llm_model``.
        model_name = settings.dream_consolidate_model or settings.local_llm_model
    elif getattr(consolidate_llm, "_provider_kind", None) == "google":
        model_name = settings.dream_consolidate_model or settings.summarization_model
    else:
        model_name = settings.dream_consolidate_model or settings.summarization_model

    run = DreamRun(
        project=project,
        status=DreamStatus.RUNNING,
        model=model_name,
        instructions=instructions,
        user_id=user_id,
    )
    await metadata_store.create_dream_run(run)

    graph = build_dream_graph()
    state: DreamState = {
        "project": project,
        "instructions": instructions,
        "limit_sessions": int(limit_sessions or settings.dream_default_session_limit),
        "user_id": user_id,
        "metadata_store": metadata_store,
        "embedder": embedder,
        "settings": settings,
        "signal_llm": signal_llm,
        "consolidate_llm": consolidate_llm,
        "dream_run": run,
        "errors": [],
    }

    try:
        await graph.ainvoke(state)
    except Exception as exc:
        logger.exception("dream.run_failed", dream_id=run.id, error=str(exc))
        run.status = DreamStatus.FAILED
        run.error = str(exc)
        run.ended_at = datetime.now(UTC)
        await metadata_store.update_dream_run(
            run.id, status=run.status, error=run.error, ended_at=run.ended_at
        )
        return run

    refreshed = await metadata_store.get_dream_run(run.id)
    return refreshed or run


async def apply_dream(
    dream_id: str,
    *,
    metadata_store,
    only_non_destructive: bool = False,
    user_id: str = "",
) -> ApplyReport:
    """Execute proposed patches deterministically.

    When ``only_non_destructive`` is True, destructive actions (merge /
    supersede / archive_stale) are left as ``proposed`` for later explicit
    review. Non-destructive actions (normalize_date / insert_insight /
    update_field) are applied.
    """
    report = ApplyReport(dream_id=dream_id)
    run = await metadata_store.get_dream_run(dream_id)
    if not run:
        report.errors.append(f"dream {dream_id} not found")
        return report

    patches = await metadata_store.get_dream_patches(
        dream_id, status=DreamPatchStatus.PROPOSED.value
    )
    now = datetime.now(UTC)

    for patch in patches:
        if only_non_destructive and patch.action in DESTRUCTIVE_DREAM_ACTIONS:
            report.skipped_destructive += 1
            continue

        try:
            await _apply_patch(patch, metadata_store=metadata_store, user_id=user_id, report=report)
            await metadata_store.update_dream_patch_status(
                patch.id, DreamPatchStatus.APPLIED, applied_at=now
            )
            report.applied += 1
        except Exception as exc:
            report.errors.append(f"{patch.id}: {exc}")
            logger.warning("dream.apply.patch_failed", patch_id=patch.id, error=str(exc))

    # Only stamp ``applied_at`` when this call actually applied something —
    # otherwise we would overwrite the timestamp set by a previous successful
    # apply on a re-invocation that finds zero ``proposed`` patches.
    if report.applied:
        await metadata_store.update_dream_run(dream_id, applied_at=now)
    logger.info(
        "dream.apply",
        dream_id=dream_id,
        applied=report.applied,
        skipped_destructive=report.skipped_destructive,
        errors=len(report.errors),
    )
    return report


async def _apply_patch(
    patch: DreamPatch,
    *,
    metadata_store,
    user_id: str,
    report: ApplyReport,
) -> None:
    """Single-patch executor — pure deterministic mutation."""
    action = patch.action
    targets: list[str] = list(patch.target_memory_ids or [])

    if action in (DreamPatchAction.MERGE, DreamPatchAction.SUPERSEDE):
        if len(targets) < 2:
            return
        # Fetch all targets up front — required for SUPERSEDE to pick the
        # newest by ``created_at`` rather than blindly trusting list order.
        loaded: list[Memory] = []
        for tid in targets:
            mem = await metadata_store.get_memory(tid, user_id=user_id)
            if mem is not None:
                loaded.append(mem)
        if len(loaded) < 2:
            return

        if action == DreamPatchAction.SUPERSEDE:
            # The prompt promises "newer fact wins". Pick canonical by latest
            # ``created_at``; ties resolved by the LLM's listed order so the
            # MERGE-equivalent path stays deterministic for tests.
            canonical = max(loaded, key=lambda m: (m.created_at, targets.index(m.id)))
        else:  # MERGE — preserve the LLM's stated canonical (first entry)
            canonical = loaded[0]

        for other in loaded:
            if other.id == canonical.id:
                continue
            other.status = MemoryStatus.SUPERSEDED
            await metadata_store.save_memory(other)
            if other.id not in canonical.supersedes:
                canonical.supersedes.append(other.id)
            report.superseded_memories.append(other.id)
        await metadata_store.save_memory(canonical)
        return

    if action == DreamPatchAction.ARCHIVE_STALE:
        for mid in targets:
            await metadata_store.update_memory_status(
                mid, MemoryStatus.ARCHIVED.value, user_id=user_id
            )
            report.archived_memories.append(mid)
        return

    if action == DreamPatchAction.NORMALIZE_DATE:
        # Phase-0 implementation: log the chronograph triple intent. Wiring it
        # to the actual Chronograph store is a follow-up — apply still records
        # the patch as applied so the user knows it was acknowledged.
        report.chronograph_triples += 1
        logger.info(
            "dream.apply.normalize_date",
            target_ids=targets,
            metadata=patch.new_metadata,
        )
        return

    if action == DreamPatchAction.INSERT_INSIGHT:
        if not patch.new_content:
            return
        meta = patch.new_metadata or {}
        topics = list(meta.get("topics") or [])
        entities = list(meta.get("entities") or [])
        # ``target_memory_ids`` on INSERT_INSIGHT are CITATIONS, not memories
        # the insight replaces. Only honour an explicit ``supersedes`` field
        # in ``new_metadata`` — never silently auto-fill from targets, or we
        # corrupt the supersedes lineage by marking the cited evidence as
        # invalidated.
        memory = Memory(
            user_id=user_id,
            content=patch.new_content,
            content_type=ContentType.LEARNING,
            source=SourceMetadata(
                platform=Platform.DREAM,
                capture_method=CaptureMethod.AUTO_DAEMON,
                session_id=f"dream:{patch.dream_id}",
                session_title="Auto-Dream insight",
            ),
            topics=topics,
            entities=entities,
            confidence=float(meta.get("confidence", 0.85)),
            supersedes=list(meta.get("supersedes") or []),
        )
        await metadata_store.save_memory(memory)
        report.inserted_memories.append(memory.id)
        return

    if action == DreamPatchAction.UPDATE_FIELD:
        for mid in targets:
            mem = await metadata_store.get_memory(mid, user_id=user_id)
            if not mem:
                continue
            meta = patch.new_metadata or {}
            if "topics" in meta and isinstance(meta["topics"], list):
                mem.topics = list(meta["topics"])
            if "entities" in meta and isinstance(meta["entities"], list):
                mem.entities = list(meta["entities"])
            await metadata_store.save_memory(mem)
        return


async def reject_dream(
    dream_id: str,
    *,
    metadata_store,
) -> int:
    """Mark every still-proposed patch in this dream as rejected.

    Returns the number of patches transitioned. Idempotent — calling twice
    leaves the second call as a no-op.
    """
    patches = await metadata_store.get_dream_patches(
        dream_id, status=DreamPatchStatus.PROPOSED.value
    )
    now = datetime.now(UTC)
    for patch in patches:
        await metadata_store.update_dream_patch_status(
            patch.id, DreamPatchStatus.REJECTED, applied_at=now
        )
    logger.info("dream.reject", dream_id=dream_id, rejected=len(patches))
    return len(patches)
