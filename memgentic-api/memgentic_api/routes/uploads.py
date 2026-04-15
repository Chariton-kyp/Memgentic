"""Upload endpoints — text, file (multipart), and URL ingestion.

All upload routes produce memories through ``pipeline.ingest_single``, which
emits ``MEMORY_CREATED`` events via the global event bus. That means upload
completion is broadcast to websocket subscribers automatically — no extra
``event_bus.emit`` call is needed inside these handlers.
"""

from __future__ import annotations

import mimetypes

import structlog
from fastapi import APIRouter, HTTPException, Request, UploadFile
from memgentic.config import settings
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Platform,
    Upload,
    UploadStatus,
)

from memgentic_api.deps import MetadataStoreDep, PipelineDep, limiter
from memgentic_api.schemas import (
    UploadResponse,
    UploadTextRequest,
    UploadUrlRequest,
)

logger = structlog.get_logger()
router = APIRouter()

# Maximum upload file size (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Allowed MIME types for file upload
ALLOWED_MIME_TYPES = {
    # Text-based (UTF-8)
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "text/html",
    "application/json",
    "application/xml",
    "text/xml",
    # PDF
    "application/pdf",
    # Microsoft Office
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    # Rich Text
    "application/rtf",
    "text/rtf",
    # eBooks
    "application/epub+zip",
}


def _upload_to_response(upload: Upload) -> UploadResponse:
    """Convert an Upload model to an API response."""
    return UploadResponse(
        id=upload.id,
        filename=upload.filename,
        status=upload.status.value,
        memory_id=upload.memory_id,
        error_message=upload.error_message,
        created_at=upload.created_at,
    )


@router.post("/upload/text", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def upload_text(
    request: Request,
    body: UploadTextRequest,
    metadata_store: MetadataStoreDep,
    pipeline: PipelineDep,
) -> UploadResponse:
    """Create a memory from plain text content."""
    # Determine content type
    try:
        ct = ContentType(body.content_type)
    except ValueError:
        ct = ContentType.FACT

    # Create upload tracking record
    title = body.title or "Text upload"
    upload = Upload(
        filename=title,
        mime_type="text/plain",
        file_size=len(body.content.encode("utf-8")),
        upload_source="manual",
    )
    await metadata_store.create_upload(upload)

    try:
        memory = await pipeline.ingest_single(
            content=body.content,
            content_type=ct,
            platform=Platform.MANUAL,
            topics=body.topics,
            capture_method=CaptureMethod.MANUAL_UPLOAD,
        )
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.COMPLETED,
            memory_id=memory.id,
        )
        logger.info("uploads.text_completed", upload_id=upload.id, memory_id=memory.id)
        return UploadResponse(
            id=upload.id,
            filename=title,
            status=UploadStatus.COMPLETED.value,
            memory_id=memory.id,
        )
    except Exception as exc:
        error_msg = str(exc)
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.FAILED,
            error=error_msg,
        )
        logger.error("uploads.text_failed", upload_id=upload.id, error=error_msg)
        raise HTTPException(status_code=500, detail=f"Failed to process text: {error_msg}") from exc


@router.post("/upload/file", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def upload_file(
    request: Request,
    file: UploadFile,
    metadata_store: MetadataStoreDep,
    pipeline: PipelineDep,
) -> UploadResponse:
    """Upload a file, extract text, and create a memory."""
    from memgentic.processing.file_ingest import extract_text_from_file

    # Determine MIME type
    guessed = mimetypes.guess_type(file.filename or "")[0]
    mime_type = file.content_type or guessed or "application/octet-stream"

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {mime_type}. "
            f"Allowed types: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    # Read file content
    content_bytes = await file.read()
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    filename = file.filename or "uploaded_file"

    # Create upload tracking record
    upload = Upload(
        filename=filename,
        mime_type=mime_type,
        file_size=len(content_bytes),
        upload_source="manual",
    )
    await metadata_store.create_upload(upload)

    try:
        # Extract text from file
        text = extract_text_from_file(content_bytes, mime_type)
        if not text.strip():
            raise ValueError("No text content could be extracted from the file")

        # Ingest as memory
        memory = await pipeline.ingest_single(
            content=text,
            content_type=ContentType.FACT,
            platform=Platform.MANUAL,
            topics=[],
            capture_method=CaptureMethod.MANUAL_UPLOAD,
        )
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.COMPLETED,
            memory_id=memory.id,
        )
        logger.info(
            "uploads.file_completed",
            upload_id=upload.id,
            memory_id=memory.id,
            filename=filename,
        )
        return UploadResponse(
            id=upload.id,
            filename=filename,
            status=UploadStatus.COMPLETED.value,
            memory_id=memory.id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.FAILED,
            error=error_msg,
        )
        raise HTTPException(status_code=422, detail=error_msg) from exc
    except Exception as exc:
        error_msg = str(exc)
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.FAILED,
            error=error_msg,
        )
        logger.error("uploads.file_failed", upload_id=upload.id, error=error_msg)
        raise HTTPException(status_code=500, detail=f"Failed to process file: {error_msg}") from exc


@router.post("/upload/url", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def upload_url(
    request: Request,
    body: UploadUrlRequest,
    metadata_store: MetadataStoreDep,
    pipeline: PipelineDep,
) -> UploadResponse:
    """Fetch a URL, extract text content, and create a memory."""
    from memgentic.processing.file_ingest import extract_text_from_url

    # Create upload tracking record
    upload = Upload(
        filename=body.url,
        mime_type="text/html",
        upload_source="url",
        original_url=body.url,
    )
    await metadata_store.create_upload(upload)

    try:
        text, title = await extract_text_from_url(body.url)

        # Use page title as session title metadata
        memory = await pipeline.ingest_single(
            content=text,
            content_type=ContentType.FACT,
            platform=Platform.MANUAL,
            topics=body.topics,
            capture_method=CaptureMethod.URL_IMPORT,
        )

        # Update upload file size now that we know the content length
        upload.file_size = len(text.encode("utf-8"))
        if title:
            upload.filename = title

        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.COMPLETED,
            memory_id=memory.id,
        )
        logger.info(
            "uploads.url_completed",
            upload_id=upload.id,
            memory_id=memory.id,
            url=body.url,
            title=title,
        )
        return UploadResponse(
            id=upload.id,
            filename=title or body.url,
            status=UploadStatus.COMPLETED.value,
            memory_id=memory.id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.FAILED,
            error=error_msg,
        )
        raise HTTPException(status_code=422, detail=error_msg) from exc
    except Exception as exc:
        error_msg = str(exc)
        await metadata_store.update_upload_status(
            upload.id,
            status=UploadStatus.FAILED,
            error=error_msg,
        )
        logger.error("uploads.url_failed", upload_id=upload.id, error=error_msg)
        raise HTTPException(status_code=500, detail=f"Failed to process URL: {error_msg}") from exc


@router.get("/uploads")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_uploads(
    request: Request,
    metadata_store: MetadataStoreDep,
    limit: int = 50,
) -> list[UploadResponse]:
    """List recent uploads with their processing status."""
    uploads = await metadata_store.get_uploads(limit=limit)
    return [_upload_to_response(u) for u in uploads]
