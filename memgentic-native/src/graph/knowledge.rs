use petgraph::graph::{NodeIndex, UnGraph};
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs;
use std::path::Path;

#[derive(Clone, Serialize, Deserialize)]
struct NodeData {
    name: String,
    node_type: String, // "topic" or "entity"
    memory_ids: Vec<String>,
    first_seen: String,
    last_seen: String,
    count: usize,
}

#[derive(Clone, Serialize, Deserialize)]
struct EdgeData {
    weight: usize,
    memory_ids: Vec<String>,
}

/// Serialization format for persistence.
#[derive(Serialize, Deserialize)]
struct GraphPersistence {
    nodes: Vec<NodeData>,
    edges: Vec<(usize, usize, EdgeData)>,
}

/// High-performance knowledge graph backed by petgraph.
///
/// Replaces NetworkX with a Rust-native graph for 10-50x faster operations.
/// Nodes represent entities/topics, edges represent co-occurrence in memories.
#[pyclass]
pub struct NativeKnowledgeGraph {
    graph: UnGraph<NodeData, EdgeData>,
    name_to_index: HashMap<String, NodeIndex>,
    path: String,
}

#[pymethods]
impl NativeKnowledgeGraph {
    #[new]
    fn new(graph_path: &str) -> Self {
        NativeKnowledgeGraph {
            graph: UnGraph::new_undirected(),
            name_to_index: HashMap::new(),
            path: graph_path.to_string(),
        }
    }

