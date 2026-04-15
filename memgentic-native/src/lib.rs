use pyo3::prelude::*;

mod graph;
mod parsers;
mod textproc;

/// Native Rust acceleration for Memgentic.
///
/// Submodules:
///   - textproc: Credential scrubbing, noise detection, text overlap, classification, entity extraction
///   - parsers:  Streaming JSONL, ChatGPT JSON, Protobuf, Markdown parsers
///   - graph:    petgraph-based knowledge graph engine
#[pymodule]
fn memgentic_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // --- textproc submodule ---
    let textproc_mod = PyModule::new_bound(m.py(), "textproc")?;
    textproc::register(&textproc_mod)?;
    m.add_submodule(&textproc_mod)?;
    // Fix Python import path so `from memgentic_native.textproc import ...` works
    m.py()
        .import_bound("sys")?
        .getattr("modules")?
        .set_item("memgentic_native.textproc", &textproc_mod)?;

    // --- parsers submodule ---
    let parsers_mod = PyModule::new_bound(m.py(), "parsers")?;
    parsers::register(&parsers_mod)?;
    m.add_submodule(&parsers_mod)?;
    m.py()
        .import_bound("sys")?
        .getattr("modules")?
        .set_item("memgentic_native.parsers", &parsers_mod)?;

    // --- graph submodule ---
    let graph_mod = PyModule::new_bound(m.py(), "graph")?;
    graph::register(&graph_mod)?;
    m.add_submodule(&graph_mod)?;
    m.py()
        .import_bound("sys")?
        .getattr("modules")?
        .set_item("memgentic_native.graph", &graph_mod)?;

    Ok(())
}
