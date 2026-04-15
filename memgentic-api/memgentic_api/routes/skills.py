"""Skill CRUD, file management, and distribution endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from memgentic.config import settings
from memgentic.events import EventType, MemgenticEvent, event_bus
from memgentic.models import Skill, SkillFile
from memgentic.processing.skill_extractor import extract_skill_from_memories
from memgentic.skills.distributor import TOOL_SKILL_PATHS, SkillDistributor
from memgentic.skills.importer import SkillImporter, SkillImportError

from memgentic_api.deps import MetadataStoreDep, PipelineDep, limiter
from memgentic_api.schemas import (
    CreateSkillRequest,
    DistributeSkillRequest,
    ExtractSkillRequest,
    ImportSkillRequest,
    SkillDistributionResponse,
    SkillFileRequest,
    SkillFileResponse,
    SkillListResponse,
    SkillResponse,
    UpdateSkillRequest,
)

logger = structlog.get_logger()
router = APIRouter()


def _skill_to_response(
    skill: Skill,
    distributions: list[dict] | None = None,
) -> SkillResponse:
    """Convert a core Skill model to an API SkillResponse."""
    dist_list = []
    if distributions:
        dist_list = [
            SkillDistributionResponse(
                id=d["id"],
                tool=d["tool"],
                target_path=d["target_path"],
                distributed_at=d["distributed_at"],
                status=d["status"],
            )
            for d in distributions
        ]

    return SkillResponse(
        id=skill.id,
        user_id=skill.user_id,
        name=skill.name,
        description=skill.description,
        content=skill.content,
        config=skill.config,
        source=skill.source,
        source_url=skill.source_url,
        version=skill.version,
        tags=skill.tags,
        distribute_to=skill.distribute_to,
        auto_distribute=skill.auto_distribute,
        source_memory_ids=skill.source_memory_ids,
        auto_extracted=skill.auto_extracted,
        extraction_confidence=skill.extraction_confidence,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        files=[
            SkillFileResponse(
                id=f.id,
                path=f.path,
                content=f.content,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )
            for f in (skill.files or [])
        ],
        distributions=dist_list,
    )


# --- CRUD ---


@router.get("/skills")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_skills(
    request: Request,
    metadata_store: MetadataStoreDep,
) -> SkillListResponse:
    """List all skills."""
    skills = await metadata_store.get_skills()
    return SkillListResponse(
        skills=[_skill_to_response(s) for s in skills],
        total=len(skills),
    )


@router.post("/skills", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_skill(
    request: Request,
    body: CreateSkillRequest,
    metadata_store: MetadataStoreDep,
) -> SkillResponse:
    """Create a new skill, optionally with attached files."""
    skill = Skill(
        name=body.name,
        description=body.description,
        content=body.content,
        config=body.config,
        source=body.source,
        source_url=body.source_url,
        version=body.version,
        tags=body.tags,
        distribute_to=body.distribute_to,
        auto_distribute=body.auto_distribute,
    )

    try:
        await metadata_store.create_skill(skill)
    except Exception as exc:
        error_msg = str(exc)
        if "UNIQUE constraint" in error_msg:
            raise HTTPException(
                status_code=409,
                detail=f"A skill named '{body.name}' already exists",
            ) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc

    # Create attached files if any
    for file_req in body.files:
        sf = SkillFile(
            skill_id=skill.id,
            path=file_req.path,
            content=file_req.content,
        )
        await metadata_store.create_skill_file(sf)

    # Auto-distribute if enabled
    if skill.auto_distribute and skill.distribute_to:
        distributor = SkillDistributor(metadata_store)
        files = await metadata_store.get_skill_files(skill.id)
        await distributor.distribute_skill(skill, files, skill.distribute_to)

    # Re-fetch to include files
    created = await metadata_store.get_skill(skill.id)
    distributions = await metadata_store.get_skill_distributions(skill.id)
    await event_bus.emit(
        MemgenticEvent(type=EventType.SKILL_CREATED, data={"id": skill.id, "name": skill.name})
    )
    return _skill_to_response(created, distributions)


@router.get("/skills/{skill_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_skill(
    request: Request,
    skill_id: str,
    metadata_store: MetadataStoreDep,
) -> SkillResponse:
    """Get a skill with its files and distribution info."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    distributions = await metadata_store.get_skill_distributions(skill_id)
    return _skill_to_response(skill, distributions)


