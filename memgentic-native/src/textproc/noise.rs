use pyo3::prelude::*;
use regex::Regex;
use std::sync::LazyLock;

static NOISE_ACKNOWLEDGMENT_PATTERNS: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(
            r"(?i)^(sure|ok|okay|yes|no|got it|understood|i see|thanks|thank you)[\s,.!]*(thanks|thank you|got it|understood|sure|ok|okay)?[\s,.!]*$"
        ).unwrap(),
        Regex::new(r"(?i)^(let me|here'?s|i'?ll|i will|i'?m going to)\b").unwrap(),
        Regex::new(r"(?i)^(looking at|reading|checking|searching|running|executing)\b").unwrap(),
        Regex::new(
            r"(?i)^(the (?:file|code|output|result|error)) (?:shows|says|indicates|contains)\b"
        ).unwrap(),
    ]
});

static OUTPUT_LINE_INDICATOR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r#"^\s*(?:at |File "|Traceback|>>>|\$|>|#|[0-9]+:|\s*\w+\.(?:py|js|ts|go|rs):\d+)"#,
    )
    .unwrap()
});

/// Core noise detection logic (no GIL needed).
pub fn is_noise_inner(text: &str) -> bool {
    if text.is_empty() {
        return true;
    }

    let stripped = text.trim();
    if stripped.len() < 8 {
        return true;
    }

    // Short acknowledgments
    if stripped.len() < 100 {
        for pattern in NOISE_ACKNOWLEDGMENT_PATTERNS.iter() {
            if pattern.is_match(stripped) {
                return true;
            }
        }
    }

    // Tool output dumps: low alphabetic ratio in long text
    if stripped.len() > 200 {
        let alpha_count = stripped.chars().filter(|c| c.is_alphabetic()).count();
        let alpha_ratio = alpha_count as f64 / stripped.len() as f64;
        if alpha_ratio < 0.3 {
            return true;
        }
    }

    // Stack traces / build logs: most lines start with output indicators
    let lines: Vec<&str> = stripped.split('\n').collect();
    if lines.len() > 5 {
        let output_lines = lines
            .iter()
            .filter(|line| OUTPUT_LINE_INDICATOR.is_match(line))
            .count();
        if output_lines as f64 / lines.len() as f64 > 0.6 {
            return true;
        }
    }

    false
}

/// Return True if this text is noise (pleasantry, acknowledgment, or tool output dump).
#[pyfunction]
pub fn is_noise(text: &str) -> bool {
    is_noise_inner(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_is_noise() {
        assert!(is_noise_inner(""));
    }

    #[test]
    fn test_short_is_noise() {
        assert!(is_noise_inner("ok"));
    }

    #[test]
    fn test_acknowledgment_is_noise() {
        assert!(is_noise_inner("Sure, got it."));
    }

    #[test]
    fn test_meaningful_text_not_noise() {
        assert!(!is_noise_inner(
            "Python uses indentation for block scoping instead of curly braces."
        ));
    }

    #[test]
    fn test_low_alpha_ratio_is_noise() {
        let text = "0123456789!@#$%^&*()".repeat(20);
        assert!(is_noise_inner(&text));
    }
}
