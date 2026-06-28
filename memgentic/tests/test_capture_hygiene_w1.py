"""W1 — capture-hygiene tests (memory-quality remediation).

Each filter added in W1 is proven two ways, per the remediation discipline:
  (a) a real noise sample that MUST be dropped, and
  (b) a real knowledge sample that MUST still pass.

Filters covered:
  1. Internal/temp dir excludes      (adapters/base.py)
  2. isSidechain turn skip            (adapters/claude_code.py)
  3. Meta-prompt detection in is_noise(processing/heuristics.py)
  4. distillation.is_valuable gate    (processing/pipeline.py)
  5. >=2-keyword classification       (processing/heuristics.py / intelligence.py)
  6. Oversized-blob cap               (processing/pipeline.py)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.adapters.base import BaseAdapter, _compiled_exclude_globs, _path_is_excluded
from memgentic.adapters.claude_code import ClaudeCodeAdapter
from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    ContentType,
    ConversationChunk,
    Platform,
)
from memgentic.processing.heuristics import (
    CONTENT_TYPE_KEYWORDS as HEURISTICS_CONTENT_TYPE_KEYWORDS,
)
from memgentic.processing.heuristics import (
    heuristic_classify,
    is_meta_prompt,
    is_noise,
)
from memgentic.processing.intelligence import (
    _CONTENT_TYPE_KEYWORDS as INTEL_CONTENT_TYPE_KEYWORDS,
)
from memgentic.processing.intelligence import (
    ClassificationResult,
    DistillationResult,
    ExtractionResult,
    SummaryResult,
)
from memgentic.processing.pipeline import (
    _MAX_CHUNK_CONTENT_CHARS,
    IngestionPipeline,
    _distillation_is_worthless,
    _enforce_chunk_size_cap,
    _truncate_if_oversized,
)
from memgentic.storage.metadata import MetadataStore

DIMS = 768


# ---------------------------------------------------------------------------
# Local fixtures (mirrors test_intelligence_activation.py)
# ---------------------------------------------------------------------------


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


def _mock_llm(available: bool = True):
    llm = MagicMock()
    llm.available = available
    llm.generate = AsyncMock(return_value="")
    llm.generate_structured = AsyncMock(return_value=None)
    return llm


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_query = embedder.embed
    embedder.embed_document = embedder.embed
    embedder.embed_batch.side_effect = lambda texts: [
        _fake_embedding(0.1 * i) for i in range(len(texts))
    ]
    embedder.embed_batch_documents = embedder.embed_batch
    return embedder


@pytest.fixture()
def mock_vector_store():
    vs = AsyncMock()
    vs.upsert_memory = AsyncMock()
    vs.upsert_memories_batch = AsyncMock()
    vs.search = AsyncMock(return_value=[])
    vs.delete_memory = AsyncMock()
    return vs


class _FakeAdapter(BaseAdapter):
    """Minimal adapter that watches a single directory for *.jsonl files."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def platform(self) -> Platform:
        return Platform.UNKNOWN

    @property
    def watch_paths(self) -> list[Path]:
        return [self._root]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.jsonl"]

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        return []

    async def get_session_id(self, file_path: Path) -> str | None:
        return None

    async def get_session_title(self, file_path: Path) -> str | None:
        return None


# ===========================================================================
# 1. Internal/temp dir excludes (adapters/base.py)
# ===========================================================================


