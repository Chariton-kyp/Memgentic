use pyo3::prelude::*;
use regex::Regex;
use std::sync::LazyLock;

struct CredentialPattern {
    name: &'static str,
    regex: Regex,
    replacement: &'static str,
}

static CREDENTIAL_PATTERNS: LazyLock<Vec<CredentialPattern>> = LazyLock::new(|| {
    vec![
        // OpenAI API keys
        CredentialPattern {
            name: "openai_key",
            regex: Regex::new(r"sk-[A-Za-z0-9_\-]{20,}").unwrap(),
            replacement: "[REDACTED:api_key]",
        },
        // OpenAI project keys
        CredentialPattern {
            name: "openai_proj",
            regex: Regex::new(r"sk-proj-[A-Za-z0-9_\-]{20,}").unwrap(),
            replacement: "[REDACTED:api_key]",
        },
        // AWS Access Key IDs
        CredentialPattern {
            name: "aws_key",
            regex: Regex::new(r"AKIA[0-9A-Z]{16}").unwrap(),
            replacement: "[REDACTED:aws_key]",
        },
        // AWS Secret Access Keys (40 chars base64-ish, between quotes)
        // Note: Rust regex doesn't support lookahead/lookbehind, so we match the quotes
        // and put them back in the replacement.
        CredentialPattern {
            name: "aws_secret",
            regex: Regex::new(r#"(['"])[A-Za-z0-9/+=]{40}(['"])"#).unwrap(),
            replacement: "${1}[REDACTED:aws_secret]${2}",
        },
        // GitHub tokens
        CredentialPattern {
            name: "github_token",
            regex: Regex::new(r"gh[pos]_[A-Za-z0-9_]{36,}").unwrap(),
            replacement: "[REDACTED:github_token]",
        },
        // Google API keys
        CredentialPattern {
            name: "google_key",
            regex: Regex::new(r"AIza[A-Za-z0-9_\-]{35}").unwrap(),
            replacement: "[REDACTED:google_key]",
        },
        // Anthropic API keys
        CredentialPattern {
            name: "anthropic_key",
            regex: Regex::new(r"sk-ant-[A-Za-z0-9_\-]{20,}").unwrap(),
            replacement: "[REDACTED:api_key]",
        },
        // Slack tokens
        CredentialPattern {
            name: "slack_token",
            regex: Regex::new(r"xox[bpras]-[A-Za-z0-9\-]{10,}").unwrap(),
            replacement: "[REDACTED:slack_token]",
        },
        // JWTs (three base64 segments)
        CredentialPattern {
            name: "jwt",
            regex: Regex::new(
                r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
            )
            .unwrap(),
            replacement: "[REDACTED:jwt]",
        },
        // Bearer tokens
        CredentialPattern {
            name: "bearer",
            regex: Regex::new(r"Bearer\s+[A-Za-z0-9_\-.]{20,}").unwrap(),
            replacement: "Bearer [REDACTED]",
        },
        // Authorization headers
        CredentialPattern {
            name: "auth_header",
            regex: Regex::new(r"Authorization:\s*\S+\s+[A-Za-z0-9_\-.]{20,}").unwrap(),
            replacement: "Authorization: [REDACTED]",
        },
        // Database connection strings
        CredentialPattern {
            name: "db_connection",
            regex: Regex::new(
                r#"(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s'"`,)]+:[^\s'"`,)]+@[^\s'"`,)]+"#
            )
            .unwrap(),
            replacement: "${1}://[REDACTED]@[REDACTED]",
        },
        // URL passwords
        CredentialPattern {
            name: "url_password",
            regex: Regex::new(r"://([^:]+):([^@\s]{8,})@").unwrap(),
            replacement: "://${1}:[REDACTED]@",
        },
        // .env style secrets
        CredentialPattern {
            name: "env_secret",
            regex: Regex::new(
                r"(?mi)^((?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ACCESS_KEY|AUTH)\w*)\s*=\s*\S+"
            )
            .unwrap(),
            replacement: "${1}=[REDACTED]",
        },
        // Private keys (PEM format)
        CredentialPattern {
            name: "private_key",
            regex: Regex::new(
                r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----"
            )
            .unwrap(),
            replacement: "[REDACTED:private_key]",
        },
        // Long hex strings (64+ chars, likely secrets)
        // Note: Rust regex doesn't support lookahead/lookbehind.
        // We use word boundary approximation instead.
        CredentialPattern {
            name: "hex_secret",
            regex: Regex::new(r"\b[0-9a-f]{64,}\b").unwrap(),
            replacement: "[REDACTED:hex_secret]",
        },
    ]
});

/// Result of credential scrubbing.
#[pyclass(get_all)]
#[derive(Clone)]
pub struct ScrubResult {
    pub text: String,
    pub redaction_count: usize,
    pub redacted_types: Vec<String>,
}

#[pymethods]
impl ScrubResult {
    fn __repr__(&self) -> String {
        format!(
            "ScrubResult(redaction_count={}, redacted_types={:?})",
            self.redaction_count, self.redacted_types
        )
    }
}

/// Core scrubbing logic (no GIL needed).
pub fn scrub_text_inner(text: &str) -> ScrubResult {
    let mut result = text.to_string();
    let mut redaction_count: usize = 0;
    let mut redacted_types: Vec<String> = Vec::new();

    for pattern in CREDENTIAL_PATTERNS.iter() {
        let mut count = 0usize;
        let new_text = pattern
            .regex
            .replace_all(&result, |caps: &regex::Captures| {
                count += 1;
                // Handle backreferences in replacement
                let mut replacement = pattern.replacement.to_string();
                for i in 1..caps.len() {
                    if let Some(m) = caps.get(i) {
                        replacement = replacement.replace(&format!("${{{}}}", i), m.as_str());
                        replacement = replacement.replace(&format!("${}", i), m.as_str());
                        replacement = replacement.replace(&format!("\\{}", i), m.as_str());
                    }
                }
                replacement
            });
        if count > 0 {
            result = new_text.into_owned();
            redaction_count += count;
            if !redacted_types.contains(&pattern.name.to_string()) {
                redacted_types.push(pattern.name.to_string());
            }
        }
    }

    ScrubResult {
        text: result,
        redaction_count,
        redacted_types,
    }
}

/// Scrub credentials from text, returning cleaned text and redaction info.
#[pyfunction]
pub fn scrub_text(text: &str) -> ScrubResult {
    scrub_text_inner(text)
}

/// Quick check — does this text contain any credential pattern?
#[pyfunction]
pub fn has_credentials(text: &str) -> bool {
    if text.is_empty() {
        return false;
    }
    CREDENTIAL_PATTERNS
        .iter()
        .any(|pattern| pattern.regex.is_match(text))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scrub_openai_key() {
        let text = "My key is sk-abc123def456ghi789jkl012mno";
        let result = scrub_text_inner(text);
        assert!(result.text.contains("[REDACTED:api_key]"));
        assert_eq!(result.redaction_count, 1);
        assert!(result.redacted_types.contains(&"openai_key".to_string()));
    }

    #[test]
    fn test_scrub_no_credentials() {
        let text = "This is a normal text with no secrets.";
        let result = scrub_text_inner(text);
        assert_eq!(result.text, text);
        assert_eq!(result.redaction_count, 0);
        assert!(result.redacted_types.is_empty());
    }

    #[test]
    fn test_has_credentials_empty() {
        assert!(!has_credentials(""));
    }

    #[test]
    fn test_scrub_github_token() {
        let text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";
        let result = scrub_text_inner(text);
        assert!(result.text.contains("[REDACTED:github_token]"));
    }

    #[test]
    fn test_scrub_multiple_credentials() {
        // Synthetic test fixtures — not real credentials.
        let fake_google = format!("AIzaSy{}", "X".repeat(33));
        let text = format!("key: sk-abc123def456ghi789jkl012mno and {}", fake_google);
        let result = scrub_text_inner(&text);
        assert_eq!(result.redaction_count, 2);
    }
}

/// Convenience wrapper that returns just the cleaned string.
#[pyfunction]
pub fn scrub_credentials(text: &str) -> String {
    if text.is_empty() {
        return text.to_string();
    }
    scrub_text_inner(text).text
}
