"""Memgentic data models — source-aware memory with rich metadata."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Per-memory capture profile. ``raw`` = verbatim chunk, no LLM enrichment.
# ``enriched`` = current default (topics/entities/LLM importance).
# ``dual`` = both, paired via ``Memory.dual_sibling_id``.
CaptureProfile = Literal["raw", "enriched", "dual"]
CAPTURE_PROFILES: tuple[CaptureProfile, ...] = ("raw", "enriched", "dual")


class ContentType(StrEnum):
    """Type of knowledge stored in a memory."""

    CONVERSATION_SUMMARY = "conversation_summary"
    DECISION = "decision"
    CODE_SNIPPET = "code_snippet"
    FACT = "fact"
    PREFERENCE = "preference"
    LEARNING = "learning"
    ACTION_ITEM = "action_item"
    ENTITY_RELATIONSHIP = "entity_relationship"
    RAW_EXCHANGE = "raw_exchange"


class CaptureMethod(StrEnum):
    """How the memory was captured."""

    AUTO_DAEMON = "auto_daemon"  # Automatic file watcher
    MCP_TOOL = "mcp_tool"  # Via MCP remember tool
    MANUAL_IMPORT = "manual_import"  # CLI import command
    BROWSER_EXTENSION = "browser_extension"  # Future: browser ext
    JSON_IMPORT = "json_import"  # Bulk JSON import
    HOOK = "hook"  # Shell/CLI hook
    MANUAL_UPLOAD = "manual_upload"  # Manual file/text upload via dashboard
    URL_IMPORT = "url_import"  # Imported from a URL


class Platform(StrEnum):
    """Source platform for the memory."""

    CLAUDE_CODE = "claude_code"
    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_WEB = "claude_web"
    CHATGPT = "chatgpt"
    GEMINI_CLI = "gemini_cli"
    GEMINI_WEB = "gemini_web"
    ANTIGRAVITY = "antigravity"
    CODEX_CLI = "codex_cli"
    COPILOT_CLI = "copilot_cli"
    COPILOT_VSCODE = "copilot_vscode"
    AIDER = "aider"
    CURSOR = "cursor"
    PERPLEXITY = "perplexity"
    CUSTOM = "custom"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class MemoryStatus(StrEnum):
    """Lifecycle status of a memory."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class SourceMetadata(BaseModel):
    """Provenance metadata — where this memory came from."""

    model_config = ConfigDict(str_strip_whitespace=True)

    platform: Platform = Field(
        description="Source platform (claude_code, chatgpt, gemini_cli, etc.)"
    )
    platform_version: str | None = Field(
        default=None,
        description="Model or tool version (e.g., 'claude-sonnet-4', 'gpt-4o')",
    )
    session_id: str | None = Field(
        default=None,
        description="Original conversation/session ID from the source platform",
    )
    session_title: str | None = Field(
        default=None,
        description="Conversation title or summary from the source",
    )
    capture_method: CaptureMethod = Field(
        default=CaptureMethod.MCP_TOOL,
        description="How this memory was captured",
    )
    original_timestamp: datetime | None = Field(
        default=None,
        description="When the original conversation happened",
    )
    file_path: str | None = Field(
        default=None,
        description="Source file path (for daemon-captured conversations)",
    )


class Memory(BaseModel):
    """A single unit of knowledge in Memgentic — the core data model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # Identity
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique memory identifier",
    )
    # Reserved for future cloud multi-user support
    user_id: str = Field(default="", description="Owner user ID")

    # Content
    content: str = Field(
        description="The actual memory/knowledge content",
        min_length=1,
    )
    content_type: ContentType = Field(
        default=ContentType.FACT,
        description="What kind of knowledge this represents",
    )

    # Source provenance
    source: SourceMetadata = Field(
        description="Where this memory came from — full provenance",
    )

    # Knowledge metadata
    topics: list[str] = Field(
        default_factory=list,
        description="Extracted topics/tags",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="People, projects, technologies mentioned",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="How reliable/certain this memory is",
    )
    supersedes: list[str] = Field(
        default_factory=list,
        description="IDs of memories this one replaces (contradiction resolution)",
    )
    corroborated_by: list[str] = Field(
        default_factory=list,
        description="Platforms that have confirmed this memory (cross-source validation)",
    )

    # Lifecycle
    status: MemoryStatus = Field(
        default=MemoryStatus.ACTIVE,
        description="Current lifecycle status",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this memory was ingested into Memgentic",
    )
    last_accessed: datetime | None = Field(
        default=None,
        description="Last time this memory was retrieved",
    )
    access_count: int = Field(
        default=0,
        ge=0,
        description="How many times this memory has been retrieved",
    )
    importance_score: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="Importance score — decays over time, boosted by access",
    )

    # Pin support
    is_pinned: bool = Field(
        default=False,
        description="Whether this memory is pinned for quick access",
    )
    pinned_at: datetime | None = Field(
        default=None,
        description="When this memory was pinned",
    )

    # Capture profile provenance — which ingestion path produced this row
    capture_profile: CaptureProfile = Field(
        default="enriched",
        description=(
            "How this memory was captured: 'raw' (verbatim, no LLM), "
            "'enriched' (current default, LLM-classified), or 'dual' "
            "(paired with a sibling of the opposite profile)."
        ),
    )
    dual_sibling_id: str | None = Field(
        default=None,
        description=(
            "For dual-profile memories: the ID of the paired sibling row "
            "(raw <-> enriched). NULL for standalone raw or enriched memories."
        ),
    )


class SessionConfig(BaseModel):
    """Session-level defaults for source filtering."""

    model_config = ConfigDict(str_strip_whitespace=True)

    include_sources: list[Platform] | None = Field(
        default=None,
        description="Only include memories from these platforms (None = all)",
    )
    exclude_sources: list[Platform] | None = Field(
        default=None,
        description="Exclude memories from these platforms",
    )
    include_content_types: list[ContentType] | None = Field(
        default=None,
        description="Only include these content types (None = all)",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for retrieval",
    )


class Collection(BaseModel):
    """A user-defined collection for organizing memories."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique collection identifier",
    )
    user_id: str = Field(default="", description="Owner user ID")
    name: str = Field(description="Collection name", min_length=1, max_length=200)
    description: str = Field(default="", description="Optional description")
    color: str = Field(default="#6B7280", description="Display color (hex)")
    icon: str = Field(default="folder", description="Display icon name")
    position: float = Field(default=0, description="Sort position (fractional indexing)")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this collection was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this collection was last updated",
    )