    /// Load graph from JSON file. No-op if file doesn't exist.
    fn load(&mut self) -> PyResult<()> {
        let path = Path::new(&self.path);
        if !path.exists() {
            return Ok(());
        }

        let content = fs::read_to_string(path).map_err(|e| {
            pyo3::exceptions::PyIOError::new_err(format!("Cannot read graph file: {}", e))
        })?;

        let persistence: GraphPersistence = serde_json::from_str(&content).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid graph JSON: {}", e))
        })?;

        self.graph = UnGraph::new_undirected();
        self.name_to_index.clear();

        // Add all nodes first
        let mut idx_map: Vec<NodeIndex> = Vec::new();
        for node_data in &persistence.nodes {
            let idx = self.graph.add_node(node_data.clone());
            self.name_to_index.insert(node_data.name.clone(), idx);
            idx_map.push(idx);
        }

        // Add edges
        for (src, tgt, edge_data) in &persistence.edges {
            if *src < idx_map.len() && *tgt < idx_map.len() {
                self.graph
                    .add_edge(idx_map[*src], idx_map[*tgt], edge_data.clone());
            }
        }

        Ok(())
    }

    /// Persist graph to JSON file.
    fn save(&self) -> PyResult<()> {
        // Build index-based persistence
        let node_indices: Vec<NodeIndex> = self.graph.node_indices().collect();
        let mut index_map: HashMap<NodeIndex, usize> = HashMap::new();
        let mut nodes: Vec<NodeData> = Vec::new();

        for (i, idx) in node_indices.iter().enumerate() {
            index_map.insert(*idx, i);
            nodes.push(self.graph[*idx].clone());
        }

        let mut edges: Vec<(usize, usize, EdgeData)> = Vec::new();
        for edge in self.graph.edge_indices() {
            if let Some((a, b)) = self.graph.edge_endpoints(edge) {
                let edge_data = self.graph[edge].clone();
                edges.push((index_map[&a], index_map[&b], edge_data));
            }
        }

        let persistence = GraphPersistence { nodes, edges };
        let json = serde_json::to_string(&persistence).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Cannot serialize graph: {}", e))
        })?;

        // Ensure parent directory exists
        if let Some(parent) = Path::new(&self.path).parent() {
            fs::create_dir_all(parent).map_err(|e| {
                pyo3::exceptions::PyIOError::new_err(format!("Cannot create directory: {}", e))
            })?;
        }

        fs::write(&self.path, json).map_err(|e| {
            pyo3::exceptions::PyIOError::new_err(format!("Cannot write graph file: {}", e))
        })?;

        Ok(())
    }

    /// Add or strengthen nodes and edges from a memory's metadata.
    fn add_memory(
        &mut self,
        memory_id: String,
        topics: Vec<String>,
        entities: Vec<String>,
    ) -> PyResult<()> {
        let now = chrono_now();

        let all_items: Vec<(String, String)> = topics
            .into_iter()
            .map(|t| (t, "topic".to_string()))
            .chain(entities.into_iter().map(|e| (e, "entity".to_string())))
            .collect();

        // Add/update nodes
        for (name, node_type) in &all_items {
            if let Some(&idx) = self.name_to_index.get(name) {
                let node = &mut self.graph[idx];
                node.memory_ids.push(memory_id.clone());
                node.last_seen = now.clone();
                node.count += 1;
            } else {
                let idx = self.graph.add_node(NodeData {
                    name: name.clone(),
                    node_type: node_type.clone(),
                    memory_ids: vec![memory_id.clone()],
                    first_seen: now.clone(),
                    last_seen: now.clone(),
                    count: 1,
                });
                self.name_to_index.insert(name.clone(), idx);
            }
        }

        // Create edges between all co-occurring items
        let names: Vec<&String> = all_items.iter().map(|(name, _)| name).collect();
        for i in 0..names.len() {
            for j in (i + 1)..names.len() {
                let a = names[i];
                let b = names[j];

                let idx_a = self.name_to_index[a];
                let idx_b = self.name_to_index[b];

                // Check if edge exists
                if let Some(edge) = self.graph.find_edge(idx_a, idx_b) {
                    let edge_data = &mut self.graph[edge];
                    edge_data.weight += 1;
                    edge_data.memory_ids.push(memory_id.clone());
                } else {
                    self.graph.add_edge(
                        idx_a,
                        idx_b,
                        EdgeData {
                            weight: 1,
                            memory_ids: vec![memory_id.clone()],
                        },
                    );
                }
            }
        }

        Ok(())
    }

    /// Get all memory IDs associated with a graph node.
    fn get_node_memory_ids(&self, name: &str) -> Vec<String> {
        match self.name_to_index.get(name) {
            Some(&idx) => self.graph[idx].memory_ids.clone(),
            None => Vec::new(),
        }
    }

    /// Breadth-first traversal from `entity` up to `depth` hops.
    ///
    /// Returns dict with 'entity', 'neighbors', and optionally 'not_found'.
    fn query_neighbors(&self, entity: &str, depth: usize) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let result = pyo3::types::PyDict::new(py);
            result.set_item("entity", entity)?;

            let start_idx = match self.name_to_index.get(entity) {
                Some(&idx) => idx,
                None => {
                    result.set_item("neighbors", pyo3::types::PyList::empty(py))?;
                    result.set_item("not_found", true)?;
                    return Ok(result.into_any().unbind());
                }
            };

            let mut neighbors: Vec<(String, String, usize, usize)> = Vec::new();
            let mut visited: HashSet<NodeIndex> = HashSet::new();
            let mut queue: VecDeque<(NodeIndex, usize)> = VecDeque::new();

            queue.push_back((start_idx, 0));

            while let Some((current, d)) = queue.pop_front() {
                if visited.contains(&current) || d > depth {
                    continue;
                }
                visited.insert(current);

                if current != start_idx {
                    let node = &self.graph[current];
                    neighbors.push((node.name.clone(), node.node_type.clone(), node.count, d));
                }

                if d < depth {
                    for nbr in self.graph.neighbors(current) {
                        if !visited.contains(&nbr) {
                            queue.push_back((nbr, d + 1));
                        }
                    }
                }
            }

            // Sort by count descending
            neighbors.sort_by_key(|n| std::cmp::Reverse(n.2));

            let py_neighbors = pyo3::types::PyList::empty(py);
            for (name, ntype, count, d) in &neighbors {
                let neighbor_dict = pyo3::types::PyDict::new(py);
                neighbor_dict.set_item("name", name)?;
                neighbor_dict.set_item("type", ntype)?;
                neighbor_dict.set_item("count", count)?;
                neighbor_dict.set_item("depth", d)?;
                py_neighbors.append(neighbor_dict)?;
            }
            result.set_item("neighbors", py_neighbors)?;

            Ok(result.into_any().unbind())
        })
    }

    /// Export the full graph as nodes and edges for visualization.
    #[pyo3(signature = (min_weight=1))]
    fn get_graph_data(&self, min_weight: usize) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let result = pyo3::types::PyDict::new(py);

            // Nodes
            let py_nodes = pyo3::types::PyList::empty(py);
            for idx in self.graph.node_indices() {
                let node = &self.graph[idx];
                let node_dict = pyo3::types::PyDict::new(py);
                node_dict.set_item("id", &node.name)?;
                node_dict.set_item("type", &node.node_type)?;
                node_dict.set_item("count", node.count)?;
                py_nodes.append(node_dict)?;
            }
            result.set_item("nodes", py_nodes)?;

            // Edges (filtered by min_weight)
            let py_edges = pyo3::types::PyList::empty(py);
            for edge in self.graph.edge_indices() {
                let edge_data = &self.graph[edge];
                if edge_data.weight >= min_weight {
                    if let Some((a, b)) = self.graph.edge_endpoints(edge) {
                        let edge_dict = pyo3::types::PyDict::new(py);
                        edge_dict.set_item("source", &self.graph[a].name)?;
                        edge_dict.set_item("target", &self.graph[b].name)?;
                        edge_dict.set_item("weight", edge_data.weight)?;
                        py_edges.append(edge_dict)?;
                    }
                }
            }
            result.set_item("edges", py_edges)?;

            Ok(result.into_any().unbind())
        })
    }

    /// Number of nodes in the graph.
    #[getter]
    fn node_count(&self) -> usize {
        self.graph.node_count()
    }

    /// Number of edges in the graph.
    #[getter]
    fn edge_count(&self) -> usize {
        self.graph.edge_count()
    }

    fn __repr__(&self) -> String {
        format!(
            "NativeKnowledgeGraph(nodes={}, edges={}, path='{}')",
            self.graph.node_count(),
            self.graph.edge_count(),
            self.path
        )
    }
}

