"""Credential scrubbing — redact secrets before storing memories."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Try to use the Rust-native implementation (20-50x faster).
try:
    from memgentic_native.textproc import (
        has_credentials as _native_has_credentials,
    )
    from memgentic_native.textproc import (
        scrub_credentials as _native_scrub_credentials,
    )
    from memgentic_native.textproc import (
        scrub_text as _native_scrub_text,
    )

    _USE_NATIVE = True
except ImportError:
    _USE_NATIVE = False

# Each pattern: (name, compiled regex, replacement text)
CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # OpenAI API keys
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED:api_key]"),
    # OpenAI project keys
    ("openai_proj", re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "[REDACTED:api_key]"),
    # AWS Access Key IDs
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws_key]"),
    # AWS Secret Access Keys (40 chars base64-ish)
    ("aws_secret", re.compile(r"(?<=['\"])[A-Za-z0-9/+=]{40}(?=['\"])"), "[REDACTED:aws_secret]"),
    # GitHub tokens
    ("github_token", re.compile(r"gh[pos]_[A-Za-z0-9_]{36,}"), "[REDACTED:github_token]"),
    # Google API keys
    ("google_key", re.compile(r"AIza[A-Za-z0-9_-]{35}"), "[REDACTED:google_key]"),
    # Anthropic API keys
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED:api_key]"),
    # Slack tokens
    ("slack_token", re.compile(r"xox[bpras]-[A-Za-z0-9-]{10,}"), "[REDACTED:slack_token]"),
    # JWTs (three base64 segments separated by dots)
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "[REDACTED:jwt]",
    ),
    # Bearer tokens in headers
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9_\-.]{20,}"), "Bearer [REDACTED]"),
    # Authorization headers
    (
        "auth_header",
        re.compile(r"Authorization:\s*\S+\s+[A-Za-z0-9_\-.]{20,}"),
        "Authorization: [REDACTED]",
    ),
    # Database connection strings (postgres, mysql, mongodb, redis)
    (
        "db_connection",
        re.compile(
            r"(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s'\"`,)]+:[^\s'\"`,)]+@[^\s'\"`,)]+"
        ),
        r"\1://[REDACTED]@[REDACTED]",
    ),
    # URL passwords (user:pass@host pattern)
    ("url_password", re.compile(r"://([^:]+):([^@\s]{8,})@"), "://\\1:[REDACTED]@"),
    # .env style secrets (KEY=value on its own line)
    (
        "env_secret",
        re.compile(
            r"^((?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ACCESS_KEY|AUTH)\w*)\s*=\s*\S+",
            re.MULTILINE | re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
    # Private keys (PEM format)
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"
            r"[\s\S]*?"
            r"-----END (?:RSA |EC |DSA )?PRIVATE KEY-----"
        ),
        "[REDACTED:private_key]",
    ),
    # Long hex strings (64+ chars, likely secrets — but not git commit hashes which are 40 chars)
    ("hex_secret", re.compile(r"(?<![0-9a-f])[0-9a-f]{64,}(?![0-9a-f])"), "[REDACTED:hex_secret]"),
]


@dataclass
class ScrubResult:
    """Result of credential scrubbing."""

    text: str
    redaction_count: int = 0
    redacted_types: list[str] = field(default_factory=list)


def scrub_text(text: str) -> ScrubResult:
    """Scrub credentials from text, returning cleaned text and redaction info.

    Returns the original text unchanged if no credentials are found.
    Uses Rust native implementation when available (20-50x faster).
    """
    if _USE_NATIVE:
        result = _native_scrub_text(text)
        return ScrubResult(
            text=result.text,
            redaction_count=result.redaction_count,
            redacted_types=list(result.redacted_types),
        )

    redaction_count = 0
    redacted_types: list[str] = []

    for name, pattern, replacement in CREDENTIAL_PATTERNS:
        new_text, count = pattern.subn(replacement, text)
        if count > 0:
            text = new_text
            redaction_count += count
            if name not in redacted_types:
                redacted_types.append(name)

    return ScrubResult(text=text, redaction_count=redaction_count, redacted_types=redacted_types)


def scrub_credentials(text: str) -> str:
    """Replace known credential patterns with redaction placeholders.

    Convenience wrapper around :func:`scrub_text` that returns just the
    cleaned string. Safe to call on any input including ``None`` or empty
    strings.
    """
    if not text:
        return text
    if _USE_NATIVE:
        return _native_scrub_credentials(text)
    return scrub_text(text).text


def has_credentials(text: str) -> bool:
    """Quick check — does this text contain any credential pattern?"""
    if not text:
        return False
    if _USE_NATIVE:
        return _native_has_credentials(text)
    return any(pattern.search(text) for _, pattern, _ in CREDENTIAL_PATTERNS)
