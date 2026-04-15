"""Tests for the knowledge graph."""

from pathlib import Path

from memgentic.graph.knowledge import create_knowledge_graph


async def test_add_memory_creates_nodes(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "fastapi"], entities=["React"])
    assert g.node_count == 3
    assert g.edge_count == 3  # python-fastapi, python-React, fastapi-React


async def test_add_memory_strengthens_edges(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "docker"], entities=[])
    await g.add_memory("m2", topics=["python", "docker"], entities=[])
    # Edge weight should be 2 — verify via graph data export (backend-agnostic)
    data = await g.get_graph_data(min_weight=2)
    strong_edges = [e for e in data["edges"] if e["weight"] >= 2]
    assert len(strong_edges) >= 1


async def test_query_neighbors_found(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "fastapi"], entities=[])
    await g.add_memory("m2", topics=["fastapi", "docker"], entities=[])

    result = await g.query_neighbors("python", depth=1)
    assert result["entity"] == "python"
    names = [n["name"] for n in result["neighbors"]]
    assert "fastapi" in names


async def test_query_neighbors_depth_2(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "fastapi"], entities=[])
    await g.add_memory("m2", topics=["fastapi", "docker"], entities=[])

    result = await g.query_neighbors("python", depth=2)
    names = [n["name"] for n in result["neighbors"]]
    assert "fastapi" in names
    assert "docker" in names  # 2 hops away


async def test_query_neighbors_not_found(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    result = await g.query_neighbors("nonexistent")
    assert result["not_found"] is True
    assert result["neighbors"] == []


async def test_get_graph_data(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "fastapi"], entities=["Qdrant"])

    data = await g.get_graph_data()
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 3

    # Check node structure
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"python", "fastapi", "Qdrant"}


async def test_get_graph_data_min_weight(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    await g.add_memory("m1", topics=["python", "docker"], entities=[])
    await g.add_memory("m2", topics=["python", "docker"], entities=["react"])

    data_all = await g.get_graph_data(min_weight=1)
    data_strong = await g.get_graph_data(min_weight=2)

    assert len(data_strong["edges"]) < len(data_all["edges"])


async def test_save_load_roundtrip(tmp_path: Path):
    path = tmp_path / "graph.json"
    g1 = create_knowledge_graph(path)
    await g1.add_memory("m1", topics=["python", "fastapi"], entities=["React"])
    await g1.save()

    g2 = create_knowledge_graph(path)
    await g2.load()
    assert g2.node_count == g1.node_count
    assert g2.edge_count == g1.edge_count


async def test_node_and_edge_count(tmp_path: Path):
    g = create_knowledge_graph(tmp_path / "graph.json")
    assert g.node_count == 0
    assert g.edge_count == 0

    await g.add_memory("m1", topics=["a"], entities=["b"])
    assert g.node_count == 2
    assert g.edge_count == 1