class UploadStatus(StrEnum):
    """Status of a file upload."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Upload(BaseModel):
    """Tracks a file or URL upload and its processing status."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique upload identifier",
    )
    user_id: str = Field(default="", description="Owner user ID")
    memory_id: str | None = Field(
        default=None,
        description="ID of the memory created from this upload (once processed)",
    )
    filename: str = Field(description="Original filename")
    mime_type: str = Field(description="MIME type of the uploaded file")
    file_size: int = Field(default=0, ge=0, description="File size in bytes")
    upload_source: str = Field(default="manual", description="Upload source (manual, url)")
    original_url: str | None = Field(default=None, description="Source URL if imported from web")
    status: UploadStatus = Field(
        default=UploadStatus.PROCESSING,
        description="Processing status",
    )
    error_message: str | None = Field(
        default=None, description="Error message if processing failed"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this upload was initiated",
    )


class Skill(BaseModel):
    """A reusable skill that can be distributed to AI coding tools."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique skill identifier",
    )
    user_id: str = Field(default="", description="Owner user ID")
    name: str = Field(
        description="Skill name (kebab-case, matches directory name)",
        min_length=1,
        max_length=200,
    )
    description: str = Field(default="", description="Short description (1-1024 chars)")
    content: str = Field(default="", description="SKILL.md body content")
    config: dict = Field(default_factory=dict, description="Skill configuration (JSON)")
    source: str = Field(
        default="manual",
        description="How the skill was created: manual, imported, auto_extracted, cloned",
    )
    source_url: str | None = Field(
        default=None,
        description="GitHub URL, ClawHub URL, etc.",
    )
    version: str = Field(default="1.0.0", description="Semantic version")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    distribute_to: list[str] = Field(
        default_factory=lambda: ["claude", "codex", "cursor"],
        description="Target tools for distribution",
    )
    auto_distribute: bool = Field(
        default=True,
        description="Whether the daemon should auto-distribute this skill",
    )
    source_memory_ids: list[str] = Field(
        default_factory=list,
        description="Memory IDs this skill was extracted from",
    )
    auto_extracted: bool = Field(
        default=False,
        description="Whether this skill was auto-extracted by LLM",
    )
    extraction_confidence: float = Field(
        default=0,
        ge=0,
        le=1,
        description="LLM extraction confidence (0-1)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this skill was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this skill was last updated",
    )
    files: list[SkillFile] = Field(
        default_factory=list,
        description="Supporting files for this skill",
    )


class SkillFile(BaseModel):
    """A supporting file attached to a skill."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique file identifier",
    )
    skill_id: str = Field(description="Parent skill ID")
    path: str = Field(description="Relative file path (e.g. 'scripts/deploy.sh')")
    content: str = Field(description="File content")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this file was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this file was last updated",
    )


class IngestionJobStatus(StrEnum):
    """Status of an ingestion job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJob(BaseModel):
    """Tracks the progress of a bulk ingestion operation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique job identifier",
    )
    user_id: str = Field(default="", description="Owner user ID")
    source_type: str = Field(description="Type of source being ingested")
    source_path: str | None = Field(
        default=None,
        description="File or directory path being ingested",
    )
    status: IngestionJobStatus = Field(
        default=IngestionJobStatus.QUEUED,
        description="Current job status",
    )
    total_items: int = Field(default=0, ge=0, description="Total items to process")
    processed_items: int = Field(default=0, ge=0, description="Items processed so far")
    failed_items: int = Field(default=0, ge=0, description="Items that failed processing")
    error_message: str | None = Field(
        default=None,
        description="Error message if the job failed",
    )
    started_at: datetime | None = Field(
        default=None,
        description="When processing started",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When processing completed",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this job was created",
    )


class ConversationChunk(BaseModel):
    """A processed chunk from a conversation, ready for storage."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(description="Chunk text content")
    content_type: ContentType = Field(description="What kind of knowledge")
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
