"""NetworkX knowledge graph — entity-relationship graph from memory metadata.

When ``memgentic-native`` is installed, the graph is backed by a Rust petgraph
engine (10-50x faster). Falls back to NetworkX transparently.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import networkx as nx
import structlog
from networkx.readwrite import json_graph

logger = structlog.get_logger()

# Try to use the Rust-native knowledge graph (10-50x faster).
try:
    from memgentic_native.graph import NativeKnowledgeGraph

    _USE_NATIVE_GRAPH = True
except ImportError:
    _USE_NATIVE_GRAPH = False


def create_knowledge_graph(graph_path: Path) -> KnowledgeGraph:
    """Factory function that returns the best available graph implementation.

    Returns a NativeKnowledgeGraph wrapper when Rust is available, otherwise
    falls back to the pure-Python NetworkX implementation.
    """
    if _USE_NATIVE_GRAPH:
        return RustKnowledgeGraph(graph_path)
    return KnowledgeGraph(graph_path)


class RustKnowledgeGraph:
    """Wrapper around the Rust NativeKnowledgeGraph with the same async API."""

    def __init__(self, graph_path: Path) -> None:
        self._inner = NativeKnowledgeGraph(str(graph_path))
        self._path = graph_path

    async def load(self) -> None:
        await asyncio.to_thread(self._inner.load)
        logger.info(
            "graph.loaded",
            backend="rust",
            nodes=self._inner.node_count,
            edges=self._inner.edge_count,
        )

    async def save(self) -> None:
        await asyncio.to_thread(self._inner.save)
        logger.debug(
            "graph.saved",
            backend="rust",
            nodes=self._inner.node_count,
            edges=self._inner.edge_count,
        )

    async def add_memory(self, memory_id: str, topics: list[str], entities: list[str]) -> None:
        await asyncio.to_thread(self._inner.add_memory, memory_id, topics, entities)

    def get_node_memory_ids(self, name: str) -> list[str]:
        return self._inner.get_node_memory_ids(name)

    async def query_neighbors(self, entity: str, depth: int = 2) -> dict:
        return await asyncio.to_thread(self._inner.query_neighbors, entity, depth)

    async def get_graph_data(self, min_weight: int = 1) -> dict:
        return await asyncio.to_thread(self._inner.get_graph_data, min_weight)

    @property
    def node_count(self) -> int:
        return self._inner.node_count

    @property
    def edge_count(self) -> int:
        return self._inner.edge_count


class KnowledgeGraph:
    """Co-occurrence graph of entities and topics extracted from memories.

    - Nodes = entities or topics (with type, count, memory_ids)
    - Edges = co-occurrence in the same memory (weighted by frequency)
    - Persisted as JSON via NetworkX's node-link format
    """

    def __init__(self, graph_path: Path) -> None:
        self._path = graph_path
        self._graph = nx.Graph()

    # --- Persistence ---

    async def load(self) -> None:
        """Load graph from JSON file (no-op if file doesn't exist)."""
        if self._path.exists():
            data = await asyncio.to_thread(self._read_json)
            self._graph = json_graph.node_link_graph(data)
            logger.info(
                "graph.loaded",
                nodes=self._graph.number_of_nodes(),
                edges=self._graph.number_of_edges(),
            )

    async def save(self) -> None:
        """Persist graph to JSON."""
        data = json_graph.node_link_data(self._graph)
        await asyncio.to_thread(self._write_json, data)
        logger.debug(
            "graph.saved",
            nodes=self._graph.number_of_nodes(),
            edges=self._graph.number_of_edges(),
        )

    def _read_json(self) -> dict:
        with open(self._path) as f:
            return json.load(f)

    def _write_json(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(data, f, default=str)

    # --- Mutations ---

    async def add_memory(
        self,
        memory_id: str,
        topics: list[str],
        entities: list[str],
    ) -> None:
        """Add or strengthen nodes and edges from a memory's metadata.

        For each topic and entity in the memory:
        - Creates a new node (with type, count=1) if it doesn't exist, or
          increments the existing node's count and appends the memory ID.
        - Creates or strengthens edges between all pairs of items that
          co-occur in this memory (complete graph over the union of topics
          and entities), incrementing edge weight on repeated co-occurrence.

        Args:
            memory_id: Unique identifier of the source memory.
            topics: Topic labels extracted from the memory.
            entities: Named entities extracted from the memory.
        """
        now = datetime.now(UTC).isoformat()
        all_items = [(t, "topic") for t in topics] + [(e, "entity") for e in entities]

        for name, node_type in all_items:
            if self._graph.has_node(name):
                node = self._graph.nodes[name]
                node.setdefault("memory_ids", []).append(memory_id)
                node["last_seen"] = now
                node["count"] = node.get("count", 0) + 1
            else:
                self._graph.add_node(
                    name,
                    type=node_type,
                    memory_ids=[memory_id],
                    first_seen=now,
                    last_seen=now,
                    count=1,
                )

        # Edges between all co-occurring items
        all_names = [name for name, _ in all_items]
        for a, b in combinations(all_names, 2):
            if self._graph.has_edge(a, b):
                self._graph[a][b]["weight"] += 1
                self._graph[a][b].setdefault("memory_ids", []).append(memory_id)
            else:
                self._graph.add_edge(a, b, weight=1, memory_ids=[memory_id])

    def get_node_memory_ids(self, name: str) -> list[str]:
        """Get all memory IDs associated with a graph node.

        Args:
            name: The node name (topic or entity).

        Returns:
            List of memory IDs that contributed to this node, or an empty
            list if the node does not exist.
        """
        if name not in self._graph:
            return []
        return self._graph.nodes[name].get("memory_ids", [])

    # --- Queries ---

    async def query_neighbors(self, entity: str, depth: int = 2) -> dict:
        """Breadth-first traversal from *entity* up to *depth* hops.

        Explores the co-occurrence graph outward from the given entity or
        topic node, returning all reachable neighbors within the specified
        depth. Neighbors are sorted by their occurrence count (descending).

        Args:
            entity: The node name to start traversal from.
            depth: Maximum number of hops from the starting node.

        Returns:
            Dict with keys:
            - ``entity``: the starting node name.
            - ``neighbors``: list of dicts with ``name``, ``type``,
              ``count``, and ``depth`` for each discovered neighbor.
            - ``not_found`` (optional): ``True`` if the entity is not in
              the graph.
        """
        if entity not in self._graph:
            return {"entity": entity, "neighbors": [], "not_found": True}

        neighbors: list[dict] = []
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(entity, 0)]

        while queue:
            current, d = queue.pop(0)
            if current in visited or d > depth:
                continue
            visited.add(current)

            if current != entity:
                node = self._graph.nodes[current]
                neighbors.append(
                    {
                        "name": current,
                        "type": node.get("type", "unknown"),
                        "count": node.get("count", 0),
                        "depth": d,
                    }
                )

            if d < depth:
                for nbr in self._graph.neighbors(current):
                    if nbr not in visited:
                        queue.append((nbr, d + 1))

        neighbors.sort(key=lambda n: n["count"], reverse=True)
        return {"entity": entity, "neighbors": neighbors}

    async def get_graph_data(self, min_weight: int = 1) -> dict:
        """Export the full graph as nodes and edges for visualization.

        Produces a JSON-serializable dict suitable for rendering in the
        dashboard's force-directed graph view.

        Args:
            min_weight: Minimum edge weight to include. Edges below this
                threshold are omitted, allowing the UI to hide weak
                co-occurrences.

        Returns:
            Dict with ``nodes`` (list of id/type/count dicts) and ``edges``
            (list of source/target/weight dicts).
        """
        nodes = [
            {
                "id": name,
                "type": data.get("type", "unknown"),
                "count": data.get("count", 0),
            }
            for name, data in self._graph.nodes(data=True)
        ]
        edges = [
            {"source": u, "target": v, "weight": data.get("weight", 1)}
            for u, v, data in self._graph.edges(data=True)
            if data.get("weight", 0) >= min_weight
        ]
        return {"nodes": nodes, "edges": edges}

    # --- Properties ---

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()
