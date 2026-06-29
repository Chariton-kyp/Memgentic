"""Memgentic configuration — Pydantic Settings with .env support."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackend(StrEnum):
    """Vector storage backend."""

    LOCAL = "local"  # Qdrant file-based (no server)
    QDRANT = "qdrant"  # Qdrant server (Docker/Cloud)
    SQLITE_VEC = "sqlite_vec"  # sqlite-vec extension co-located with metadata DB


class EmbeddingProvider(StrEnum):
    """Embedding model provider."""

    OLLAMA = "ollama"  # Local Ollama (default)
    OPENAI = "openai"  # OpenAI API
    OPENAI_COMPAT = "openai_compat"  # OpenAI-compatible server (llama.cpp, vLLM, LM Studio, TEI)


class MemgenticSettings(BaseSettings):
    """Core settings for Memgentic."""

    model_config = SettingsConfigDict(
        env_prefix="MEMGENTIC_",
        # A user-wide ``~/.memgentic/.env`` is read first as the base config, so
        # a single file pins the embedding model / vector backend for EVERY
        # tool's MCP ``serve`` regardless of the working directory it is spawned
        # in (MCP clients launch ``serve`` from arbitrary CWDs and do not pass
        # env through). A project-local ``.env`` in the CWD overrides it, and
        # real ``MEMGENTIC_*`` environment variables override both.
        env_file=(str(Path.home() / ".memgentic" / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage ---
    data_dir: Path = Field(
        default=Path.home() / ".memgentic" / "data",
        description="Root directory for all Memgentic data (SQLite, Qdrant files, graph)",
    )
    storage_backend: StorageBackend = Field(
        default=StorageBackend.QDRANT,
        description=(
            "Vector storage backend: 'qdrant' (default, Qdrant server — run via Docker or "
            "Qdrant Cloud), 'sqlite_vec' (zero-config, multi-process safe, no server), "
            "or 'local' (file-based Qdrant, single-process). "
            "BREAKING CHANGE from v0.7: default changed from 'sqlite_vec' to 'qdrant'. "
            "Set MEMGENTIC_STORAGE_BACKEND=sqlite_vec to keep the previous behaviour."
        ),
    )
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant server URL (only used when storage_backend='qdrant')",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        description="Qdrant API key (for Qdrant Cloud)",
    )
    collection_name: str = Field(
        default="memgentic_memories",
        description="Qdrant collection name",
    )

    # --- Embeddings ---
    embedding_provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.OLLAMA,
        description=(
            "Embedding provider: 'ollama' (local Ollama, default), 'openai' "
            "(api.openai.com), or 'openai_compat' (any OpenAI-compatible /v1 "
            "endpoint — llama.cpp's llama-server, vLLM, LM Studio, TEI — set "
            "embedding_base_url). Override via MEMGENTIC_EMBEDDING_PROVIDER."
        ),
    )
    embedding_model: str = Field(
        default="qwen3-embedding:4b",
        description=(
            "Embedding model name (Ollama model name or OpenAI model ID). "
            "Override via MEMGENTIC_EMBEDDING_MODEL. Default 'qwen3-embedding:4b' "
            "(Ollama q4_K_M, ~2.5 GB) MRL-truncated to 1024 dims (~+5 MTEB vs 0.6b). "
            "Light fallback: 'qwen3-embedding:0.6b' (639 MB). "
            "Switching the model OR the dimensions changes the vector space and "
            "REQUIRES a full re-embed of the store (`memgentic re-embed`) — "
            "old and new vectors are not comparable."
        ),
    )
    embedding_dimensions: int = Field(
        default=1024,
        description=(
            "Embedding vector dimensions via Matryoshka (MRL) truncation. "
            "Override via MEMGENTIC_EMBEDDING_DIMENSIONS. 1024 pairs with the "
            "default qwen3-embedding:4b (natively 2560-dim; Ollama applies "
            "server-side MRL truncation via the 'dimensions' request parameter). "
            "Use 768 with the light qwen3-embedding:0.6b fallback. "
            "MUST match the model the store was embedded with — "
            "changing it requires a full re-embed (`memgentic re-embed`)."
        ),
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (when using openai embeddings)",
    )
    embedding_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of an OpenAI-compatible /v1/embeddings endpoint, used when "
            "embedding_provider='openai_compat'. Lets you serve embeddings from any "
            "fast local engine — llama.cpp's llama-server, vLLM, LM Studio, "
            "Text-Embeddings-Inference — instead of Ollama. Include the version path "
            "like the OpenAI SDK base_url (e.g. http://localhost:8082/v1); "
            "'/embeddings' is appended. Override via MEMGENTIC_EMBEDDING_BASE_URL."
        ),
    )
    embedding_api_key: str | None = Field(
        default=None,
        description=(
            "Optional bearer token for the openai_compat embedding endpoint. Most "
            "local servers need none; sent as 'Authorization: Bearer <key>' only when "
            "set. Override via MEMGENTIC_EMBEDDING_API_KEY."
        ),
    )
    embedding_batch_size: int = Field(
        default=8,
        description="Max concurrent embedding requests (lower for CPU, higher for GPU)",
    )
    import_concurrency: int = Field(
        default=4,
        description="Number of files to process concurrently during import",
    )

    # --- Reranker (optional cross-encoder, served by llama-server) ---
    # Absolute relevance gate applied AFTER fusion. OFF by default so installs
    # without a llama-server are unaffected; when on but the server is
    # unreachable, recall falls back to the fused order (never breaks).
    # Ollama CANNOT serve rerankers — run llama.cpp's llama-server:
    #   llama-server -m Qwen3-Reranker-0.6B-Q4_K_M.gguf \
    #       --reranking --pooling rank --embedding --port 8081
    # Use the verified-working Voodisss GGUFs. See docs/reranker-setup.md.
    enable_reranker: bool = Field(
        default=False,
        description=(
            "Enable cross-encoder reranking of fused recall candidates. OFF by "
            "default. Requires a reachable llama-server at reranker_url; when "
            "unreachable, recall gracefully falls back to the fused order. "
            "Override via MEMGENTIC_ENABLE_RERANKER."
        ),
    )
    reranker_url: str = Field(
        default="http://localhost:8081",
        description=(
            "Base URL of the llama-server exposing /v1/rerank (started with "
            "--reranking --pooling rank --embedding). Override via "
            "MEMGENTIC_RERANKER_URL."
        ),
    )
    reranker_model: str = Field(
        default="Qwen3-Reranker-0.6B-Q4_K_M",
        description=(
            "Informational reranker model name (sent in the request body; most "
            "local servers ignore it). Default = Qwen3-Reranker-0.6B-Q4_K_M "
            "(Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp, ~396 MB, verified "
            "working GGUF with intact classifier head). Opt into the 4B variant "
            "('Qwen3-Reranker-4B-Q4_K_M') for maximum quality. "
            "Override via MEMGENTIC_RERANKER_MODEL."
        ),
    )
    reranker_top_k: int = Field(
        default=20,
        ge=1,
        description=(
            "How many top fused candidates to send to the reranker. The rerank "
            "window: a larger value reorders more of the pool at the cost of "
            "latency. Override via MEMGENTIC_RERANKER_TOP_K."
        ),
    )
    reranker_min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "ABSOLUTE floor on the rerank score [0,1]. Candidates scoring below "
            "this are DROPPED — the 'drop weak results' gate that the relative "
            "min-max relevance floor cannot provide. Default 0.0 = no floor "
            "(rerank only reorders). Raise (e.g. 0.3) to prune off-topic hits. "
            "Override via MEMGENTIC_RERANKER_MIN_SCORE."
        ),
    )
    reranker_timeout_s: float = Field(
        default=2.0,
        gt=0.0,
        description=(
            "Per-request timeout (seconds) for the llama-server rerank call. "
            "Kept short so a slow/wedged server cannot stall recall; on timeout "
            "recall falls back to the fused order. Override via "
            "MEMGENTIC_RERANKER_TIMEOUT_S."
        ),
    )

    # --- LLM (for summarization) ---
    summarization_model: str = Field(
        default="gemini-2.0-flash-lite",
        description="LLM model for conversation summarization and extraction (API)",
    )
    google_api_key: str | None = Field(
        default=None,
        description="Google AI API key for Gemini models",
    )
    local_llm_model: str = Field(
        default="gemma4:e4b",
        description="Local LLM model via Ollama for classification/extraction (no API key needed)",
    )
    enable_local_llm: bool = Field(
        default=True,
        description="Try local LLM via Ollama before falling back to heuristics",
    )
    ollama_num_threads: int = Field(
        default=0,
        description="CPU threads for Ollama inference (0=auto, set to vCPU count - 2 for servers)",
    )
    ollama_num_ctx: int = Field(
        default=2048,
        description=(
            "Context window for the Ollama LLM (KV cache size, in tokens). "
            "Larger windows allow longer prompts but quadratically increase VRAM. "
            "Default 2048 keeps a 4-7B model running on a 6-8 GiB GPU; raise to "
            "4096 if your VRAM allows and your prompts run long."
        ),
    )
    ollama_num_predict: int = Field(
        default=512,
        description=(
            "Maximum tokens an Ollama generation can produce. Memgentic's structured "
            "outputs (classification / extraction JSON) need ≤ 200 tokens; 512 is a "
            "safe ceiling. Lower if you see runaway outputs; raise for free-form summaries."
        ),
    )

    # --- OpenAI-compatible endpoint (LM Studio / vLLM / llama.cpp llama-server) ---
    # Use when you need a model architecture Ollama doesn't support yet (e.g. an
    # Unsloth gemma4 GGUF through llama.cpp tip-of-tree). When base_url is set,
    # this provider takes priority over the local Ollama tier.
    openai_compat_base_url: str | None = Field(
        default=None,
        description=(
            "OpenAI-compatible chat-completions endpoint (e.g. http://localhost:8080/v1 "
            "for llama.cpp llama-server). Leave unset to disable this tier."
        ),
    )
    openai_compat_model: str = Field(
        default="local-model",
        description=(
            "Model name to send in the chat-completions request. Most local servers "
            "ignore this and use whatever they loaded; cloud-compat services need the real id."
        ),
    )
    openai_compat_api_key: str = Field(
        default="not-needed",
        description=(
            "API key for the OpenAI-compatible endpoint. Local servers don't validate "
            "it — any non-empty string works. Use a real key for hosted services."
        ),
    )

    # --- Security ---
    enable_credential_scrubbing: bool = Field(
        default=True,
        description="Scrub API keys, tokens, passwords from memories before storage",
    )

    # --- Intelligence ---
    enable_llm_processing: bool = Field(
        default=True,
        description="Enable LLM-powered classification, extraction, summarization",
    )
    memory_half_life_days: int = Field(
        default=90,
        description="Half-life in days for memory importance decay",
    )
    recall_min_relevance: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description=(
            "Post-rank relevance floor for recall (0-1). Results whose "
            "normalized relevance (hybrid) or cosine similarity (basic) is "
            "below this are dropped. Conservative default 0.15 trims clear "
            "noise without hiding legitimate hits (observed on-topic cosines "
            "run 0.2-0.5). Callers may lower it to widen recall."
        ),
    )
    enable_recall_feature_boost: bool = Field(
        default=True,
        description=(
            "Apply query-feature boosts (exact quoted phrases, proper-noun "
            "mentions, temporal proximity) during hybrid recall ranking. "
            "Enabled by default; disable to fall back to plain fused ranking."
        ),
    )
    recall_scope: Literal["project", "global"] = Field(
        default="project",
        description=(
            "Default scope for memory recall. 'project' (default) scopes recall "
            "to the current project/repository, resolved for the MCP server in "
            "priority order: explicit project arg → configure_session project → "
            "MEMGENTIC_PROJECT env → the subprocess cwd's git-repo / directory. "
            "'global' searches every project (the pre-W3 behaviour). Override "
            "per install or via the MEMGENTIC_RECALL_SCOPE env var. Pass "
            "project='*' (or 'all'/'global') on a single call to force global "
            "regardless of this setting."
        ),
    )
    recall_scope_strict: bool = Field(
        default=False,
        description=(
            "How project scope behaves when the current project yields nothing. "
            "False (default) = project-first with a graceful global fallback: an "
            "auto-scoped recall that returns fewer than the requested results "
            "retries globally and merges, so recall is never worse than global. "
            "True = project-only: auto-scoped recall never falls back, so a "
            "project with no matching memories returns nothing. Override via the "
            "MEMGENTIC_RECALL_SCOPE_STRICT env var."
        ),
    )
    enable_write_time_dedup: bool = Field(
        default=True,
        description=(
            "Skip near-duplicate memories at ingestion time. Enabled by default "
            "for better recall quality; adds one vector lookup per memory. "
            "Disable for maximum ingestion throughput."
        ),
    )
    enable_fact_distillation: bool = Field(
        default=True,
        description=(
            "Run fact-distillation node in the intelligence pipeline. Enabled by "
            "default for higher-quality memories; falls back to heuristics when "
            "no LLM is configured. Disable to save one LLM call per chunk."
        ),
    )
    enable_value_gate: bool = Field(
        default=True,
        description=(
            "Drop clearly-worthless memories at ingestion using the distillation "
            "value signal (is_valuable=False AND value_score below "
            "value_gate_min_score). Conservative: never drops when the signal is "
            "absent. Disable to keep every enriched chunk regardless of value."
        ),
    )
    value_gate_min_score: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Distillation value_score below which a chunk explicitly marked "
            "is_valuable=False is dropped by the value gate. Lower = more "
            "conservative (drops fewer)."
        ),
    )
    max_memory_content_chars: int = Field(
        default=65_536,
        gt=0,
        description=(
            "Hard cap on a single memory's content length (characters). Anything "
            "longer is truncated with a marker before embedding/storage so one "
            "pathological turn (e.g. a 765 KB file-read dump) cannot bloat the "
            "embedder context window or an SQLite row."
        ),
    )
    enable_corroboration: bool = Field(
        default=True,
        description="Boost confidence when multiple platforms confirm the same fact",
    )
    default_capture_profile: Literal["raw", "enriched", "dual"] = Field(
        default="enriched",
        description=(
            "Default capture profile for new memories when the ingestion call "
            "does not specify one. 'raw' stores verbatim chunks with no LLM "
            "enrichment. 'enriched' (default) runs the full intelligence "
            "pipeline. 'dual' writes both rows paired via dual_sibling_id "
            "(2x storage). Can also be overridden at runtime; the runtime "
            "value is persisted in the ``runtime_settings`` table."
        ),
    )
    corroboration_threshold: float = Field(
        default=0.85,
        description="Minimum similarity score to consider as corroboration (0-1)",
    )
    corroboration_boost: float = Field(
        default=0.1,
        description="Confidence boost when a fact is corroborated (+0.1, capped at 1.0)",
    )

    # --- Dream (auto-consolidation) ---
    # Two-tier model routing: cheap default LLMClient for the Gather Signal
    # phase, stronger Anthropic-hosted Sonnet for the Consolidate phase that
    # actually proposes patches. Falls back to the default LLMClient when
    # ``anthropic_api_key`` is unset.
    dream_consolidate_model: str = Field(
        default="claude-sonnet-4-6",
        description=(
            "Model used by the dream Consolidate phase (proposes patches). "
            "Names starting with 'claude-' route through Anthropic when "
            "ANTHROPIC_API_KEY is set — typical choices: claude-sonnet-4-6 "
            "(default, balanced), claude-opus-4-7 (best quality), "
            "claude-haiku-4-5 (cheapest). Set to an empty string or any "
            "non-claude name to fall back to the default LLMClient "
            "(Gemini → OpenAI-compat → Ollama → heuristics)."
        ),
    )
    dream_signal_model: str = Field(
        default="claude-haiku-4-5",
        description=(
            "Model used by the dream Gather Signal phase (bulk-scan over "
            "session transcripts). Defaults to claude-haiku-4-5 — cheap and "
            "fast, suited to high-volume passes. Same routing rules as "
            "dream_consolidate_model: claude-* via Anthropic, anything else "
            "(empty string, 'local', etc.) falls back to the default "
            "LLMClient."
        ),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        description=(
            "Anthropic API key (used by the dream Consolidate phase only — "
            "core ingestion uses Gemini/local LLMs)."
        ),
    )
    dream_default_session_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Default sessions per dream when --limit-sessions is not given.",
    )

    # --- Retention / self-cleaning (GC) ---
    hard_delete_archived_after_days: int = Field(
        default=30,
        ge=0,
        description=(
            "Grace period in days before archived/superseded memories become "
            "eligible for permanent hard-deletion by the retention GC sweep "
            "(`memgentic gc`). 0 disables GC entirely — memories are still "
            "archived but never hard-deleted. Pinned and mcp_tool-captured "
            "memories are NEVER hard-deleted regardless of this setting."
        ),
    )
    gc_interval_seconds: int = Field(
        default=0,
        ge=0,
        description=(
            "How often the daemon runs the retention GC sweep (seconds). 0 "
            "(default) disables the in-daemon loop — run `memgentic gc --apply` "
            "manually or via cron instead. Only takes effect when "
            "hard_delete_archived_after_days > 0."
        ),
    )

    # --- Daemon ---
    watch_interval: int = Field(
        default=30,
        description="File watcher check interval in seconds",
    )
    idle_threshold: int = Field(
        default=300,
        description="Seconds of inactivity before a conversation is considered finished",
    )
    skill_sync_interval: int = Field(
        default=60,
        description=(
            "How often the daemon re-syncs auto-distributable skills to each "
            "tool's native path (seconds). Set to 0 to disable."
        ),
    )

    # --- Rate Limiting ---
    rate_limit_default: int = Field(
        default=60,
        description="Default rate limit per minute for API endpoints",
    )
    rate_limit_search: int = Field(
        default=30,
        description="Rate limit per minute for search endpoints",
    )
    rate_limit_import: int = Field(
        default=10,
        description="Rate limit per minute for import endpoints",
    )

    # --- API Authentication ---
    api_key: str | None = Field(
        default=None,
        description="API key for REST API authentication (set MEMGENTIC_API_KEY env var)",
    )

    # --- Hooks ---
    hook_briefing_hours: int = Field(
        default=48,
        description="Lookback window (hours) for SessionStart hook briefing",
    )
    hook_briefing_limit: int = Field(
        default=5,
        description="Max memories included in SessionStart hook briefing",
    )

    # --- Context file auto-update ---
    enable_context_file_auto_update: bool = Field(
        default=True,
        description="Daemon auto-updates .memgentic-context.md for non-MCP tools",
    )
    context_file_path: str = Field(
        default=".memgentic-context.md",
        description="Path to the standalone context file",
    )
    context_file_hours: int = Field(
        default=72,
        description="Hours of history to include in the auto-generated context file",
    )
    context_file_interval_seconds: int = Field(
        default=300,
        description="How often the daemon checks whether to regenerate the context file",
    )

    # --- Observability ---
    enable_observability: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing/metrics (requires [observability] extras)",
    )
    otlp_endpoint: str | None = Field(
        default=None,
        description="OTLP HTTP endpoint (e.g. http://localhost:4318)",
    )

    # --- MCP Server ---
    mcp_transport: str = Field(
        default="stdio",
        description="MCP transport: 'stdio' (local) or 'streamable_http' (remote)",
    )
    mcp_port: int = Field(
        default=8200,
        description="MCP server port (only used with streamable_http transport)",
    )

    @property
    def sqlite_path(self) -> Path:
        """SQLite database file path."""
        return self.data_dir / "memgentic.db"

    @property
    def qdrant_local_path(self) -> Path:
        """Qdrant local storage path (file-based mode)."""
        return self.data_dir / "qdrant"

    @property
    def graph_path(self) -> Path:
        """Knowledge graph serialization path."""
        return self.data_dir / "graph.json"


# Singleton settings instance
settings = MemgenticSettings()