class TestExcludeDirs:
    def test_temp_task_dir_is_excluded(self):
        # NOISE: Claude Code internal task dir slugged from an OS temp path.
        junk = (
            Path.home()
            / ".claude"
            / "projects"
            / ("C--Users-harit-AppData-Local-Temp-claude-task-abc")
            / "session.jsonl"
        )
        assert _path_is_excluded(junk, _compiled_exclude_globs()) is True

    def test_appdata_local_temp_dir_is_excluded(self):
        # Fix 4 (W1 review): the bare "*-Local-Temp*" glob was removed as too
        # broad.  Only the Windows-AppData-specific slug is excluded.
        appdata_junk = Path(
            "/home/u/.claude/projects/C--Users-harit-AppData-Local-Temp-task/conv.jsonl"
        )
        assert _path_is_excluded(appdata_junk, _compiled_exclude_globs()) is True

    def test_non_appdata_local_temp_dir_is_not_excluded(self):
        # A path that contains "-Local-Temp-" but NOT "AppData" is no longer
        # excluded after Fix 4 — the broad glob was removed.
        other = Path("/home/u/.claude/projects/x--Local-Temp-y/conv.jsonl")
        assert _path_is_excluded(other, _compiled_exclude_globs()) is False

    def test_real_project_dir_is_not_excluded(self):
        # KNOWLEDGE: an ordinary repo session must NOT be excluded.
        real = (
            Path.home()
            / ".claude"
            / "projects"
            / ("C--Users-harit-Desktop-Business-Projects-EllinBid")
            / "session.jsonl"
        )
        assert _path_is_excluded(real, _compiled_exclude_globs()) is False

    def test_observer_excludes_still_apply(self):
        observer = Path("/home/u/.claude/projects/x--claude-mem-observer-sessions/c.jsonl")
        assert _path_is_excluded(observer, _compiled_exclude_globs()) is True

    def test_discover_files_drops_temp_keeps_real(self, tmp_path: Path):
        temp_dir = tmp_path / "C--Users-harit-AppData-Local-Temp-task"
        temp_dir.mkdir()
        (temp_dir / "junk.jsonl").write_text("{}\n", encoding="utf-8")

        real_dir = tmp_path / "C--Users-harit-Desktop-real-project"
        real_dir.mkdir()
        real_file = real_dir / "good.jsonl"
        real_file.write_text("{}\n", encoding="utf-8")

        found = _FakeAdapter(tmp_path).discover_files()
        assert real_file in found
        assert all("AppData-Local-Temp" not in str(f) for f in found)


# ===========================================================================
# 2. isSidechain turn skip (adapters/claude_code.py)
# ===========================================================================


class TestSidechainSkip:
    async def test_sidechain_turns_dropped_main_kept(self, tmp_path: Path):
        turns = [
            {
                "role": "human",
                "content": (
                    "MAIN_USER_QUESTION: How should I structure the FastAPI project so that "
                    "routers, services and repositories stay cleanly separated for a medium API?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "MAIN_ASSISTANT_ANSWER: Use a layered structure — thin routers call "
                    "services, services call repositories, and dependency injection keeps "
                    "everything testable across the whole application surface."
                ),
            },
            {
                "role": "human",
                "isSidechain": True,
                "content": (
                    "SIDECHAIN_TASK_PROMPT: You are summarizing the daily log. Produce a terse "
                    "bullet digest of everything that happened in this session for the archive."
                ),
            },
            {
                "role": "assistant",
                "isSidechain": True,
                "content": (
                    "SIDECHAIN_TASK_OUTPUT: - did a thing - did another thing - wrapped up the "
                    "session and stored the digest for later retrieval by the summarizer task."
                ),
            },
        ]
        f = tmp_path / "conv.jsonl"
        f.write_text("\n".join(json.dumps(t) for t in turns), encoding="utf-8")

        chunks = await ClaudeCodeAdapter().parse_file(f)
        blob = "\n".join(c.content for c in chunks)

        # NOISE: nothing from the sidechain leaks into any memory.
        assert "SIDECHAIN_TASK_PROMPT" not in blob
        assert "SIDECHAIN_TASK_OUTPUT" not in blob
        # KNOWLEDGE: the real exchange is preserved.
        assert "MAIN_USER_QUESTION" in blob
        assert "MAIN_ASSISTANT_ANSWER" in blob


# ===========================================================================
# 3. Meta-prompt detection in is_noise (processing/heuristics.py)
# ===========================================================================

