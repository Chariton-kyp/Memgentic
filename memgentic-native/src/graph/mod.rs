use pyo3::prelude::*;

pub mod knowledge;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<knowledge::NativeKnowledgeGraph>()?;
    Ok(())
}
