"""Tests for credential scrubbing."""

from memgentic.processing.scrubber import has_credentials, scrub_credentials, scrub_text


def test_openai_key():
    result = scrub_text("Use key sk-proj-abc123xyz456def789ghijk to call the API")
    assert "sk-proj-abc123xyz456def789ghijk" not in result.text
    assert "[REDACTED:api_key]" in result.text
    assert result.redaction_count >= 1


def test_aws_access_key():
    result = scrub_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert result.redaction_count >= 1


def test_github_token():
    result = scrub_text("Use ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx1234 for auth")
    assert "ghp_" not in result.text
    assert "[REDACTED:github_token]" in result.text


def test_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = scrub_text(f"Token: {jwt}")
    assert "eyJ" not in result.text
    assert "[REDACTED:jwt]" in result.text


def test_bearer_token():
    result = scrub_text("Authorization: Bearer eyJhbGciOi_very_long_token_value_here")
    assert "Bearer [REDACTED]" in result.text


def test_database_connection_string():
    result = scrub_text("DATABASE_URL=postgres://admin:secretpass123@db.example.com:5432/mydb")
    assert "secretpass123" not in result.text
    assert "REDACTED" in result.text


def test_url_password():
    result = scrub_text("Connect to redis://user:MyS3cretP@ss@redis.example.com:6379")
    assert "MyS3cretP@ss" not in result.text
    assert "[REDACTED]" in result.text


def test_env_secret():
    text = "Set this:\nAPI_KEY=sk_live_abc123def456\nDEBUG=true"
    result = scrub_text(text)
    assert "sk_live_abc123def456" not in result.text
    assert "DEBUG=true" in result.text  # Non-secret preserved


def test_private_key():
    text = "Here's the key:\n-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg...\n-----END PRIVATE KEY-----\n"
    result = scrub_text(text)
    assert "MIIEvQIBADANBg" not in result.text
    assert "[REDACTED:private_key]" in result.text


def test_anthropic_key():
    result = scrub_text("ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijk123456")
    assert "sk-ant-" not in result.text


def test_google_api_key():
    # Synthetic test fixture — not a real API key.  # pragma: allowlist secret
    result = scrub_text("key=AIzaSy" + "X" * 33)
    assert "AIzaSy" not in result.text


def test_no_false_positive_on_normal_text():
    text = "Python is great for building APIs. Use FastAPI for async web servers."
    result = scrub_text(text)
    assert result.text == text
    assert result.redaction_count == 0
    assert result.redacted_types == []


def test_no_false_positive_on_short_hex():
    # Git commit hashes (40 chars) should NOT be scrubbed
    text = "Commit abc123def456abc123def456abc123def456abc1 merged."
    result = scrub_text(text)
    assert result.redaction_count == 0  # 40 chars < 64 threshold


def test_multiple_credentials():
    text = "Use sk-proj-abc123xyz456def789ghijk and ghp_token123456789012345678901234567890ab"
    result = scrub_text(text)
    assert result.redaction_count >= 2
    assert "openai_key" in result.redacted_types or "openai_proj" in result.redacted_types
    assert "github_token" in result.redacted_types


def test_scrub_result_types():
    result = scrub_text("Bearer my_super_secret_token_value_here_123")
    assert isinstance(result.redacted_types, list)
    assert isinstance(result.redaction_count, int)
    assert isinstance(result.text, str)


def test_scrub_credentials_wrapper_redacts():
    out = scrub_credentials("Use sk-proj-abc123xyz456def789ghijk for the API")
    assert "sk-proj-" not in out
    assert "REDACTED" in out


def test_scrub_credentials_empty_string():
    assert scrub_credentials("") == ""


def test_scrub_credentials_none_safe():
    assert scrub_credentials(None) is None  # type: ignore[arg-type]


def test_has_credentials_detects_key():
    assert has_credentials("token sk-proj-abc123xyz456def789ghijk here") is True


def test_has_credentials_false_on_clean_text():
    assert has_credentials("We decided to use PostgreSQL for storage") is False


def test_has_credentials_empty_safe():
    assert has_credentials("") is False
    assert has_credentials(None) is False  # type: ignore[arg-type]