@router.put("/skills/{skill_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def update_skill(
    request: Request,
    skill_id: str,
    body: UpdateSkillRequest,
    metadata_store: MetadataStoreDep,
) -> SkillResponse:
    """Update a skill's metadata or content."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    update_kwargs = body.model_dump(exclude_none=True)
    if update_kwargs:
        await metadata_store.update_skill(skill_id, **update_kwargs)

    # Re-distribute if auto-distribute is on
    updated = await metadata_store.get_skill(skill_id)
    if updated.auto_distribute and updated.distribute_to:
        distributor = SkillDistributor(metadata_store)
        files = await metadata_store.get_skill_files(skill_id)
        await distributor.distribute_skill(updated, files, updated.distribute_to)

    distributions = await metadata_store.get_skill_distributions(skill_id)
    await event_bus.emit(
        MemgenticEvent(type=EventType.SKILL_UPDATED, data={"id": skill_id, "name": updated.name})
    )
    return _skill_to_response(updated, distributions)


@router.delete("/skills/{skill_id}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def delete_skill(
    request: Request,
    skill_id: str,
    metadata_store: MetadataStoreDep,
) -> None:
    """Delete a skill and remove it from all tool paths."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Remove from tool paths before deleting from DB
    distributor = SkillDistributor(metadata_store)
    await distributor.remove_skill(skill.name, skill.distribute_to)

    await metadata_store.delete_skill(skill_id)
    await event_bus.emit(
        MemgenticEvent(type=EventType.SKILL_DELETED, data={"id": skill_id, "name": skill.name})
    )


# --- Skill Files ---


