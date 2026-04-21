"""Dataset → Memgentic ingestion helpers.

Each public loader yields :class:`benchmarks.lib.harness.CorpusSession`
and :class:`benchmarks.lib.harness.BenchmarkQuery` objects in memory.
Network access and large-file streaming are deliberately out of scope
for Phase 1 — datasets live on disk via ``benchmarks/datasets/download.sh``.

Phase 1 ships only the LongMemEval loader. Additional loaders (LoCoMo,
ConvoMem, MemBench) land alongside their runners in the Week 4 PRs per
plan §14.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from memgentic.models import ContentType, ConversationChunk, Platform

from benchmarks.lib.harness import BenchmarkQuery, CorpusSession


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
