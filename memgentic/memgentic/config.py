"""Memgentic configuration — Pydantic Settings with .env support."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

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


class MemgenticSettings(BaseSettings):
    """Core settings for Memgentic."""

    model_config = SettingsConfigDict(
        env_prefix="MEMGENTIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage ---
    data_dir: Path = Field(
        default=Path.home() / ".memgentic" / "data",
        description="Root directory for all Memgentic data (SQLite, Qdrant files, graph)",
    )
    storage_backend: StorageBackend = Field(
        default=StorageBackend.SQLITE_VEC,
        description=(
            "Vector storage backend: 'sqlite_vec' (default, zero-config, multi-process safe), "
            "'local' (file-based Qdrant, single-process), or 'qdrant' (Qdrant server)"
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
        description="Embedding provider: 'ollama' (local) or 'openai'",
    )
    embedding_model: str = Field(
        default="qwen3-embedding:0.6b",
        description="Embedding model name (Ollama model name or OpenAI model ID)",
    )
    embedding_dimensions: int = Field(
        default=768,
        description="Embedding vector dimensions (768 via MRL truncation)",
    )
    ollama_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (when using openai embeddings)",
    )
    embedding_batch_size: int = Field(
        default=8,
        description="Max concurrent embedding requests (lower for CPU, higher for GPU)",
    )
    import_concurrency: int = Field(
        default=4,
        description="Number of files to process concurrently during import",
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
    enable_corroboration: bool = Field(
        default=True,
        description="Boost confidence when multiple platforms confirm the same fact",
    )
    corroboration_threshold: float = Field(
        default=0.85,
        description="Minimum similarity score to consider as corroboration (0-1)",
    )
    corroboration_boost: float = Field(
        default=0.1,
        description="Confidence boost when a fact is corroborated (+0.1, capped at 1.0)",
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

    # --- Context file auto-update (Phase 3.A) ---
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

    # --- Observability (Phase 3.B) ---
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