@router.post("/skills/{skill_id}/files", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def add_skill_file(
    request: Request,
    skill_id: str,
    body: SkillFileRequest,
    metadata_store: MetadataStoreDep,
) -> SkillFileResponse:
    """Add a file to a skill."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    sf = SkillFile(
        skill_id=skill_id,
        path=body.path,
        content=body.content,
    )
    try:
        await metadata_store.create_skill_file(sf)
    except Exception as exc:
        error_msg = str(exc)
        if "UNIQUE constraint" in error_msg:
            raise HTTPException(
                status_code=409,
                detail=f"File '{body.path}' already exists in this skill",
            ) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc

    return SkillFileResponse(
        id=sf.id,
        path=sf.path,
        content=sf.content,
        created_at=sf.created_at,
        updated_at=sf.updated_at,
    )


@router.put("/skills/{skill_id}/files/{file_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def update_skill_file(
    request: Request,
    skill_id: str,
    file_id: str,
    body: SkillFileRequest,
    metadata_store: MetadataStoreDep,
) -> SkillFileResponse:
    """Update a skill file's path and content."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Verify the file exists and belongs to the skill
    files = await metadata_store.get_skill_files(skill_id)
    target = next((f for f in files if f.id == file_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Skill file not found")

    await metadata_store.update_skill_file(file_id, body.path, body.content)

    # Re-fetch to get updated timestamps
    updated_files = await metadata_store.get_skill_files(skill_id)
    updated = next((f for f in updated_files if f.id == file_id), None)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to fetch updated file")

    return SkillFileResponse(
        id=updated.id,
        path=updated.path,
        content=updated.content,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.delete("/skills/{skill_id}/files/{file_id}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def delete_skill_file(
    request: Request,
    skill_id: str,
    file_id: str,
    metadata_store: MetadataStoreDep,
) -> None:
    """Delete a file from a skill."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    files = await metadata_store.get_skill_files(skill_id)
    target = next((f for f in files if f.id == file_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Skill file not found")

    await metadata_store.delete_skill_file(file_id)


# --- Distribution ---


@router.post("/skills/{skill_id}/distribute")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def distribute_skill(
    request: Request,
    skill_id: str,
    body: DistributeSkillRequest,
    metadata_store: MetadataStoreDep,
) -> dict:
    """Manually trigger distribution of a skill to specific tools."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    files = await metadata_store.get_skill_files(skill_id)
    distributor = SkillDistributor(metadata_store)
    written = await distributor.distribute_skill(skill, files, body.tools)

    return {"distributed_to": body.tools, "paths": written}


@router.get("/skills/{skill_id}/distributions")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_skill_distributions(
    request: Request,
    skill_id: str,
    metadata_store: MetadataStoreDep,
) -> list[SkillDistributionResponse]:
    """List where a skill has been distributed."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    dists = await metadata_store.get_skill_distributions(skill_id)
    return [
        SkillDistributionResponse(
            id=d["id"],
            tool=d["tool"],
            target_path=d["target_path"],
            distributed_at=d["distributed_at"],
            status=d["status"],
        )
        for d in dists
    ]


# --- Remove Skill from a Specific Tool ---


@router.delete("/skills/{skill_id}/distribute/{tool}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def remove_skill_from_tool(
    request: Request,
    skill_id: str,
    tool: str,
    metadata_store: MetadataStoreDep,
) -> None:
    """Remove a skill from one specific tool without deleting the skill."""
    skill = await metadata_store.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if tool not in TOOL_SKILL_PATHS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown tool '{tool}'. Known tools: " + ", ".join(sorted(TOOL_SKILL_PATHS.keys()))
            ),
        )

    distributor = SkillDistributor(metadata_store)
    try:
        await distributor.remove_skill_from_tool(skill.name, tool)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        await metadata_store.delete_skill_distribution(skill_id, tool)
    except Exception as exc:
        logger.warning(
            "skills.remove_from_tool.delete_dist_failed",
            skill_id=skill_id,
            tool=tool,
            error=str(exc),
        )

    await event_bus.emit(
        MemgenticEvent(
            type=EventType.SKILL_UPDATED,
            data={"id": skill_id, "name": skill.name, "removed_from": tool},
        )
    )


# --- Extract Skill from Memories ---


@router.post("/skills/extract", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def extract_skill(
    request: Request,
    body: ExtractSkillRequest,
    metadata_store: MetadataStoreDep,
    pipeline: PipelineDep,
) -> SkillResponse:
    """Auto-extract a skill from memory content.

    Uses the configured LLM client (when available) to synthesize reusable
    SKILL.md instructions from a batch of related memories. Falls back to a
    deterministic naive concatenation when no LLM is configured so the endpoint
    keeps working in offline installs.
    """
    # Fetch all referenced memories
    memories_map = await metadata_store.get_memories_batch(body.memory_ids)
    found = [m for m in memories_map.values() if m is not None]

    if not found:
        raise HTTPException(
            status_code=404,
            detail="No valid memories found for the given IDs",
        )

    llm_client = getattr(pipeline, "llm_client", None)
    extraction = await extract_skill_from_memories(found, llm_client)

    llm_used = bool(llm_client and getattr(llm_client, "available", False))
    confidence = 0.85 if llm_used else 0.5

    skill = Skill(
        name=extraction["name"],
        description=extraction.get("description", ""),
        content=extraction.get("content", ""),
        source="auto_extracted",
        tags=extraction.get("tags", []),
        source_memory_ids=body.memory_ids,
        auto_extracted=True,
        extraction_confidence=confidence,
    )

    try:
        await metadata_store.create_skill(skill)
    except Exception as exc:
        error_msg = str(exc)
        if "UNIQUE constraint" in error_msg:
            raise HTTPException(
                status_code=409,
                detail=f"A skill named '{skill.name}' already exists",
            ) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc

    created = await metadata_store.get_skill(skill.id)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.SKILL_CREATED,
            data={"id": skill.id, "name": skill.name, "source": "auto_extracted"},
        )
    )
    return _skill_to_response(created)


# --- Import Skill from GitHub ---


@router.post("/skills/import", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def import_skill(
    request: Request,
    body: ImportSkillRequest,
    metadata_store: MetadataStoreDep,
) -> SkillResponse:
    """Import a skill from a GitHub URL.

    Fetches the referenced repository, parses SKILL.md, and persists the skill
    along with any supporting files. Returns the created skill record.
    """
    importer = SkillImporter()
    try:
        skill = await importer.import_from_github(body.github_url)
    except SkillImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Ensure we do not collide with an existing skill of the same name
    existing = await metadata_store.get_skill_by_name(skill.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A skill named '{skill.name}' already exists",
        )

    files = list(skill.files)
    skill.files = []  # stored via create_skill_file below

    try:
        await metadata_store.create_skill(skill)
    except Exception as exc:
        error_msg = str(exc)
        if "UNIQUE constraint" in error_msg:
            raise HTTPException(
                status_code=409,
                detail=f"A skill named '{skill.name}' already exists",
            ) from exc
        raise HTTPException(status_code=500, detail=error_msg) from exc

    for sf in files:
        sf.skill_id = skill.id
        try:
            await metadata_store.create_skill_file(sf)
        except Exception as exc:
            logger.warning(
                "skills.import.file_persist_failed",
                skill_id=skill.id,
                path=sf.path,
                error=str(exc),
            )

    # Auto-distribute if the skill opted in (default True)
    if skill.auto_distribute and skill.distribute_to:
        distributor = SkillDistributor(metadata_store)
        persisted_files = await metadata_store.get_skill_files(skill.id)
        await distributor.distribute_skill(skill, persisted_files, skill.distribute_to)

    created = await metadata_store.get_skill(skill.id)
    distributions = await metadata_store.get_skill_distributions(skill.id)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.SKILL_CREATED,
            data={
                "id": skill.id,
                "name": skill.name,
                "source": "imported",
                "source_url": body.github_url,
            },
        )
    )
    return _skill_to_response(created, distributions)
