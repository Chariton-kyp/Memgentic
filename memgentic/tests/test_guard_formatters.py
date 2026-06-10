"""Tests for guard output formatters."""

import json

from memgentic.guard.formatters import format_json, format_text
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
