"""Dataset → Memgentic ingestion helpers.

Each public loader yields :class:`benchmarks.lib.harness.CorpusSession`
and :class:`benchmarks.lib.harness.BenchmarkQuery` objects in memory.
Network access and large-file streaming are deliberately out of scope
— datasets live on disk via ``benchmarks/datasets/download.sh``.

Phase 2 adds four loaders next to the original LongMemEval one:

* :func:`load_locomo` — Salesforce/SNAP's long-conversation QA dataset
* :func:`load_convomem` — Salesforce's multi-category conversational
  memory dataset
* :func:`load_membench` — yikun-li/MemBench JSONL dataset
* :func:`load_cross_tool_transfer` — Memgentic-original cross-tool
  retrieval dataset (see
  ``benchmarks/datasets/cross_tool_transfer/README.md``)

Every loader is tagged "format v1 — verify against upstream on first
real run" in its docstring. The upstream schemas drift across
releases; loaders read only the fields we rely on and fail loudly when
required fields are missing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from memgentic.models import ContentType, ConversationChunk, Platform

from benchmarks.lib.harness import BenchmarkQuery, CorpusSession

# Map a Cross-Tool Transfer ``tool`` tag to the Memgentic ``Platform`` enum.
# Keys intentionally match the short identifiers used inside the AI-tool
# ecosystem so curation can use whichever the dataset author types.
_CROSS_TOOL_PLATFORMS: dict[str, Platform] = {
    "claude_code": Platform.CLAUDE_CODE,
    "claude-code": Platform.CLAUDE_CODE,
    "claude_desktop": Platform.CLAUDE_DESKTOP,
    "claude_web": Platform.CLAUDE_WEB,
    "chatgpt": Platform.CHATGPT,
    "gemini_cli": Platform.GEMINI_CLI,
    "gemini-cli": Platform.GEMINI_CLI,
    "gemini_web": Platform.GEMINI_WEB,
    "codex_cli": Platform.CODEX_CLI,
    "codex-cli": Platform.CODEX_CLI,
    "copilot_cli": Platform.COPILOT_CLI,
    "aider": Platform.AIDER,
    "cursor": Platform.CURSOR,
}


class CorpusLoaderError(RuntimeError):
    """Raised when a corpus file is missing or malformed."""


def load_longmemeval(dataset_path: str | Path) -> tuple[list[CorpusSession], list[BenchmarkQuery]]:
    """Load a LongMemEval dataset file into harness-ready objects.

    LongMemEval ships one JSON file per split. Each top-level record
    pairs a multi-turn chat history with a single labelled question and
    the session that answers it. We accept both the list-of-records
    shape and the ``{"records": [...]}`` envelope upstream occasionally
    uses.

    The public LongMemEval schema (see
    ``UCB-LongMemEval`` on GitHub) evolves across releases. This loader
    reads only the fields common to every release shipped so far:

    * ``question_id`` / ``question``
    * ``haystack_sessions``  — list of sessions; each is a list of
      ``{role, content}`` dicts
    * ``haystack_session_ids`` — parallel to ``haystack_sessions``
    * ``answer_session_ids`` — list of gold session IDs
    * ``question_type`` — optional category tag

    Args:
        dataset_path: Path to the JSON file on disk. The file is not
            distributed with Memgentic (see ``benchmarks/datasets/README.md``).

    Returns:
        ``(sessions, queries)`` — every unique session across the file
        followed by every labelled question.

    Raises:
        CorpusLoaderError: File is missing, unreadable, or violates the
            fields listed above. The message names the offending record
            where possible.
    """
    path = Path(dataset_path)
    if not path.exists():
        raise CorpusLoaderError(
            f"LongMemEval dataset not found at {path}. "
            "Download it via benchmarks/datasets/download.sh."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusLoaderError(f"Could not parse {path} as JSON: {exc}") from exc

    records = raw["records"] if isinstance(raw, dict) and "records" in raw else raw
    if not isinstance(records, list):
        raise CorpusLoaderError(
            f"Expected a list of LongMemEval records in {path}, got {type(records).__name__}"
        )

    sessions_by_id: dict[str, CorpusSession] = {}
    queries: list[BenchmarkQuery] = []

    for idx, record in enumerate(records):
        try:
            queries.append(_parse_longmemeval_record(record, sessions_by_id))
        except KeyError as exc:
            raise CorpusLoaderError(
                f"Record {idx} in {path} is missing required field {exc.args[0]!r}"
            ) from exc

    return list(sessions_by_id.values()), queries


def _parse_longmemeval_record(
    record: dict[str, Any],
    sessions_by_id: dict[str, CorpusSession],
) -> BenchmarkQuery:
    """Mutate ``sessions_by_id`` in place and return the query for ``record``."""
    question_id = str(record["question_id"])
    question_text = str(record["question"])
    haystack = record["haystack_sessions"]
    session_ids = record["haystack_session_ids"]
    gold_ids = record.get("answer_session_ids") or []
    if not isinstance(gold_ids, list):
        gold_ids = [gold_ids]

    if len(haystack) != len(session_ids):
        raise CorpusLoaderError(
            f"Record {question_id}: haystack_sessions / haystack_session_ids length mismatch "
            f"({len(haystack)} vs {len(session_ids)})"
        )

    for turns, session_id in zip(haystack, session_ids, strict=False):
        sid = str(session_id)
        if sid in sessions_by_id:
            # Sessions recur across questions; ingest once.
            continue
        sessions_by_id[sid] = CorpusSession(
            session_id=sid,
            chunks=list(_turns_to_chunks(turns)),
            platform=Platform.UNKNOWN,
            session_title=None,
        )

    return BenchmarkQuery(
        id=question_id,
        text=question_text,
        gold={str(g) for g in gold_ids},
        category=record.get("question_type"),
        metadata={"source_record_keys": sorted(record.keys())},
    )


def _turns_to_chunks(turns: Any) -> Iterator[ConversationChunk]:
    """Yield one :class:`ConversationChunk` per non-empty turn.

    Each turn is expected to be a dict with ``role`` and ``content``
    keys. Plain strings are also accepted (treated as user turns) to
    tolerate minor schema drift across dataset versions.
    """
    if not isinstance(turns, list):
        raise CorpusLoaderError(f"Expected a list of turns, got {type(turns).__name__}")

    for turn in turns:
        if isinstance(turn, str):
            role, content = "user", turn
        elif isinstance(turn, dict):
            role = str(turn.get("role", "user"))
            content = str(turn.get("content", ""))
        else:
            continue

        content = content.strip()
        if not content:
            continue

        yield ConversationChunk(
            content=content if role == "user" else f"[{role}] {content}",
            content_type=ContentType.RAW_EXCHANGE,
            topics=[],
            entities=[],
            confidence=1.0,
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    """Read the file as UTF-8 JSON or raise :class:`CorpusLoaderError`."""
    if not path.exists():
        raise CorpusLoaderError(
            f"Dataset not found at {path}. Run benchmarks/datasets/download.sh."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusLoaderError(f"Could not parse {path} as JSON: {exc}") from exc


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield non-empty JSON objects from a newline-delimited JSON file."""
    if not path.exists():
        raise CorpusLoaderError(
            f"Dataset not found at {path}. Run benchmarks/datasets/download.sh."
        )
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorpusLoaderError(f"{path}:{line_no} is not valid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise CorpusLoaderError(
                    f"{path}:{line_no} expected a JSON object, got {type(obj).__name__}"
                )
            yield obj