# Real internal-task prompt openings observed in the audit.
# NOTE (Fix 2, W1 review): "Rules: ..." and "Instructions: ..." samples were
# removed because the bare label pattern was too broad — it incorrectly
# filtered genuine knowledge entries like
# "Guidelines: always prefer psycopg 3 over asyncpg for consistency."
# Those two openings are no longer detected as meta-prompts (acceptable
# false-negative trade-off per the W1 review).
META_PROMPT_SAMPLES = [
    "You are a daily-log summarizer. Summarize the following session into bullets.",
    "Human: You are summarizing this conversation for compaction.",
    "You are an ADVERSARIAL verifier whose job is to find flaws in the claim below.",
    "You are a memory classifier. Assign exactly one category to each chunk.",
    "Apply maximum non-destructive compression to the following transcript.",
    "Human: Apply compression to the conversation while preserving every decision.",
    "Your task is to create a detailed summary of the conversation so far.",
    "This session is being continued from a previous conversation that ran out of context.",
    "[SUGGESTION MODE] Propose three next actions for the user without doing them.",
    # New concrete role nouns added in Fix 1 (W1 review):
    "You are summarizer. Here is the session to compress.",
    "You are evaluator. Score the following claim for accuracy.",
    "You are verifier. Check whether the facts below are correct.",
    "You are classifier. Assign one of the following content types.",
    "You are memory consolidation agent. Merge duplicate entries.",
]

# Genuine knowledge that MUST survive the meta-prompt filter.
KNOWLEDGE_SAMPLES = [
    "We decided to use PostgreSQL because JSONB lets us avoid a second datastore.",
    "You are correct that the migration needs row-level security in the first revision.",
    "FastAPI is built on Starlette and supports async routes natively.",
    "The bug was a missing await in the embedder batch call; fixed by awaiting the gather.",
    "I prefer psycopg 3 over asyncpg here because we already depend on it elsewhere.",
]


class TestMetaPromptDetection:
    @pytest.mark.parametrize("sample", META_PROMPT_SAMPLES)
    def test_meta_prompt_is_flagged(self, sample: str):
        assert is_meta_prompt(sample) is True
        assert is_noise(sample) is True  # NOISE: dropped by the pipeline filter

    @pytest.mark.parametrize("sample", KNOWLEDGE_SAMPLES)
    def test_knowledge_is_not_meta_prompt(self, sample: str):
        assert is_meta_prompt(sample) is False
        assert is_noise(sample) is False  # KNOWLEDGE: survives

    def test_leading_whitespace_does_not_evade(self):
        assert is_meta_prompt("   You are a summarizer of logs and digests.") is True

    def test_empty_is_not_meta_prompt(self):
        assert is_meta_prompt("") is False

    # Fix 1 keep-test (W1 review): "You are the X" must no longer be filtered —
    # "the " was removed from the alternation because it over-matched real
    # knowledge like "You are the right engineer to ask about this migration."
    def test_you_are_the_right_engineer_is_kept(self):
        assert is_meta_prompt("You are the right engineer to ask about this migration.") is False

    # Fix 2 keep-test (W1 review): genuine project guidelines must survive the
    # meta-prompt filter — the bare label pattern was too broad.
    def test_guidelines_knowledge_is_kept(self):
        assert (
            is_meta_prompt("Guidelines: always prefer psycopg 3 over asyncpg for consistency.")
            is False
        )


# ===========================================================================
# 4. distillation.is_valuable write gate (processing/pipeline.py)
# ===========================================================================


