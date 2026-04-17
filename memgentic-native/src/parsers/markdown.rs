use pyo3::prelude::*;
use regex::Regex;
use std::sync::LazyLock;

/// Regex for Aider-style markdown turn markers (#### user / #### assistant).
static RE_AIDER_SPLIT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?m)^####\s+").unwrap());

/// Regex for Codex-style markdown turn markers (# user / ## assistant).
/// Matches the full header including role word (no lookahead — unsupported by regex crate).
static RE_CODEX_SPLIT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?mi)^#{1,2}\s+(?:user|assistant)\b").unwrap());

/// Split Aider-style Markdown into (role, content) pairs on `#### ` markers.
///
/// Returns list of (role, content) tuples where role is 'user' or 'assistant'.
fn split_aider_inner(text: &str) -> Vec<(String, String)> {
    let parts: Vec<&str> = RE_AIDER_SPLIT.split(text).collect();
    let mut turns = Vec::new();

    for part in parts {
        let trimmed = part.trim();
        if trimmed.is_empty() {
            continue;
        }

        // First line is the role, rest is content
        let (role_line, content) = match trimmed.split_once('\n') {
            Some((first, rest)) => (first.trim().to_lowercase(), rest.trim().to_string()),
            None => (trimmed.to_lowercase(), String::new()),
        };

        if role_line == "user" || role_line == "assistant" {
            turns.push((role_line, content));
        }
    }

    turns
}

/// Split Codex-style Markdown into (role, content) pairs.
/// Uses find_iter instead of split since the regex consumes the role word.
fn split_codex_inner(text: &str) -> Vec<(String, String)> {
    let mut turns = Vec::new();
    let mut last_end = 0;
    let mut last_role: Option<String> = None;

    for m in RE_CODEX_SPLIT.find_iter(text) {
        // Flush the content accumulated for the previous role
        if let Some(role) = last_role.take() {
            let content = text[last_end..m.start()].trim().to_string();
            turns.push((role, content));
        }
        // Extract the role from the matched header (e.g., "# user" -> "user")
        let header = m.as_str().trim();
        let role = header.trim_start_matches('#').trim().to_lowercase();
        if role == "user" || role == "assistant" {
            last_role = Some(role);
        }
        last_end = m.end();
    }

    // Flush trailing content for the last role
    if let Some(role) = last_role.take() {
        let content = text[last_end..].trim().to_string();
        turns.push((role, content));
    }

    turns
}

/// Split Markdown conversation text into (role, content) pairs.
///
/// Supports two formats:
///   - "aider": Splits on `#### user` / `#### assistant` markers
///   - "codex": Splits on `# user` / `## assistant` markers
///
/// Returns list of (role, content) tuples.
#[pyfunction]
#[pyo3(signature = (text, format="aider"))]
pub fn split_markdown_turns(text: &str, format: &str) -> Vec<(String, String)> {
    match format {
        "codex" => split_codex_inner(text),
        _ => split_aider_inner(text),
    }
}