def _single_chunk(content: str) -> list[ConversationChunk]:
    """Wrap a string as a single :class:`ConversationChunk`."""
    text = content.strip()
    if not text:
        return []
    return [
        ConversationChunk(
            content=text,
            content_type=ContentType.RAW_EXCHANGE,
            topics=[],
            entities=[],
            confidence=1.0,
        )
    ]


# ---------------------------------------------------------------------------
# LoCoMo
# ---------------------------------------------------------------------------
def load_locomo(dataset_path: str | Path) -> tuple[list[CorpusSession], list[BenchmarkQuery]]:
    """Load LoCoMo's long-conversation QA dataset.

    Format v1 — verify against upstream on first real run. LoCoMo's
    ``locomo10.json`` ships a list of ten "samples"; each sample carries
    a ``conversation`` block with multiple sessions keyed as
    ``session_1``, ``session_2``, ... and a ``qa`` list whose entries
    have ``question``, ``answer`` and ``evidence`` (list of session IDs
    or free-form strings identifying the supporting session).

    This loader reads only those fields and tolerates mild drift
    (missing ``evidence`` becomes an empty gold set; sessions may be
    stored as a list or a dict). Every ``(sample_id, session_key)``
    pair becomes a :class:`CorpusSession`; ``gold`` is the set of
    evidence identifiers as they appear in the sample, stringified.

    Args:
        dataset_path: Path to ``locomo10.json`` (or a Phase-2 reshard).

    Returns:
        ``(sessions, queries)`` — sessions across every sample in the
        file, followed by every QA pair found.
    """
    path = Path(dataset_path)
    raw = _read_json(path)
    samples = raw if isinstance(raw, list) else raw.get("samples") or raw.get("data") or []
    if not isinstance(samples, list):
        raise CorpusLoaderError(
            f"Expected a list of LoCoMo samples in {path}, got {type(samples).__name__}"
        )

    sessions: list[CorpusSession] = []
    queries: list[BenchmarkQuery] = []

    for sample_idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("sample_id") or sample.get("id") or sample_idx)
        conversation = sample.get("conversation") or {}
        qa_list = sample.get("qa") or sample.get("qas") or []

        sessions.extend(_locomo_sessions(sample_id, conversation))
        queries.extend(_locomo_queries(sample_id, qa_list))

    return sessions, queries


