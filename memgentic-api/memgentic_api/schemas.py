"""API request/response models for Memgentic REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --- Response Models ---


class SourceResponse(BaseModel):
    """Source provenance metadata in API responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    platform: str
    platform_version: str | None = None
    session_id: str | None = None
    session_title: str | None = None
    capture_method: str
    original_timestamp: datetime | None = None
    file_path: str | None = None


class MemoryResponse(BaseModel):
    """Single memory in API responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    content: str
    content_type: str
    platform: str
    topics: list[str]
    entities: list[str]
    confidence: float
    status: str
    created_at: datetime
    last_accessed: datetime | None = None
    access_count: int = 0
    source: SourceResponse
    is_pinned: bool = False
    pinned_at: datetime | None = None


class MemoryListResponse(BaseModel):
    """Paginated memory list."""

    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int


class SearchResultItem(BaseModel):
    """Single search result with relevance score."""

    memory: MemoryResponse
    score: float


class SearchResultResponse(BaseModel):
    """Search results with scores."""

    results: list[SearchResultItem]
    query: str
    total: int


class SourceStatsResponse(BaseModel):
    """Per-platform statistics."""

    platform: str
    count: int
    percentage: float


class SourcesListResponse(BaseModel):
    """All sources with counts."""

    sources: list[SourceStatsResponse]
    total: int


class StatsResponse(BaseModel):
    """Overall memory statistics."""

    total_memories: int
    vector_count: int
    store_status: str
    sources: list[SourceStatsResponse]


class TimelineBucket(BaseModel):
    """Memory count for a date bucket."""

    date: str
    count: int


class TopicCount(BaseModel):
    """Topic with occurrence count."""

    topic: str
    count: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str
    storage_backend: str


# --- Request Models ---


class CreateMemoryRequest(BaseModel):
    """Create a new memory."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(..., min_length=3, max_length=10000)
    content_type: str = Field(default="fact")
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source: str = Field(default="unknown")


class UpdateMemoryRequest(BaseModel):
    """Update memory metadata (partial)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    topics: list[str] | None = None
    entities: list[str] | None = None
    status: str | None = None  # active, archived


class SearchRequest(BaseModel):
    """Semantic search request."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., min_length=2, max_length=1000)
    sources: list[str] | None = None
    exclude_sources: list[str] | None = None
    content_types: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class KeywordSearchRequest(BaseModel):
    """Full-text keyword search request."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., min_length=2)
    limit: int = Field(default=10, ge=1, le=50)


class ImportMemoriesRequest(BaseModel):
    """Import memories from JSON."""

    memories: list[CreateMemoryRequest]


# --- Collection Schemas ---


class CreateCollectionRequest(BaseModel):
    """Create a new collection."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    color: str = Field(default="#6B7280")
    icon: str = Field(default="folder")


class UpdateCollectionRequest(BaseModel):
    """Update collection metadata (partial)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    position: float | None = None


class CollectionResponse(BaseModel):
    """Single collection in API responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    user_id: str
    name: str
    description: str
    color: str
    icon: str
    position: float
    memory_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionListResponse(BaseModel):
    """List of collections."""

    collections: list[CollectionResponse]
    total: int


class AddMemoryToCollectionRequest(BaseModel):
    """Add a memory to a collection."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_id: str


# --- Upload Schemas ---


class UploadTextRequest(BaseModel):
    """Create a memory from plain text."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(..., min_length=3, max_length=50000)
    title: str | None = None
    topics: list[str] = Field(default_factory=list)
    content_type: str = Field(default="fact")


class UploadUrlRequest(BaseModel):
    """Create a memory from a URL."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(..., min_length=10)
    topics: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    """Upload result."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    filename: str
    status: str
    memory_id: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None


# --- Batch Operation Schemas ---


class BatchUpdateRequest(BaseModel):
    """Batch update multiple memories."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_ids: list[str] = Field(..., min_length=1, max_length=500)
    updates: dict[str, list[str] | str] = Field(
        ...,
        description="Fields to update: status (str), topics (list[str])",
    )


class BatchUpdateResponse(BaseModel):
    """Result of a batch update operation."""

    updated: int


class BatchDeleteRequest(BaseModel):
    """Batch archive (soft-delete) multiple memories."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_ids: list[str] = Field(..., min_length=1, max_length=500)


class BatchDeleteResponse(BaseModel):
    """Result of a batch delete operation."""

    deleted: int


# --- Skill Schemas ---


class SkillFileRequest(BaseModel):
    """File to attach to a skill."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    path: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)


class CreateSkillRequest(BaseModel):
    """Create a new skill."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    content: str = Field(default="")
    config: dict = Field(default_factory=dict)
    source: str = Field(default="manual")
    source_url: str | None = None
    version: str = Field(default="1.0.0")
    tags: list[str] = Field(default_factory=list)
    distribute_to: list[str] = Field(default_factory=lambda: ["claude", "codex", "cursor"])
    auto_distribute: bool = Field(default=True)
    files: list[SkillFileRequest] = Field(default_factory=list)


class UpdateSkillRequest(BaseModel):
    """Update a skill (partial)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = None
    description: str | None = None
    content: str | None = None
    config: dict | None = None
    source: str | None = None
    source_url: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    distribute_to: list[str] | None = None
    auto_distribute: bool | None = None


class SkillFileResponse(BaseModel):
    """A file attached to a skill."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    path: str
    content: str
    created_at: datetime
    updated_at: datetime


class SkillDistributionResponse(BaseModel):
    """A distribution record for a skill."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    tool: str
    target_path: str
    distributed_at: datetime
    status: str


class SkillResponse(BaseModel):
    """Single skill in API responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    user_id: str
    name: str
    description: str
    content: str
    config: dict
    source: str
    source_url: str | None = None
    version: str
    tags: list[str]
    distribute_to: list[str]
    auto_distribute: bool
    source_memory_ids: list[str]
    auto_extracted: bool
    extraction_confidence: float
    created_at: datetime
    updated_at: datetime
    files: list[SkillFileResponse] = Field(default_factory=list)
    distributions: list[SkillDistributionResponse] = Field(default_factory=list)


class SkillListResponse(BaseModel):
    """List of skills."""

    skills: list[SkillResponse]
    total: int


class ExtractSkillRequest(BaseModel):
    """Extract a skill from memory content."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_ids: list[str] = Field(..., min_length=1, max_length=100)


class DistributeSkillRequest(BaseModel):
    """Manually distribute a skill to specific tools."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    tools: list[str] = Field(..., min_length=1)


class ImportSkillRequest(BaseModel):
    """Import a skill from a remote source (currently GitHub)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    github_url: str = Field(..., min_length=10, max_length=2048)


# --- Ingestion Job Schemas ---


class IngestionJobResponse(BaseModel):
    """A single ingestion job in API responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    source_type: str
    source_path: str | None = None
    status: str
    total_items: int
    processed_items: int
    failed_items: int
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class IngestionJobListResponse(BaseModel):
    """Paginated list of ingestion jobs."""

    jobs: list[IngestionJobResponse]
    total: int
