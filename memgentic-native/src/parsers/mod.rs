use pyo3::prelude::*;

pub mod chatgpt;
pub mod jsonl;
pub mod markdown;
pub mod protobuf;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(jsonl::parse_jsonl_file, m)?)?;
    m.add_function(wrap_pyfunction!(jsonl::clean_xml_tags, m)?)?;
    m.add_function(wrap_pyfunction!(chatgpt::flatten_chatgpt_mapping, m)?)?;
    m.add_function(wrap_pyfunction!(chatgpt::parse_chatgpt_conversations, m)?)?;
    m.add_function(wrap_pyfunction!(
        protobuf::extract_strings_from_protobuf,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(protobuf::extract_strings_fallback, m)?)?;
    m.add_function(wrap_pyfunction!(markdown::split_markdown_turns, m)?)?;
    Ok(())
}