def _locomo_sessions(sample_id: str, conversation: Any) -> Iterator[CorpusSession]:
    """Yield one :class:`CorpusSession` per session found in ``conversation``.

    Accepts both dict-keyed (``{"session_1": [...], ...}``) and list
    shapes; anything else is skipped quietly so a single malformed
    sample doesn't break the whole run.
    """
    if isinstance(conversation, dict):
        items = conversation.items()
    elif isinstance(conversation, list):
        items = ((f"session_{idx + 1}", turns) for idx, turns in enumerate(conversation))
    else:
        return

    for key, turns in items:
        if not isinstance(key, str) or not key.startswith("session"):
            # LoCoMo uses ``session_1`` / ``session_2`` etc.; skip meta keys.
            continue
        session_id = f"{sample_id}::{key}"
        chunks = list(_turns_to_chunks(turns)) if isinstance(turns, list) else []
        if not chunks:
            continue
        yield CorpusSession(
            session_id=session_id,
            chunks=chunks,
            platform=Platform.UNKNOWN,
            session_title=None,
            metadata={"sample_id": sample_id, "session_key": key},
        )


def _locomo_queries(sample_id: str, qa_list: Any) -> Iterator[BenchmarkQuery]:
    if not isinstance(qa_list, list):
        return
    for qa_idx, qa in enumerate(qa_list):
        if not isinstance(qa, dict):
            continue
        question = str(qa.get("question") or "").strip()
        if not question:
            continue
        evidence = qa.get("evidence") or qa.get("evidence_sessions") or []
        if not isinstance(evidence, list):
            evidence = [evidence]
        gold = {f"{sample_id}::{ev}" for ev in evidence if ev}
        yield BenchmarkQuery(
            id=f"{sample_id}::qa{qa_idx}",
            text=question,
            gold=gold,
            category=str(qa.get("category") or qa.get("type") or "") or None,
            metadata={"answer": qa.get("answer")},
        )


