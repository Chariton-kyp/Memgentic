"""Tests for Guard data models."""

import pytest
from pydantic import ValidationError

from memgentic.models import GuardRule, GuardRuleType, Violation


def test_guard_rule_defaults_and_strip():
    r = GuardRule(
        id="core-import-direction",
        type="import_direction",
        targets=["memgentic_api"],
        message="  core must not import api  ",
    )
    assert r.type is GuardRuleType.IMPORT_DIRECTION
    assert r.scope == "**"
    assert r.severity == "error"
    assert r.source == "decisions.yaml"
    assert r.message == "core must not import api"  # str_strip_whitespace


def test_violation_optional_fields():
    v = Violation(rule_id="r1", message="bad", file="a.py")
    assert v.line is None and v.snippet is None

    v2 = Violation(rule_id="r1", message="bad", file="a.py", line=42, snippet="import foo")
    assert v2.line == 42 and v2.snippet == "import foo"


# ---------------------------------------------------------------------------
# HARDENING: empty targets must be rejected at construction time
# ---------------------------------------------------------------------------


def test_empty_targets_rejected():
    """GuardRule with targets=[] must raise a validation error."""
    with pytest.raises(ValidationError):
        GuardRule(id="x", type="banned_import", targets=[], message="m")


# ---------------------------------------------------------------------------
# C# / forbidden-path additions
# ---------------------------------------------------------------------------


def test_forbidden_path_rule_type_exists():
    """The forbidden_path rule type must be loadable from a decisions file."""
    r = GuardRule(
        id="no-env",
        type="forbidden_path",
        targets=["**/.env"],
        message="never commit secrets",
    )
    assert r.type is GuardRuleType.FORBIDDEN_PATH
    assert r.type.value == "forbidden_path"


def test_violation_severity_defaults_to_error():
    """Violation.severity defaults to 'error' for backward compatibility."""
    v = Violation(rule_id="r1", message="bad", file="a.py")
    assert v.severity == "error"


def test_violation_severity_accepts_warn():
    v = Violation(rule_id="r1", message="bad", file="a.py", severity="warn")
    assert v.severity == "warn"
