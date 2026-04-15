use pyo3::prelude::*;
use regex::Regex;
use serde_json::Value;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::LazyLock;

/// Compiled XML noise patterns matching Claude Code infrastructure tags.
static XML_NOISE_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(r"(?s)<system-reminder>.*?</system-reminder>").unwrap(),
        Regex::new(r"(?s)<task-notification>.*?</task-notification>").unwrap(),
        Regex::new(r"(?s)<observed_from_primary_session>.*?</observed_from_primary_session>")
            .unwrap(),
        Regex::new(r"(?s)<command-name>.*?</command-name>").unwrap(),
        Regex::new(r"(?s)<command-message>.*?</command-message>").unwrap(),
        Regex::new(r"(?s)<command-args>.*?</command-args>").unwrap(),
        Regex::new(r"(?s)<local-command-stdout>.*?</local-command-stdout>").unwrap(),
    ]
});

static RE_MULTI_NEWLINES: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\n{3,}").unwrap());

/// Strip XML infrastructure noise and normalize whitespace.
pub fn clean_xml_tags_inner(text: &str) -> String {
    let mut result = text.to_string();
    for pattern in XML_NOISE_PATTERNS.iter() {
        result = pattern.replace_all(&result, "").into_owned();
    }
    result = RE_MULTI_NEWLINES.replace_all(&result, "\n\n").into_owned();
    result.trim().to_string()
}

/// Clean XML infrastructure tags from Claude Code text.
#[pyfunction]
pub fn clean_xml_tags(text: &str) -> String {
    clean_xml_tags_inner(text)
}

/// Extract readable text from a Claude Code turn JSON object.
fn extract_text_from_turn(turn: &Value) -> String {
    // Try message.content first (current format)
    let content = if let Some(message) = turn.get("message") {
        if let Some(obj) = message.as_object() {
            obj.get("content")
                .cloned()
                .unwrap_or(Value::String(String::new()))
        } else if let Some(s) = message.as_str() {
            return clean_xml_tags_inner(s);
        } else {
            turn.get("content")
                .cloned()
                .unwrap_or(Value::String(String::new()))
        }
    } else {
        turn.get("content")
            .cloned()
            .unwrap_or(Value::String(String::new()))
    };

    match content {
        Value::String(s) => clean_xml_tags_inner(&s),
        Value::Array(blocks) => {
            let mut parts = Vec::new();
            for block in &blocks {
                if let Some(s) = block.as_str() {
                    parts.push(s.to_string());
                } else if let Some(obj) = block.as_object() {
                    // Only keep text blocks — skip tool_use, tool_result, thinking
                    if obj.get("type").and_then(Value::as_str) == Some("text") {
                        if let Some(text) = obj.get("text").and_then(Value::as_str) {
                            parts.push(text.to_string());
                        }
                    }
                }
            }
            let joined = parts.join("\n").trim().to_string();
            if joined.is_empty() {
                String::new()
            } else {
                clean_xml_tags_inner(&joined)
            }
        }
        _ => {
            if content.is_null() {
                String::new()
            } else {
                clean_xml_tags_inner(&content.to_string())
            }
        }
    }
}

/// Represents a parsed turn from a JSONL conversation.
#[derive(Clone)]
struct ParsedTurn {
    role: String,
    text: String,
}

/// Parse a Claude Code JSONL file and return a list of dicts with 'role' and 'text' keys.
///
/// Streams the file line-by-line (not loading the entire file into memory),
/// parses each JSON object, extracts role and text, cleans XML tags.
#[pyfunction]
pub fn parse_jsonl_file(file_path: &str) -> PyResult<Vec<PyObject>> {
    let file = File::open(file_path)
        .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Cannot open file: {}", e)))?;
    let reader = BufReader::new(file);

    let mut turns: Vec<ParsedTurn> = Vec::new();

    for line_result in reader.lines() {
        let line = match line_result {
            Ok(l) => l,
            Err(_) => continue,
        };

        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let turn: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(_) => continue,
        };

        // Get role from "role" or "type" field
        let role = turn
            .get("role")
            .or_else(|| turn.get("type"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();

        // Skip infrastructure turns
        if role == "system" || role == "file-history-snapshot" {
            continue;
        }

        let text = extract_text_from_turn(&turn);
        if text.len() < 20 {
            continue;
        }

        turns.push(ParsedTurn { role, text });
    }

    // Convert to Python dicts
    Python::with_gil(|py| {
        turns
            .into_iter()
            .map(|turn| -> PyResult<PyObject> {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("role", &turn.role)?;
                dict.set_item("text", &turn.text)?;
                Ok(dict.into_any().unbind())
            })
            .collect()
    })
}
