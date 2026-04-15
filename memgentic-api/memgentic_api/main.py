"""Memgentic REST API — FastAPI application with lifespan management."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from email.utils import formatdate, parsedate_to_datetime

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from memgentic.config import settings
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from memgentic_api.auth import verify_api_key
from memgentic_api.deps import limiter
from memgentic_api.routes import (
    collections,
    graph,
    import_export,
    ingestion,
    memories,
    skills,
    sources,
    stats,
    uploads,
    websocket,
)

logger = structlog.get_logger()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies larger than MAX_BODY_SIZE."""

    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB

    async def dispatch(self, request, call_next):
        if request.headers.get("content-length"):
            content_length = int(request.headers["content-length"])
            if content_length > self.MAX_BODY_SIZE:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        return await call_next(request)


# Path patterns for Cache-Control max-age values
_STATS_PATHS = ("/api/v1/stats", "/api/v1/metrics", "/api/v1/sources", "/api/v1/health/detailed")
_LIST_PATHS = ("/api/v1/memories",)


class CachingHeadersMiddleware(BaseHTTPMiddleware):
    """Add ETag, Cache-Control, and Last-Modified headers to GET responses.

    Also handles conditional requests: If-None-Match (ETag) and If-Modified-Since.
    Returns 304 Not Modified when the content has not changed.
    """

    async def dispatch(self, request, call_next):
        # Only apply caching to GET requests
        if request.method != "GET":
            return await call_next(request)

        # Skip WebSocket upgrade requests
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        response = await call_next(request)

        # Only cache successful JSON responses
        if response.status_code != 200:
            return response

        # Read body for ETag computation
        body_chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        body = b"".join(body_chunks)

        # Generate ETag from content hash
        etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324

        # Check If-None-Match
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})

        # Determine Cache-Control max-age based on path
        path = request.url.path
        if any(path.startswith(p) for p in _STATS_PATHS):
            max_age = 300
        elif any(path.startswith(p) for p in _LIST_PATHS):
            max_age = 60
        else:
            max_age = 60  # Default for other GET endpoints

        # Build new response with caching headers
        new_response = Response(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type,
        )
        # Copy original headers
        for key, value in response.headers.items():
            if key.lower() not in ("content-length", "content-encoding", "transfer-encoding"):
                new_response.headers[key] = value

        new_response.headers["ETag"] = etag
        new_response.headers["Cache-Control"] = f"private, max-age={max_age}"
        new_response.headers["Last-Modified"] = formatdate(usegmt=True)

        # Check If-Modified-Since
        if_modified_since = request.headers.get("if-modified-since")
        if if_modified_since:
            try:
                since_dt = parsedate_to_datetime(if_modified_since)
                # For simplicity, compare against "now" — content was just generated
                # A 304 is only returned when the ETag matches (above)
                _ = since_dt  # placeholder for future last-modified tracking
            except (TypeError, ValueError):
                pass

        return new_response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize stores on startup, close on shutdown."""
    from memgentic.processing.embedder import Embedder
    from memgentic.processing.pipeline import IngestionPipeline
    from memgentic.storage.metadata import MetadataStore
    from memgentic.storage.vectors import VectorStore

    metadata_store = MetadataStore(settings.sqlite_path)
    vector_store = VectorStore(settings)
    embedder = Embedder(settings)

    # Optional: intelligence package for LLM client and knowledge graph
    llm_client = None
    graph = None
    try:
        from memgentic.processing.llm import LLMClient

        llm_client = LLMClient(settings)
    except ImportError:
        pass

    try:
        from memgentic.graph.knowledge import create_knowledge_graph

        graph = create_knowledge_graph(settings.graph_path)
        await graph.load()
        logger.info("api.intelligence_loaded", graph_nodes=graph.node_count)
    except ImportError:
        logger.info(
            "api.no_intelligence",
            msg="Intelligence extras not installed. Graph and advanced search unavailable.",
        )

    pipeline = IngestionPipeline(
        settings,
        metadata_store,
        vector_store,
        embedder,
        llm_client=llm_client,
        graph=graph,
    )

    await metadata_store.initialize()
    await vector_store.initialize()

    app.state.metadata_store = metadata_store
    app.state.vector_store = vector_store
    app.state.embedder = embedder
    app.state.pipeline = pipeline
    app.state.graph = graph

    logger.info("api.startup", storage=settings.storage_backend.value)

    yield

    if graph:
        await graph.save()
    await embedder.close()
    await metadata_store.close()
    await vector_store.close()
    logger.info("api.shutdown")


app = FastAPI(
    title="Memgentic API",
    description="Universal AI Memory Layer — search, manage, and stream memories",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security middlewares — order matters (Starlette processes outermost first)
# 1. Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# 2. CORS — allow dashboard and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "https://app.memgentic.dev"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "If-None-Match"],
)

# 3. Request size limit — reject oversized payloads early
app.add_middleware(RequestSizeLimitMiddleware)

# 4. HTTP caching headers (ETag, Cache-Control) for GET endpoints
app.add_middleware(CachingHeadersMiddleware)

# Mount routers — all require API key when MEMGENTIC_API_KEY is set
_auth = [Depends(verify_api_key)]
app.include_router(memories.router, prefix="/api/v1", tags=["memories"], dependencies=_auth)
app.include_router(sources.router, prefix="/api/v1", tags=["sources"], dependencies=_auth)
app.include_router(stats.router, prefix="/api/v1", tags=["stats"], dependencies=_auth)
app.include_router(
    import_export.router, prefix="/api/v1", tags=["import/export"], dependencies=_auth
)
app.include_router(graph.router, prefix="/api/v1", tags=["graph"], dependencies=_auth)
app.include_router(collections.router, prefix="/api/v1", tags=["collections"], dependencies=_auth)
app.include_router(uploads.router, prefix="/api/v1", tags=["uploads"], dependencies=_auth)
app.include_router(skills.router, prefix="/api/v1", tags=["skills"], dependencies=_auth)
app.include_router(ingestion.router, prefix="/api/v1", tags=["ingestion"], dependencies=_auth)

# WebSocket — no auth dependency (clients authenticate via initial message if needed)
app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])


@app.get("/api/v1/health", tags=["health"])
async def health_check():
    """Health check endpoint — verifies storage connectivity."""
    checks: dict[str, str] = {}

    # Check SQLite
    try:
        metadata = app.state.metadata_store
        await metadata.get_total_count()
        checks["sqlite"] = "ok"
    except Exception:
        checks["sqlite"] = "error"

    # Check vector store
    try:
        vectors = app.state.vector_store
        await vectors.get_collection_info()
        checks["vectors"] = "ok"
    except Exception:
        checks["vectors"] = "error"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "version": "0.1.0",
        "storage_backend": settings.storage_backend.value,
        "checks": checks,
    }
