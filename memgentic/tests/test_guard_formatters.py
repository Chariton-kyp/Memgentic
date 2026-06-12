"""Tests for guard output formatters."""

import io
import json

from memgentic.guard.formatters import (
    format_json,
    format_text,
    stream_supports_unicode,
)
from memgentic.models import Violation

V = [
    Violation(
        rule_id="r1",
        message="bad import",
        file="memgentic/x.py",
        line=2,
        snippet="import memgentic_api",
    )
]


def test_format_json_roundtrips():
    data = json.loads(format_json(V))
    assert data["violation_count"] == 1
    assert data["violations"][0]["file"] == "memgentic/x.py"
    assert data["violations"][0]["line"] == 2


def test_format_text_mentions_file_and_message():
    text = format_text(V)
    assert "memgentic/x.py" in text and "bad import" in text


def test_format_text_clean():
    text = format_text([])
    assert "0 violations" in text or "passed" in text.lower()


def test_format_json_clean():
    data = json.loads(format_json([]))
    assert data["violation_count"] == 0
    assert data["violations"] == []


def test_format_text_has_no_stdout_side_effect(capsys):
    format_text(V)
    assert capsys.readouterr().out == ""  # must not print; caller echoes the return value


def test_format_text_survives_markup_in_data():
    v = [Violation(rule_id="[/x]", message="bad", file="a.py", line=1, snippet="x = [not markup]")]
    out = format_text(v)  # must not raise
    assert "a.py" in out and "not markup" in out


# ---------------------------------------------------------------------------
# severity-aware formatting
# ---------------------------------------------------------------------------


def test_format_json_includes_severity():
    v = [Violation(rule_id="r", message="m", file="a.py", severity="warn")]
    data = json.loads(format_json(v))
    assert data["violations"][0]["severity"] == "warn"


def test_format_text_distinguishes_error_and_warn():
    v = [
        Violation(rule_id="e", message="an error", file="a.py", severity="error"),
        Violation(rule_id="w", message="a warning", file="b.py", severity="warn"),
    ]
    out = format_text(v)
    # error uses ✗, warn uses ⚠
    assert "✗" in out
    assert "⚠" in out
    assert "an error" in out and "a warning" in out


# ---------------------------------------------------------------------------
# Windows / cp1253 encoding safety (regression for the UnicodeEncodeError crash)
# ---------------------------------------------------------------------------


def _cp1253_stream() -> io.TextIOWrapper:
    """A strict cp1253 text stream — mirrors a Greek Windows console with no
    UTF-8 reconfigure. Writing any of the guard glyphs (✓ ✗ ⚠ —) to it raises
    UnicodeEncodeError unless the formatter emitted ASCII fallbacks."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1253", errors="strict", newline="")


def test_stream_supports_unicode_false_for_cp1253():
    assert stream_supports_unicode(_cp1253_stream()) is False


def test_stream_supports_unicode_true_for_utf8():
    assert stream_supports_unicode(_utf8_stream()) is True


def _utf8_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict", newline="")


def test_stream_supports_unicode_handles_missing_encoding():
    # A stream with no .encoding attribute must be treated as unsafe (ASCII).
    class _NoEncoding:
        pass

    assert stream_supports_unicode(_NoEncoding()) is False


def test_ascii_format_text_has_no_non_ascii_glyphs():
    v = [
        Violation(rule_id="e", message="an error", file="a.py", severity="error"),
        Violation(rule_id="w", message="a warning", file="b.py", severity="warn"),
    ]
    out = format_text(v, ascii_only=True)
    # No box-drawing / symbol glyphs that crash a cp1253 console.
    assert all(ord(c) < 128 for c in out), repr([c for c in out if ord(c) >= 128])
    assert "[X]" in out  # error marker
    assert "[WARN]" in out  # warn marker
    assert "an error" in out and "a warning" in out


def test_ascii_format_text_clean_is_pure_ascii():
    out = format_text([], ascii_only=True)
    assert all(ord(c) < 128 for c in out)
    assert "0 violations" in out


def test_ascii_format_text_writes_to_cp1253_stream_without_crashing():
    """The genuine bug: writing guard output to a strict cp1253 stream must not
    raise. With ascii_only=True the formatter emits only ASCII, so it survives."""
    v = [
        Violation(
            rule_id="r",
            message="use httpx instead",
            file="app.py",
            line=2,
            snippet="import requests",
        )
    ]
    out = format_text(v, ascii_only=True)
    stream = _cp1253_stream()
    stream.write(out)  # must not raise UnicodeEncodeError
    stream.flush()


def test_unicode_format_text_still_uses_glyphs_by_default():
    # Default (rich console / UTF-8) path keeps the pretty glyphs.
    v = [Violation(rule_id="e", message="m", file="a.py", severity="error")]
    out = format_text(v)
    assert "✗" in out
