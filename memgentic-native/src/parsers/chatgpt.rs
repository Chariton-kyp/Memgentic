use pyo3::prelude::*;
use serde_json::Value;

/// Flatten a ChatGPT mapping tree into chronological turns.
///
/// Each node in the mapping has an 'id', optional 'message', 'parent', and 'children'.
/// We sort by create_time to get chronological order, then extract user/assistant turns.
///
/// Returns list of dicts with 'role' and 'text' keys.
#[pyfunction]
pub fn flatten_chatgpt_mapping(mapping_json: &str) -> PyResult<Vec<PyObject>> {
    let mapping: Value = serde_json::from_str(mapping_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid JSON: {}", e)))?;

    let obj = match mapping.as_object() {
        Some(o) => o,
        None => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "mapping must be a JSON object",
            ))
        }
    };

    let mut nodes_with_time: Vec<(f64, String, String)> = Vec::new();

    for node in obj.values() {
        let node_obj = match node.as_object() {
            Some(o) => o,
            None => continue,
        };

        let message = match node_obj.get("message").and_then(Value::as_object) {
            Some(m) => m,
            None => continue,
        };

        let role = match message
            .get("author")
            .and_then(Value::as_object)
            .and_then(|a| a.get("role"))
            .and_then(Value::as_str)
        {
            Some(r) if r == "user" || r == "assistant" => r.to_string(),
            _ => continue,
        };

        let content = match message.get("content").and_then(Value::as_object) {
            Some(c) => c,
            None => continue,
        };

        let parts = match content.get("parts").and_then(Value::as_array) {
            Some(p) => p,
            None => continue,
        };

        let text_parts: Vec<String> = parts
            .iter()
            .filter_map(|part| part.as_str().map(String::from))
            .collect();

        let text = text_parts.join("\n").trim().to_string();
        if text.is_empty() {
            continue;
        }

        let create_time = message
            .get("create_time")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);

        nodes_with_time.push((create_time, role, text));
    }

    // Sort by create_time for chronological order
    nodes_with_time.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    Python::with_gil(|py| {
        nodes_with_time
            .into_iter()
            .map(|(_, role, text)| -> PyResult<PyObject> {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("role", &role)?;
                dict.set_item("text", &text)?;
                Ok(dict.into_any().unbind())
            })
            .collect()
    })
}

/// Parse a ChatGPT conversations.json file (or string content) and return
/// a list of conversations, each being a list of turn dicts with 'role' and 'text'.
///
/// This handles the full file: reads the JSON array, processes each conversation's
/// mapping tree, and returns the flattened turns per conversation.
#[pyfunction]
pub fn parse_chatgpt_conversations(json_content: &str) -> PyResult<Vec<Vec<PyObject>>> {
    let data: Value = serde_json::from_str(json_content)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid JSON: {}", e)))?;

    let conversations = match data.as_array() {
        Some(arr) => arr,
        None => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Expected a JSON array of conversations",
            ))
        }
    };

    let mut all_results: Vec<Vec<PyObject>> = Vec::new();

    for conv in conversations {
        let conv_obj = match conv.as_object() {
            Some(o) => o,
            None => continue,
        };

        let mapping = match conv_obj.get("mapping").and_then(Value::as_object) {
            Some(m) => m,
            None => continue,
        };

        let mut nodes_with_time: Vec<(f64, String, String)> = Vec::new();

        for node in mapping.values() {
            let node_obj = match node.as_object() {
                Some(o) => o,
                None => continue,
            };

            let message = match node_obj.get("message").and_then(Value::as_object) {
                Some(m) => m,
                None => continue,
            };

            let role = match message
                .get("author")
                .and_then(Value::as_object)
                .and_then(|a| a.get("role"))
                .and_then(Value::as_str)
            {
                Some(r) if r == "user" || r == "assistant" => r.to_string(),
                _ => continue,
            };

            let content = match message.get("content").and_then(Value::as_object) {
                Some(c) => c,
                None => continue,
            };

            let parts = match content.get("parts").and_then(Value::as_array) {
                Some(p) => p,
                None => continue,
            };

            let text_parts: Vec<String> = parts
                .iter()
                .filter_map(|part| part.as_str().map(String::from))
                .collect();

            let text = text_parts.join("\n").trim().to_string();
            if text.is_empty() {
                continue;
            }

            let create_time = message
                .get("create_time")
                .and_then(Value::as_f64)
                .unwrap_or(0.0);

            nodes_with_time.push((create_time, role, text));
        }

        nodes_with_time
            .sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

        let turns = Python::with_gil(|py| -> PyResult<Vec<PyObject>> {
            nodes_with_time
                .into_iter()
                .map(|(_, role, text)| -> PyResult<PyObject> {
                    let dict = pyo3::types::PyDict::new_bound(py);
                    dict.set_item("role", &role)?;
                    dict.set_item("text", &text)?;
                    Ok(dict.into_any().unbind())
                })
                .collect()
        })?;
        all_results.push(turns);
    }

    Ok(all_results)
}
