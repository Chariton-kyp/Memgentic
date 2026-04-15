"""Knowledge graph endpoints — nodes, edges, and neighbor queries."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from memgentic.config import settings

from memgentic_api.deps import limiter

router = APIRouter()


def get_graph(request: Request) -> Any:
    """Get the shared KnowledgeGraph from app state (requires intelligence extras)."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(
            status_code=501,
            detail="Knowledge graph requires intelligence extras. "
            "Install with: pip install mneme-core[intelligence]",
        )
    return graph


GraphDep = Annotated[Any, Depends(get_graph)]


@router.get("/graph")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_graph_data(
    request: Request,
    graph: GraphDep,
    min_weight: int = Query(default=1, ge=1, description="Minimum edge weight to include"),
) -> dict:
    """Export full graph (nodes + edges) for dashboard visualization."""
    return await graph.get_graph_data(min_weight=min_weight)


@router.get("/graph/{entity}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_graph_neighbors(
    request: Request,
    entity: str,
    graph: GraphDep,
    depth: int = Query(default=2, ge=1, le=5, description="BFS depth"),
) -> dict:
    """Get neighbors of an entity up to *depth* hops."""
    return await graph.query_neighbors(entity, depth=depth)