# ---------------------------------------------------------------------------
# ConvoMem
# ---------------------------------------------------------------------------
def load_convomem(dataset_path: str | Path) -> tuple[list[CorpusSession], list[BenchmarkQuery]]:
    """Load Salesforce's ConvoMem dataset.

    Format v1 — verify against upstream on first real run. ConvoMem
    ships ~250 questions split across five categories. Each record is
    expected to be::

        {
            "id": "cm-001",
            "category": "single_hop",
            "conversation": [{"role": "user", "content": "..."}, ...],
            "question": "Who is Alice's mentor?",
            "answer": "Bob",
            "session_id": "sess-42",           # optional
            "evidence": ["sess-42", ...]        # optional, gold session IDs
        }

    The loader accepts a top-level list or a ``{"data": [...]}``
    envelope. Each record's ``conversation`` becomes a single
    :class:`CorpusSession`; the question produces one
    :class:`BenchmarkQuery` with its gold set taken from ``evidence``
    (preferred) or ``session_id`` (fallback).
    """
    path = Path(dataset_path)
    raw = _read_json(path)
    records = raw if isinstance(raw, list) else raw.get("data") or raw.get("records") or []
    if not isinstance(records, list):
        raise CorpusLoaderError(
            f"Expected a list of ConvoMem records in {path}, got {type(records).__name__}"
        )

    sessions_by_id: dict[str, CorpusSession] = {}
    queries: list[BenchmarkQuery] = []

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        question = str(record.get("question") or "").strip()
        if not question:
            continue

        record_id = str(record.get("id") or record.get("question_id") or f"cm-{idx}")
        session_id = str(record.get("session_id") or record_id)
        conversation = record.get("conversation") or []

        if session_id not in sessions_by_id:
            chunks = list(_turns_to_chunks(conversation)) if isinstance(conversation, list) else []
            if chunks:
                sessions_by_id[session_id] = CorpusSession(
                    session_id=session_id,
                    chunks=chunks,
                    platform=Platform.UNKNOWN,
                    session_title=None,
                    metadata={"category": record.get("category")},
                )

        evidence = record.get("evidence")
        if isinstance(evidence, list) and evidence:
            gold = {str(e) for e in evidence}
        elif evidence:
            gold = {str(evidence)}
        else:
            gold = {session_id}

        queries.append(
            BenchmarkQuery(
                id=record_id,
                text=question,
                gold=gold,
                category=str(record.get("category") or "") or None,
                metadata={"answer": record.get("answer")},
            )
        )

    return list(sessions_by_id.values()), queries


# ---------------------------------------------------------------------------
# MemBench
# ---------------------------------------------------------------------------
def load_membench(dataset_path: str | Path) -> tuple[list[CorpusSession], list[BenchmarkQuery]]:
    """Load MemBench's JSONL dataset.

    Format v1 — verify against upstream on first real run. MemBench
    (ACL 2025, yikun-li/MemBench) ships ~8.5k questions as JSONL.
    Each line is expected to be::

        {
            "question_id": "mb-0001",
            "question": "...",
            "context": "long supporting passage",
            "source_id": "ctx-123",     # ID of the supporting context
            "category": "factual"        # optional
        }

    We treat ``source_id`` as both the session identifier (so ingestion
    deduplicates shared contexts across questions) and the sole gold
    item for the question. Questions with neither a ``source_id`` nor
    a ``context`` are skipped.
    """
    path = Path(dataset_path)
    sessions_by_id: dict[str, CorpusSession] = {}
    queries: list[BenchmarkQuery] = []

    for record in _iter_jsonl(path):
        question = str(record.get("question") or "").strip()
        if not question:
            continue
        source_id = record.get("source_id") or record.get("context_id")
        context = record.get("context") or record.get("passage") or ""
        record_id = str(record.get("question_id") or record.get("id") or f"mb-{len(queries)}")

        if source_id is None and not context:
            continue
        session_id = str(source_id) if source_id is not None else f"{record_id}::ctx"

        if session_id not in sessions_by_id and context:
            chunks = _single_chunk(str(context))
            if chunks:
                sessions_by_id[session_id] = CorpusSession(
                    session_id=session_id,
                    chunks=chunks,
                    platform=Platform.UNKNOWN,
                    session_title=None,
                    metadata={"category": record.get("category")},
                )

        queries.append(
            BenchmarkQuery(
                id=record_id,
                text=question,
                gold={session_id},
                category=str(record.get("category") or "") or None,
                metadata={"answer": record.get("answer")},
            )
        )

    return list(sessions_by_id.values()), queries