/// Simple ISO 8601 timestamp (avoid adding chrono crate dependency).
fn chrono_now() -> String {
    use std::time::SystemTime;
    let duration = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = duration.as_secs();
    // Simple UTC timestamp formatting
    let days = secs / 86400;
    let time_of_day = secs % 86400;
    let hours = time_of_day / 3600;
    let minutes = (time_of_day % 3600) / 60;
    let seconds = time_of_day % 60;

    // Calculate year/month/day from days since epoch (1970-01-01)
    let (year, month, day) = days_to_date(days);

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}+00:00",
        year, month, day, hours, minutes, seconds
    )
}

/// Convert days since Unix epoch to (year, month, day).
fn days_to_date(mut days: u64) -> (u64, u64, u64) {
    // Algorithm from Howard Hinnant's civil_from_days
    days += 719468;
    let era = days / 146097;
    let doe = days - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_graph() -> NativeKnowledgeGraph {
        NativeKnowledgeGraph::new("/tmp/test_native_graph.json")
    }

    #[test]
    fn test_new_graph_empty() {
        let g = make_graph();
        assert_eq!(g.graph.node_count(), 0);
        assert_eq!(g.graph.edge_count(), 0);
    }

    #[test]
    fn test_add_memory_creates_nodes_and_edges() {
        let mut g = make_graph();
        g.add_memory(
            "mem1".to_string(),
            vec!["python".to_string()],
            vec!["FastAPI".to_string()],
        )
        .unwrap();
        assert_eq!(g.graph.node_count(), 2);
        assert_eq!(g.graph.edge_count(), 1);
    }

    #[test]
    fn test_add_memory_increments_count() {
        let mut g = make_graph();
        g.add_memory("mem1".to_string(), vec!["python".to_string()], vec![])
            .unwrap();
        g.add_memory("mem2".to_string(), vec!["python".to_string()], vec![])
            .unwrap();
        let idx = g.name_to_index["python"];
        assert_eq!(g.graph[idx].count, 2);
        assert_eq!(g.graph[idx].memory_ids.len(), 2);
    }

    #[test]
    fn test_get_node_memory_ids_existing() {
        let mut g = make_graph();
        g.add_memory("mem1".to_string(), vec!["rust".to_string()], vec![])
            .unwrap();
        let ids = g.get_node_memory_ids("rust");
        assert_eq!(ids, vec!["mem1".to_string()]);
    }

    #[test]
    fn test_get_node_memory_ids_missing() {
        let g = make_graph();
        let ids = g.get_node_memory_ids("nonexistent");
        assert!(ids.is_empty());
    }

    #[test]
    fn test_days_to_date_epoch() {
        let (y, m, d) = days_to_date(0);
        assert_eq!((y, m, d), (1970, 1, 1));
    }

    #[test]
    fn test_days_to_date_known() {
        // 2024-01-01 is day 19723 since epoch
        let (y, m, d) = days_to_date(19723);
        assert_eq!((y, m, d), (2024, 1, 1));
    }
}
