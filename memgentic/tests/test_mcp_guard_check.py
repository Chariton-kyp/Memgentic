"""Tests for the ``memgentic_guard_check`` MCP self-check tool.

Reuses the seeded-git-repo fixture pattern from ``test_guard_engine.py`` so the
tool is exercised against real diffs, not mocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memgentic.mcp.server import GuardCheckInput, memgentic_guard_check

RULES = """\
rules:
  - id: core-import-direction
    type: import_direction
    scope: "memgentic/memgentic/**"
    targets: ["memgentic_api", "dashboard"]
    message: "Core must never import from api/dashboard."
    source: "CLAUDE.md"
"""


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    (repo / "memgentic" / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "decisions.yaml").write_text(RULES, encoding="utf-8")
    (repo / "memgentic" / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    _git(repo, "add", "decisions.yaml", "memgentic/memgentic/x.py")
    _git(repo, "commit", "-m", "base")


@pytest.fixture
def ctx():
    """A throwaway Context — the guard tool never touches it."""
    return MagicMock()


@pytest.fixture
def violating_repo(tmp_path):
    """Repo whose feat branch adds a forbidden ``import memgentic_api`` in core."""
    repo = tmp_path / "v"
    _init_repo(repo)
    _git(repo, "checkout", "-b", "feat")
    (repo / "memgentic" / "memgentic" / "x.py").write_text(
        "import os\nimport memgentic_api\n", encoding="utf-8"
    )
    _git(repo, "add", "memgentic/memgentic/x.py")
    _git(repo, "commit", "-m", "violate")
    return repo


@pytest.fixture
def clean_repo(tmp_path):
    """Repo whose feat branch makes only an allowed change."""
    repo = tmp_path / "c"
    _init_repo(repo)
    _git(repo, "checkout", "-b", "feat")
    (repo / "memgentic" / "memgentic" / "x.py").write_text(
        "import os\nimport sys\n", encoding="utf-8"
    )
    _git(repo, "add", "memgentic/memgentic/x.py")
    _git(repo, "commit", "-m", "clean")
    return repo


async def test_guard_check_reports_violations(violating_repo, ctx):
    result = await memgentic_guard_check(
        GuardCheckInput(repo=str(violating_repo), base="main"), ctx
    )
    assert result["passed"] is False
    assert result["violation_count"] == 1
    v = result["violations"][0]
    assert v["rule_id"] == "core-import-direction"
    assert v["file"] == "memgentic/memgentic/x.py"
    assert v["line"] == 2
    assert "memgentic_api" in v["snippet"]
    assert result["rules_path"].endswith("decisions.yaml")


async def test_guard_check_clean_repo_passes(clean_repo, ctx):
    result = await memgentic_guard_check(GuardCheckInput(repo=str(clean_repo), base="main"), ctx)
    assert result["passed"] is True
    assert result["violation_count"] == 0
    assert result["violations"] == []


async def test_guard_check_missing_rules_is_friendly(tmp_path, ctx):
    repo = tmp_path / "norules"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    result = await memgentic_guard_check(GuardCheckInput(repo=str(repo)), ctx)
    # No rules file -> friendly pass, not an error.
    assert result["passed"] is True
    assert result["violation_count"] == 0
    assert "error" not in result
    assert "No rules file" in result["message"]


async def test_guard_check_not_a_git_repo(tmp_path, ctx):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "decisions.yaml").write_text(RULES, encoding="utf-8")
    result = await memgentic_guard_check(GuardCheckInput(repo=str(plain)), ctx)
    assert result["passed"] is False
    assert "Not a git repository" in result["error"]


async def test_guard_check_staged(violating_repo, ctx):
    """A forbidden import sitting in the index is caught with staged=True."""
    # Stage a fresh violation on top of the existing feat branch.
    (violating_repo / "memgentic" / "memgentic" / "y.py").write_text(
        "import dashboard\n", encoding="utf-8"
    )
    _git(violating_repo, "add", "memgentic/memgentic/y.py")
    result = await memgentic_guard_check(
        GuardCheckInput(repo=str(violating_repo), staged=True), ctx
    )
    assert result["passed"] is False
    assert any(v["file"] == "memgentic/memgentic/y.py" for v in result["violations"])


async def test_guard_check_explicit_rules_path(violating_repo, ctx):
    """An explicit rules_path is honoured over the default location."""
    alt = violating_repo / "alt_rules.yaml"
    alt.write_text(RULES, encoding="utf-8")
    result = await memgentic_guard_check(
        GuardCheckInput(repo=str(violating_repo), base="main", rules_path=str(alt)), ctx
    )
    assert result["passed"] is False
    assert result["rules_path"].endswith("alt_rules.yaml")


WARN_RULES = """\
rules:
  - id: no-dapr
    type: forbidden_path
    targets: ["dapr/**"]
    message: "dapr config is generated"
    severity: warn
"""


async def test_guard_check_warn_only_passes_with_severity(tmp_path, ctx):
    """Warn-only violations: passed=True, but the violation is still reported
    with its severity."""
    repo = tmp_path / "w"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "decisions.yaml").write_text(WARN_RULES, encoding="utf-8")
    (repo / "readme.txt").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "decisions.yaml", "readme.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "feat")
    (repo / "dapr").mkdir()
    (repo / "dapr" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    _git(repo, "add", "dapr/config.yaml")
    _git(repo, "commit", "-m", "add dapr config")

    result = await memgentic_guard_check(GuardCheckInput(repo=str(repo), base="main"), ctx)
    assert result["passed"] is True  # warn-only does not fail
    assert result["violation_count"] == 1
    assert result["violations"][0]["severity"] == "warn"
    assert result["violations"][0]["file"] == "dapr/config.yaml"
