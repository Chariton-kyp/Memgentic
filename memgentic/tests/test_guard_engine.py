"""Integration tests for the guard engine."""
import subprocess
from pathlib import Path

import pytest

from memgentic.guard.engine import load_rules, run

FIXTURE = Path(__file__).parent / "fixtures" / "guard" / "decisions.yaml"


def _run(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True)


@pytest.fixture
def seeded_repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "memgentic" / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "memgentic" / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    _run(repo, "add", "memgentic/memgentic/x.py")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    (repo / "memgentic" / "memgentic" / "x.py").write_text(
        "import os\nimport memgentic_api\n", encoding="utf-8")
    _run(repo, "add", "memgentic/memgentic/x.py")
    _run(repo, "commit", "-m", "violate")
    return repo


def test_load_rules():
    rules = load_rules(FIXTURE)
    assert {r.id for r in rules} == {"core-import-direction", "no-langchain-in-core"}


def test_engine_fires_on_seeded_import_direction(seeded_repo):
    rules = load_rules(FIXTURE)
    violations = run(seeded_repo, rules, base="main", staged=False)
    assert any(v.rule_id == "core-import-direction" and v.file == "memgentic/memgentic/x.py"
               for v in violations)


def test_engine_clean_branch_no_violations(tmp_path):
    repo = tmp_path / "c"
    (repo / "memgentic" / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "memgentic" / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    _run(repo, "add", "memgentic/memgentic/x.py")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    (repo / "memgentic" / "memgentic" / "x.py").write_text(
        "import os\nimport sys\n", encoding="utf-8")
    _run(repo, "add", "memgentic/memgentic/x.py")
    _run(repo, "commit", "-m", "clean change")
    rules = load_rules(FIXTURE)
    assert run(repo, rules, base="main", staged=False) == []


def test_checks_cover_all_rule_types():
    from memgentic.guard.engine import _CHECKS
    from memgentic.models import GuardRuleType
    assert set(_CHECKS) == set(GuardRuleType)


def test_engine_fires_on_seeded_banned_dependency(tmp_path):
    repo = tmp_path / "d"
    (repo / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    base = '[project]\ndependencies = [\n    "rich>=14",\n]\n'
    (repo / "memgentic" / "pyproject.toml").write_text(base, encoding="utf-8")
    _run(repo, "add", "memgentic/pyproject.toml")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    bad = '[project]\ndependencies = [\n    "rich>=14",\n    "langchain-core>=1",\n]\n'
    (repo / "memgentic" / "pyproject.toml").write_text(bad, encoding="utf-8")
    _run(repo, "add", "memgentic/pyproject.toml")
    _run(repo, "commit", "-m", "add dep")
    out = run(repo, load_rules(FIXTURE), base="main", staged=False)
    assert any(v.rule_id == "no-langchain-in-core" for v in out)


def test_load_rules_reports_bad_rule_id(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text('rules:\n  - id: oops\n    type: not_a_real_type\n    targets: ["x"]\n    message: "m"\n',
                   encoding="utf-8")
    with pytest.raises(ValueError, match="oops"):
        load_rules(bad)
