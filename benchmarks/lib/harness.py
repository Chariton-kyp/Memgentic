"""BenchmarkHarness — shared setup/ingest/evaluate/teardown loop.

The harness wraps a throw-away Memgentic instance so every run starts
from an empty DB and leaves no state behind. It is deliberately thin:
runner-specific parsing (how a dataset maps to ``ConversationChunk``
objects) and runner-specific scoring (which identifiers count as gold)
stay out of here so the same harness drives LongMemEval, LoCoMo,
ConvoMem, MemBench, and Cross-Tool Transfer without branching.

The ``profile`` argument accepts ``"raw"``, ``"enriched"``, ``"dual"`` and
a small set of synonyms documented in :meth:`BenchmarkHarness.__init__`.
Phase 2 wires the profile end-to-end: every ingestion call made through
:meth:`BenchmarkHarness.ingest_session` forwards the profile to
:meth:`memgentic.processing.pipeline.IngestionPipeline.ingest_conversation`
via its ``capture_profile`` argument, so ``raw`` runs bypass LLM
enrichment, ``enriched`` runs go through the full Gemini-Flash-Lite
pipeline, and ``dual`` runs emit paired raw/enriched memories.
"""

from __future__ import annotations

import contextlib
import json
import random
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memgentic.config import EmbeddingProvider, MemgenticSettings, StorageBackend
from memgentic.models import CaptureMethod, CaptureProfile, ConversationChunk, Platform
from memgentic.processing.embedder import Embedder
from memgentic.processing.llm import LLMClient
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

# Random seed for any sampling done inside the harness (shuffles, MMR, …).
# Matches the seed pinned in benchmarks/BENCHMARKS.md §Reproducibility.
DEFAULT_SEED = 42

_KNOWN_PROFILES = {"raw", "enriched", "dual"}
_PROFILE_ALIASES = {
    # Accept a couple of friendly aliases without locking the plan in.
    "verbatim": "raw",
    "llm": "enriched",
}


@dataclass
class CorpusSession:
    """One session / conversation worth of chunks, ready for ingestion.

    Corpus loaders convert their dataset's native format into
    ``CorpusSession`` objects; the harness does not care how the source
    file is parsed.
    """

    session_id: str
    chunks: list[ConversationChunk]
    platform: Platform = Platform.UNKNOWN
    session_title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkQuery:
    """One evaluation query with its gold answer(s).

    ``gold`` is a set of identifiers (session_ids, memory_ids, …) depending
    on the benchmark. The scoring callable passed to :meth:`evaluate`
    decides how to use them.
    """

    id: str
    text: str
    gold: set[str]
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


#: Signature of the per-query scorer passed to :meth:`BenchmarkHarness.evaluate`.
#: Takes the query plus the ranked vector-store hits and returns a JSON-
#: serialisable dict of per-question metrics. Runners own the shape.
ScorerFn = Callable[[BenchmarkQuery, list[dict[str, Any]]], Mapping[str, Any]]


