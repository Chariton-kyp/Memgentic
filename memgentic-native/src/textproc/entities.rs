use pyo3::prelude::*;
use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

static RE_URLS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"https?://([^\s<>"'/?#]+)"#).unwrap());

static RE_FILE_PATHS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"\b[\w/\\.\-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|sql|sh|go|rs|java|css|html)\b",
    )
    .unwrap()
});

static RE_CAMEL_CASE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b").unwrap());

static RE_PROPER_NOUNS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b").unwrap());

static RE_NPM_PACKAGES: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"@[\w\-]+/[\w\-]+").unwrap());

static RE_VERSION_STRINGS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b[A-Za-z]+\s+\d+(?:\.\d+)+\b").unwrap());

static RE_VERSION_SHORT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\bv\d+(?:\.\d+)+\b").unwrap());

/// Core entity extraction logic (no GIL needed).
pub fn extract_named_entities_inner(text: &str) -> Vec<String> {
    let mut entities: Vec<String> = Vec::new();

    // URLs — extract domain names
    for cap in RE_URLS.captures_iter(text) {
        let domain = &cap[1];
        if domain.contains('.') {
            entities.push(domain.to_string());
        }
    }

    // File paths with extensions
    for m in RE_FILE_PATHS.find_iter(text) {
        entities.push(m.as_str().to_string());
    }

    // CamelCase identifiers
    for m in RE_CAMEL_CASE.find_iter(text) {
        entities.push(m.as_str().to_string());
    }

    // Capitalized multi-word phrases (proper nouns)
    for m in RE_PROPER_NOUNS.find_iter(text) {
        entities.push(m.as_str().to_string());
    }

    // @-scoped packages
    for m in RE_NPM_PACKAGES.find_iter(text) {
        entities.push(m.as_str().to_string());
    }

    // Version strings
    for m in RE_VERSION_STRINGS.find_iter(text) {
        entities.push(m.as_str().to_string());
    }
    for m in RE_VERSION_SHORT.find_iter(text) {
        entities.push(m.as_str().to_string());
    }

    // Deduplicate while preserving order
    let mut seen = HashSet::new();
    let mut unique = Vec::new();
    for e in entities {
        let lower = e.to_lowercase();
        if seen.insert(lower) {
            unique.push(e);
        }
    }

    unique.truncate(15);
    unique
}

/// Extract named entities using regex heuristics (no NLP library needed).
#[pyfunction]
pub fn extract_named_entities(text: &str) -> Vec<String> {
    extract_named_entities_inner(text)
}
