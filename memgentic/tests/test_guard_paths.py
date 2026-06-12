"""Tests for the forbidden_path guard check."""

from __future__ import annotations

from memgentic.guard.checks import paths
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule


def _rule(targets, scope="**", severity="error", message="forbidden path"):
    return GuardRule(
        id="no-path",
        type="forbidden_path",
        scope=scope,
        targets=targets,
        message=message,
        severity=severity,
    )


def _noblob(_path):
    return None


def test_fires_on_matching_path():
    rule = _rule(["**/.env"])
    df = DiffFile(path="config/.env", added_lines={1: "SECRET=abc"})
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1
    v = out[0]
    assert v.file == "config/.env"
    assert v.line is None
    assert v.snippet is None
    assert v.message == "forbidden path"
    assert v.rule_id == "no-path"


def test_fires_on_top_level_dotenv():
    rule = _rule(["**/.env"])
    df = DiffFile(path=".env", added_lines={1: "X=1"})
    # fnmatch '*' crosses '/', so '**/.env' matches a bare '.env' too.
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1


def test_does_not_fire_on_env_example():
    """'**/.env' must NOT match '.env.example' — different basename."""
    rule = _rule(["**/.env"])
    df = DiffFile(path=".env.example", added_lines={1: "X=1"})
    assert paths.check(rule, [df], _noblob) == []


def test_does_not_fire_on_env_example_in_subdir():
    rule = _rule(["**/.env"])
    df = DiffFile(path="config/.env.example", added_lines={1: "X=1"})
    assert paths.check(rule, [df], _noblob) == []


def test_dir_glob_target_matches_descendants():
    rule = _rule(["dapr/**"])
    df = DiffFile(path="dapr/components/redis.yaml", added_lines={1: "x"})
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1
    assert out[0].file == "dapr/components/redis.yaml"


def test_dir_glob_does_not_match_unrelated():
    rule = _rule(["dapr/**"])
    df = DiffFile(path="src/dapr_helper.py", added_lines={1: "x"})
    assert paths.check(rule, [df], _noblob) == []


def test_fires_on_deleted_file():
    """Deleting a forbidden path still fires — the rule means 'never touch'."""
    rule = _rule(["**/.env"])
    df = DiffFile(path=".env", is_deleted=True)
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1


def test_fires_on_binary_file():
    """A committed forbidden path may be binary-ish; still fires."""
    rule = _rule(["**/.env"])
    df = DiffFile(path=".env", is_binary=True)
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1


def test_any_target_glob_fires():
    rule = _rule(["**/.env", "**/*.pem", "secrets/**"])
    df = DiffFile(path="certs/server.pem", added_lines={1: "x"})
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1


def test_scope_restricts_matching():
    """rule.scope still gates which files are considered."""
    rule = _rule(["**/*.yaml"], scope="dapr/**")
    inside = DiffFile(path="dapr/config.yaml", added_lines={1: "x"})
    outside = DiffFile(path="other/config.yaml", added_lines={1: "x"})
    out = paths.check(rule, [inside, outside], _noblob)
    assert len(out) == 1
    assert out[0].file == "dapr/config.yaml"


def test_no_match_no_violation():
    rule = _rule(["**/.env"])
    df = DiffFile(path="src/main.py", added_lines={1: "x"})
    assert paths.check(rule, [df], _noblob) == []


def test_severity_copied_from_rule():
    rule = _rule(["dapr/**"], severity="warn")
    df = DiffFile(path="dapr/config.yaml", added_lines={1: "x"})
    out = paths.check(rule, [df], _noblob)
    assert out[0].severity == "warn"


def test_base_blob_getter_ignored_for_suppression():
    """Touching a forbidden path is always reportable; base side is ignored."""
    rule = _rule(["**/.env"])
    df = DiffFile(path=".env", added_lines={1: "X=1"})

    def base_getter(_path):
        return "X=0"  # pre-existing — must NOT suppress

    out = paths.check(rule, [df], _noblob, base_blob_getter=base_getter)
    assert len(out) == 1


def test_one_violation_per_file_even_if_multiple_targets_match():
    rule = _rule(["**/.env", "**/*"])
    df = DiffFile(path=".env", added_lines={1: "X=1"})
    out = paths.check(rule, [df], _noblob)
    assert len(out) == 1