class BenchmarkHarness:
    """Isolated, reproducible Memgentic instance for benchmark runs.

    The harness owns a temp data directory, a throw-away SQLite metadata
    store, and a throw-away vector store. It instantiates
    :class:`memgentic.processing.pipeline.IngestionPipeline` against them
    so the harness ingests through exactly the same code path as the
    production CLI / daemon / MCP server.

    Usage sketch::

        harness = BenchmarkHarness(profile="raw",
                                   embedder="qwen3-0.6b",
                                   backend="sqlite-vec")
        await harness.setup()
        try:
            for session in loader.iter_sessions(dataset_path):
                await harness.ingest_session(session)
            records = await harness.evaluate(queries, scorer=my_scorer)
            harness.write_jsonl(records, out_path)
        finally:
            await harness.teardown()

    Runners that match the §6 pseudocode call ``ingest_session`` and
    ``search`` directly instead of ``evaluate``; both patterns are
    supported.
    """

    def __init__(
        self,
        profile: str = "raw",
        embedder: str = "qwen3-0.6b",
        backend: str = "sqlite-vec",
        *,
        seed: int = DEFAULT_SEED,
        settings_override: MemgenticSettings | None = None,
        enable_llm: bool | None = None,
    ) -> None:
        """Construct a harness without touching disk.

        Args:
            profile: Capture profile tag (``"raw"``, ``"enriched"``,
                ``"dual"``). The tag is recorded in result files and
                passed through to
                :meth:`memgentic.processing.pipeline.IngestionPipeline.ingest_conversation`
                via ``capture_profile`` so ingestion uses exactly the
                same code path as production.
            embedder: Embedder label. The default ``"qwen3-0.6b"`` maps to
                the production Ollama model. Custom values flow through
                unchanged for experimentation.
            backend: Vector backend label. ``"sqlite-vec"`` selects the
                zero-config sqlite-vec backend; ``"qdrant-local"`` selects
                file-based Qdrant; ``"qdrant"`` selects a remote Qdrant
                server (reads URL from the settings override).
            seed: Seed used for any sampling inside the harness. Defaults
                to 42 per the reproducibility contract.
            settings_override: Pre-built settings object. When provided,
                the harness uses it as-is — useful for wiring a Qdrant
                server URL or supplying a real Ollama config in Docker.
        """
        self.profile: CaptureProfile = self._normalise_profile(profile)
        self.embedder_label = embedder
        self.backend_label = backend
        self.seed = seed
        self._settings_override = settings_override

        # Plan 12 PR-C: LLM enrichment flag.
        # Default behavior preserves backward compatibility:
        #   - profile=raw → enable_llm=False (no LLM, fast, deterministic)
        #   - profile=enriched/dual → enable_llm=True (Gemma/Qwen via Ollama
        #     for topic/entity extraction, classification, summarization)
        # Explicit override wins. The harness used to hard-code llm_client=None
        # regardless of profile, which silently broke the enriched/dual paths
        # in benchmark runs (see pipeline.intelligence_heuristic_only logs).
        if enable_llm is None:
            self.enable_llm = self.profile in ("enriched", "dual")
        else:
            self.enable_llm = enable_llm

        self._tmp_root: Path | None = None
        self._settings: MemgenticSettings | None = None
        self._metadata: MetadataStore | None = None
        self._vectors: VectorStore | None = None
        self._embedder: Embedder | None = None
        self._llm: LLMClient | None = None
        self._pipeline: IngestionPipeline | None = None

        random.seed(self.seed)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def setup(self) -> None:
        """Create temp dirs and initialise the Memgentic stack.

        Kept async because all downstream components are async; a
        synchronous wrapper can be added later if a runner wants it.
        """
        if self._tmp_root is not None:
            raise RuntimeError("BenchmarkHarness.setup() called twice")

        self._tmp_root = Path(tempfile.mkdtemp(prefix="memgentic-bench-"))
        (self._tmp_root / "data").mkdir()
        (self._tmp_root / "cache").mkdir()

        self._settings = self._build_settings(self._tmp_root)

        self._metadata = MetadataStore(self._settings.data_dir / "memgentic.db")
        await self._metadata.initialize()

        self._vectors = VectorStore(self._settings)
        await self._vectors.initialize(metadata_store=self._metadata)

        self._embedder = Embedder(self._settings)

        # Plan 12 PR-C: build LLM client when the harness was asked for
        # LLM-aware ingestion. Default flag derives from profile:
        # raw=disabled, enriched/dual=enabled. The pipeline degrades to
        # heuristic classification when the LLM client is None or the
        # underlying provider is unavailable, so this is safe to enable
        # by default for enriched/dual.
        if self.enable_llm:
            self._llm = LLMClient(self._settings)
            if not self._llm.available:
                # Provider not configured (no Ollama, no API key). Fall back
                # to heuristic-only — same behavior as the pre-PR-C skeleton
                # but now signaled as a skipped capability, not a silent miss.
                self._llm = None
        else:
            self._llm = None

        self._pipeline = IngestionPipeline(
            settings=self._settings,
            metadata_store=self._metadata,
            vector_store=self._vectors,
            embedder=self._embedder,
            llm_client=self._llm,
            graph=None,
        )

    async def teardown(self) -> None:
        """Close stores and wipe the temp dir. Idempotent."""
        if self._metadata is not None:
            await self._metadata.close()
            self._metadata = None
        if self._vectors is not None:
            await self._vectors.close()
            self._vectors = None
        if self._embedder is not None:
            with contextlib.suppress(Exception):  # pragma: no cover — defensive
                await self._embedder.close()
        self._embedder = None
        self._pipeline = None

        if self._tmp_root is not None and self._tmp_root.exists():
            shutil.rmtree(self._tmp_root, ignore_errors=True)
        self._tmp_root = None
        self._settings = None

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    async def ingest_session(self, session: CorpusSession) -> None:
        """Ingest a single session via :class:`IngestionPipeline`.

        The §6 LongMemEval runner calls this in a loop; other runners
        can call :meth:`ingest_corpus` to pass an iterable.

        The harness's normalised ``profile`` flows through as
        ``capture_profile`` so the pipeline routes to the configured
        raw / enriched / dual code path without any runner branching.
        """
        pipeline = self._require_pipeline()
        await pipeline.ingest_conversation(
            chunks=session.chunks,
            platform=session.platform,
            session_id=session.session_id,
            session_title=session.session_title,
            capture_method=CaptureMethod.MANUAL_IMPORT,
            capture_profile=self.profile,
        )

    async def ingest_corpus(
        self,
        sessions: Iterable[CorpusSession],
    ) -> int:
        """Ingest every session yielded by a corpus loader.

        Returns the number of sessions ingested (not the number of
        memories, which the pipeline decides).
        """
        count = 0
        for session in sessions:
            await self.ingest_session(session)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Search / evaluate
    # ------------------------------------------------------------------
    async def search(self, text: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Embed ``text`` and return the top-``n_results`` vector hits.

        Results are raw dicts with ``id``, ``score`` and ``payload``
        (which carries ``session_id``, ``content_type``, ``platform``
        and so on). Runners read whatever field they need for scoring;
        the harness stays agnostic.
        """
        embedder = self._require(self._embedder, "embedder")
        vectors = self._require(self._vectors, "vector store")
        embedding = await embedder.embed(text)
        return await vectors.search(embedding, limit=n_results)

    async def evaluate(
        self,
        queries: Sequence[BenchmarkQuery],
        scorer: ScorerFn,
        *,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Run every query through :meth:`search` and score with ``scorer``.

        ``scorer`` receives the query plus the raw hit list and returns
        a dict of per-question metrics. The harness prepends the common
        fields (``question_id``, ``question``, ``gold``, ``category``)
        so result JSONL files are self-describing regardless of runner.
        """
        records: list[dict[str, Any]] = []
        for query in queries:
            hits = await self.search(query.text, n_results=k)
            scored = dict(scorer(query, hits))
            records.append(
                {
                    "question_id": query.id,
                    "question": query.text,
                    "gold": sorted(query.gold),
                    "category": query.category,
                    **scored,
                }
            )
        return records

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    @staticmethod
    def write_jsonl(records: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
        """Write ``records`` as newline-delimited JSON, one object per line.

        Creates parent directories as needed. Returns the resolved path
        so callers can log it.
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(dict(record), default=str))
                fh.write("\n")
        return out_path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_settings(self, tmp_root: Path) -> MemgenticSettings:
        if self._settings_override is not None:
            return self._settings_override

        backend = {
            "sqlite-vec": StorageBackend.SQLITE_VEC,
            "sqlite_vec": StorageBackend.SQLITE_VEC,
            "local": StorageBackend.LOCAL,
            "qdrant-local": StorageBackend.LOCAL,
            "qdrant": StorageBackend.QDRANT,
        }.get(self.backend_label, StorageBackend.SQLITE_VEC)

        # Plan 12 PR-C: when LLM enrichment is enabled, flip the toggles
        # the IngestionPipeline reads to decide whether to call the LLM
        # for classification / extraction / summarization. The actual
        # provider (Ollama local or cloud API) comes from environment
        # variables (GOOGLE_API_KEY for Gemini, MEMGENTIC_LOCAL_LLM_MODEL
        # for the Ollama tag, etc.) — see memgentic.config for the full set.
        return MemgenticSettings(
            data_dir=tmp_root / "data",
            storage_backend=backend,
            collection_name="memgentic_bench",
            embedding_dimensions=768,
            enable_credential_scrubbing=True,
            embedding_provider=EmbeddingProvider.OLLAMA,
            enable_llm_processing=self.enable_llm,
            enable_local_llm=self.enable_llm,
        )

    @staticmethod
    def _normalise_profile(profile: str) -> CaptureProfile:
        resolved = _PROFILE_ALIASES.get(profile, profile)
        if resolved not in _KNOWN_PROFILES:
            raise ValueError(
                f"Unknown profile {profile!r}. Expected one of {sorted(_KNOWN_PROFILES)}."
            )
        # The membership check above constrains `resolved` to the three literal
        # values, but pyright can't narrow through ``in _KNOWN_PROFILES`` — the
        # cast here encodes the invariant for the type checker.
        from typing import cast

        return cast(CaptureProfile, resolved)

    def _require_pipeline(self) -> IngestionPipeline:
        if self._pipeline is None:
            raise RuntimeError(
                "BenchmarkHarness not initialised — call `await harness.setup()` first"
            )
        return self._pipeline

    @staticmethod
    def _require(value: Any, name: str) -> Any:
        if value is None:
            raise RuntimeError(
                f"BenchmarkHarness.{name} not initialised — call `await harness.setup()` first"
            )
        return value
