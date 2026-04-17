use pyo3::prelude::*;

pub mod classify;
pub mod entities;
pub mod noise;
pub mod overlap;
pub mod scrubber;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(scrubber::scrub_text, m)?)?;
    m.add_function(wrap_pyfunction!(scrubber::has_credentials, m)?)?;
    m.add_function(wrap_pyfunction!(scrubber::scrub_credentials, m)?)?;
    m.add_function(wrap_pyfunction!(noise::is_noise, m)?)?;
    m.add_function(wrap_pyfunction!(overlap::text_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(classify::heuristic_classify, m)?)?;
    m.add_function(wrap_pyfunction!(classify::heuristic_extract, m)?)?;
    m.add_function(wrap_pyfunction!(entities::extract_named_entities, m)?)?;
    m.add_function(wrap_pyfunction!(batch_process, m)?)?;
    m.add_class::<scrubber::ScrubResult>()?;
    Ok(())
}

/// Process a batch of texts in parallel using Rayon.
/// Returns list of dicts with keys: cleaned_text, is_noise, content_type, confidence, entities, redaction_count.
#[pyfunction]
fn batch_process(texts: Vec<String>) -> PyResult<Vec<PyObject>> {
    use rayon::prelude::*;

    let results: Vec<_> = texts
        .par_iter()
        .map(|text| {
            let scrub = scrubber::scrub_text_inner(text);
            let noisy = noise::is_noise_inner(&scrub.text);
            let (content_type, confidence) = classify::heuristic_classify_inner(&scrub.text);
            let ents = entities::extract_named_entities_inner(&scrub.text);

            (scrub, noisy, content_type, confidence, ents)
        })
        .collect();

    Python::with_gil(|py| {
        results
            .into_iter()
            .map(|(scrub, noisy, content_type, confidence, ents)| -> PyResult<PyObject> {
                let dict = pyo3::types::PyDict::new(py);
                dict.set_item("cleaned_text", &scrub.text)?;
                dict.set_item("is_noise", noisy)?;
                dict.set_item("content_type", &content_type)?;
                dict.set_item("confidence", confidence)?;
                dict.set_item("entities", &ents)?;
                dict.set_item("redaction_count", scrub.redaction_count)?;
                dict.set_item("redacted_types", &scrub.redacted_types)?;
                Ok(dict.into_any().unbind())
            })
            .collect::<PyResult<Vec<_>>>()
    })
}