# ---------------------------------------------------------------------------
# Cross-Tool Transfer (Memgentic-original)
# ---------------------------------------------------------------------------
def load_cross_tool_transfer(
    dataset_path: str | Path,
) -> tuple[list[CorpusSession], list[BenchmarkQuery]]:
    """Load the Memgentic Cross-Tool Transfer JSONL fixture.

    Format v1 — verify against upstream on first real run. Every line
    is one "turn" object. The loader distinguishes two kinds of
    turns by a ``role`` field:

    * ``"turn"`` (default) — belongs to a conversation; becomes a
      :class:`ConversationChunk` inside the session identified by
      ``session_id``. The ``tool`` field maps to a
      :class:`memgentic.models.Platform` for provenance.
    * ``"query"`` — a follow-up question the benchmark asks
      cross-tool. Produces a :class:`BenchmarkQuery` whose ``gold``
      set is ``ground_truth_memory_ids`` (or ``ground_truth_session_ids``
      as a fallback).

    If a record has no explicit role we treat it as a conversation
    turn when ``content`` is non-empty and as a query when
    ``ground_truth_memory_ids`` is non-empty.

    Expected fields per the dataset README:

    ``tool`` (str)            platform identifier (claude_code, chatgpt, …)
    ``turn`` (int)            turn number within the session
    ``content`` (str)         utterance text
    ``session_id`` (str)      conversation identifier
    ``ground_truth_memory_ids`` (list[str])  gold retrieval targets
    """
    path = Path(dataset_path)
    sessions_by_id: dict[str, list[ConversationChunk]] = {}
    session_platforms: dict[str, Platform] = {}
    queries: list[BenchmarkQuery] = []

    for record in _iter_jsonl(path):
        role = str(record.get("role") or "").strip().lower()
        content = str(record.get("content") or "").strip()
        gold_ids = (
            record.get("ground_truth_memory_ids") or record.get("ground_truth_session_ids") or []
        )
        if not isinstance(gold_ids, list):
            gold_ids = [gold_ids]

        if not role:
            role = "query" if gold_ids else "turn"

        session_id = str(record.get("session_id") or "")
        tool = str(record.get("tool") or "").strip().lower()

        if role == "query":
            if not content:
                continue
            queries.append(
                BenchmarkQuery(
                    id=str(record.get("query_id") or record.get("id") or f"ctt-q{len(queries)}"),
                    text=content,
                    gold={str(g) for g in gold_ids if g},
                    category=str(record.get("category") or "") or None,
                    metadata={
                        "source_tool": tool or None,
                        "target_tool": record.get("target_tool"),
                        "session_id": session_id or None,
                    },
                )
            )
            continue

        # Conversation turn.
        if not session_id or not content:
            continue
        sessions_by_id.setdefault(session_id, []).extend(_single_chunk(content))
        if tool and session_id not in session_platforms:
            session_platforms[session_id] = _CROSS_TOOL_PLATFORMS.get(tool, Platform.UNKNOWN)

    sessions = [
        CorpusSession(
            session_id=sid,
            chunks=chunks,
            platform=session_platforms.get(sid, Platform.UNKNOWN),
            session_title=None,
            metadata={"tool": session_platforms.get(sid, Platform.UNKNOWN).value},
        )
        for sid, chunks in sessions_by_id.items()
        if chunks
    ]
    return sessions, queries
