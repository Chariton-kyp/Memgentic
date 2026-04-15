use pyo3::prelude::*;
use std::collections::HashSet;

/// Core text overlap logic (no GIL needed).
pub fn text_overlap_inner(text_a: &str, text_b: &str) -> f64 {
    if text_a.is_empty() || text_b.is_empty() {
        return 0.0;
    }

    // Case-insensitive word-level Jaccard similarity matching Python behavior.
    let words_a_lower: HashSet<String> = text_a
        .split_whitespace()
        .map(|w| w.to_lowercase())
        .collect();
    let words_b_lower: HashSet<String> = text_b
        .split_whitespace()
        .map(|w| w.to_lowercase())
        .collect();

    let intersection = words_a_lower.intersection(&words_b_lower).count();
    let union = words_a_lower.union(&words_b_lower).count();

    if union == 0 {
        return 0.0;
    }

    intersection as f64 / union as f64
}

/// Compute word-level Jaccard similarity between two texts (0.0 to 1.0).
#[pyfunction]
pub fn text_overlap(text_a: &str, text_b: &str) -> f64 {
    text_overlap_inner(text_a, text_b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_texts() {
        let score = text_overlap_inner("hello world", "hello world");
        assert!((score - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_no_overlap() {
        let score = text_overlap_inner("hello world", "foo bar");
        assert!(score.abs() < f64::EPSILON);
    }

    #[test]
    fn test_partial_overlap() {
        let score = text_overlap_inner("hello world foo", "hello world bar");
        assert!((score - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn test_empty_text() {
        assert!(text_overlap_inner("", "hello").abs() < f64::EPSILON);
        assert!(text_overlap_inner("hello", "").abs() < f64::EPSILON);
    }

    #[test]
    fn test_case_insensitive() {
        let score = text_overlap_inner("Hello World", "hello world");
        assert!((score - 1.0).abs() < f64::EPSILON);
    }
}