class TestValueGateHelper:
    def test_explicitly_worthless_is_dropped(self):
        # NOISE: model said not valuable AND scored it below the floor.
        d = {"is_valuable": False, "value_score": 0.1}
        assert _distillation_is_worthless(d, 0.25) is True

    def test_valuable_is_kept(self):
        d = {"is_valuable": True, "value_score": 0.9}
        assert _distillation_is_worthless(d, 0.25) is False

    def test_low_score_but_valuable_is_kept(self):
        # is_valuable must be explicitly False to drop.
        d = {"is_valuable": True, "value_score": 0.05}
        assert _distillation_is_worthless(d, 0.25) is False

    def test_worthless_but_high_score_is_kept(self):
        # Both conditions required — a high score rescues it.
        d = {"is_valuable": False, "value_score": 0.8}
        assert _distillation_is_worthless(d, 0.25) is False

    def test_absent_signal_is_kept(self):
        # KNOWLEDGE: never drop when the signal is missing/None.
        assert _distillation_is_worthless(None, 0.25) is False
        assert _distillation_is_worthless({}, 0.25) is False
        assert _distillation_is_worthless({"is_valuable": False}, 0.25) is False
        assert _distillation_is_worthless({"is_valuable": None, "value_score": 0.0}, 0.25) is False

    def test_bool_value_score_is_not_numeric(self):
        # A stray bool must not be treated as a 0/1 score.
        assert (
            _distillation_is_worthless({"is_valuable": False, "value_score": False}, 0.25) is False
        )

    def test_value_score_at_boundary_is_kept(self):
        # Fix 5 (W1 review): value_score == value_gate_min_score (0.25) with
        # is_valuable=False must be KEPT — the gate uses strict < semantics.
        assert (
            _distillation_is_worthless({"is_valuable": False, "value_score": 0.25}, 0.25) is False
        )


class TestValueGatePipeline:
    async def test_worthless_chunk_dropped_valuable_kept(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, tmp_path
    ):
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
            embedding_dimensions=DIMS,
            enable_fact_distillation=True,
            enable_value_gate=True,
            value_gate_min_score=0.25,
            enable_write_time_dedup=False,
            enable_corroboration=False,
        )
        llm = _mock_llm(available=True)
        # Order: classify(c0), classify(c1), distill(c0), distill(c1), extract, summarize
        llm.generate_structured.side_effect = [
            ClassificationResult(content_type="decision", confidence=0.9),
            ClassificationResult(content_type="raw_exchange", confidence=0.6),
            DistillationResult(facts=["chose postgres"], is_valuable=True, value_score=0.9),
            DistillationResult(facts=[], is_valuable=False, value_score=0.05),
            ExtractionResult(topics=["postgres"], entities=["PostgreSQL"]),
            SummaryResult(summary="summary"),
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content=(
                    "KEEP_ME: We decided to use PostgreSQL for the API because JSONB removes "
                    "the need for a second document store and simplifies the deployment."
                ),
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content=(
                    "DROP_ME: ok sounds good thanks, talk later, have a nice weekend everyone "
                    "and see you on monday for the next sync about nothing in particular."
                ),
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            session_id="vg-session",
        )

        # The worthless chunk is gone; the real decision survives.
        assert len(memories) == 1
        assert "KEEP_ME" in memories[0].content
        assert all("DROP_ME" not in m.content for m in memories)

    async def test_gate_off_keeps_both(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, tmp_path
    ):
        settings = MemgenticSettings(
            data_dir=tmp_path / "data2",
            storage_backend=StorageBackend.LOCAL,
            embedding_dimensions=DIMS,
            enable_fact_distillation=True,
            enable_value_gate=False,  # disabled -> nothing dropped
            enable_write_time_dedup=False,
            enable_corroboration=False,
        )
        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = [
            ClassificationResult(content_type="decision", confidence=0.9),
            ClassificationResult(content_type="raw_exchange", confidence=0.6),
            DistillationResult(facts=["x"], is_valuable=True, value_score=0.9),
            DistillationResult(facts=[], is_valuable=False, value_score=0.05),
            ExtractionResult(topics=[], entities=[]),
            SummaryResult(summary="s"),
        ]
        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )
        chunks = [
            ConversationChunk(
                content="KEEP_A: a long enough sentence about a real architectural decision here.",
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content="KEEP_B: another long enough sentence that the gate would normally drop.",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]
        memories = await pipeline.ingest_conversation(
            chunks=chunks, platform=Platform.CLAUDE_CODE, session_id="vg-off"
        )
        assert len(memories) == 2


# ===========================================================================
# 5. >=2-keyword classification (processing/heuristics.py)
# ===========================================================================


class TestKeywordTightening:
    def test_single_stray_keyword_is_raw_exchange(self):
        # NOISE-ish: a lone keyword in prose must NOT mislabel the type.
        ct, _ = heuristic_classify("We had a long chat and version control came up once.")
        assert ct == "raw_exchange"

    def test_two_keywords_classify(self):
        # KNOWLEDGE: a genuine multi-signal decision still classifies.
        ct, conf = heuristic_classify(
            "We decided to migrate; the team chose Postgres and finalized the decision."
        )
        assert ct == "decision"
        assert conf == 0.85

    def test_removed_from_keyword_no_longer_codes_prose(self):
        # "from " used to force code_snippet on ordinary English prose.
        ct, _ = heuristic_classify("She walked home from the office after a quiet afternoon.")
        assert ct == "raw_exchange"

    def test_removed_return_keyword_no_longer_codes_prose(self):
        ct, _ = heuristic_classify("I will return the favour when you are back in town.")
        assert ct == "raw_exchange"

    def test_real_code_still_classifies(self):
        ct, _ = heuristic_classify("```python\nimport os\ndef main():\n    pass\n```")
        assert ct == "code_snippet"


# ===========================================================================
# Fix 3 (W1 review): Native classify drift guard
# ===========================================================================


class TestNativeClassifyDriftGuard:
    """Guard that the Python keyword tables never re-introduce the English-
    ambiguous tokens "from ", "let ", "return " that were removed in W1 (RC6).

    Both the Python dicts (heuristics.py and intelligence.py) MUST stay in
    sync with memgentic-native/src/textproc/classify.rs — see the DRIFT GUARD
    comment at the top of each keyword dict.
    """

    _BANNED = {"from ", "let ", "return "}

    def _all_keywords(self, kw_dict: dict) -> set[str]:
        result: set[str] = set()
        for kws in kw_dict.values():
            result.update(kws)
        return result

    def test_heuristics_keywords_no_banned_tokens(self):
        found = self._all_keywords(HEURISTICS_CONTENT_TYPE_KEYWORDS) & self._BANNED
        assert not found, (
            f"heuristics.py CONTENT_TYPE_KEYWORDS contains banned token(s) {found!r} "
            f"— these fire on plain English prose and must not be re-added."
        )

    def test_intelligence_keywords_no_banned_tokens(self):
        found = self._all_keywords(INTEL_CONTENT_TYPE_KEYWORDS) & self._BANNED
        assert not found, (
            f"intelligence.py _CONTENT_TYPE_KEYWORDS contains banned token(s) {found!r} "
            f"— these fire on plain English prose and must not be re-added."
        )


# ===========================================================================
# 6. Oversized-blob cap (processing/pipeline.py)
# ===========================================================================


class TestOversizedCap:
    def test_truncate_marks_oversized(self):
        big = "x" * 1000
        out = _truncate_if_oversized(big, 100)
        assert out.startswith("x" * 100)
        assert "[truncated by Memgentic" in out
        assert "1000" in out

    def test_truncate_leaves_small_untouched(self):
        small = "a real, short memory worth keeping"
        assert _truncate_if_oversized(small, 100) == small

    def test_enforce_cap_truncates_chunk(self):
        chunks = [
            ConversationChunk(content="y" * 5000, content_type=ContentType.RAW_EXCHANGE),
            ConversationChunk(content="short and real", content_type=ContentType.RAW_EXCHANGE),
        ]
        out = _enforce_chunk_size_cap(chunks, Platform.CLAUDE_CODE, cap=1000)
        assert len(out[0].content) < 5000
        assert "[truncated by Memgentic" in out[0].content
        assert out[1].content == "short and real"  # KNOWLEDGE: untouched

    def test_default_cap_is_64kb(self):
        assert _MAX_CHUNK_CONTENT_CHARS == 65_536
        assert MemgenticSettings().max_memory_content_chars == 65_536
