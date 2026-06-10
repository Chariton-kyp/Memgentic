"""CLI tests for the guard command."""

import subprocess

import pytest
from click.testing import CliRunner

from memgentic.cli import main


def _run(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo_with_rules(tmp_path):
    repo = tmp_path / "r"
    (repo / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    (repo / "decisions.yaml").write_text(
        'rules:\n  - id: d\n    type: import_direction\n    scope: "memgentic/**"\n'
        '    targets: ["memgentic_api"]\n    message: "no api"\n',
        encoding="utf-8",
    )
    _run(repo, "add", "memgentic/x.py", "decisions.yaml")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    return repo


def test_clean_branch_exit_0(repo_with_rules):
    (repo_with_rules / "memgentic" / "x.py").write_text("import os\nimport sys\n", encoding="utf-8")
    _run(repo_with_rules, "add", "memgentic/x.py")
    _run(repo_with_rules, "commit", "-m", "clean")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo_with_rules), "--base", "main"])
    assert res.exit_code == 0


def test_violation_exit_1(repo_with_rules):
    (repo_with_rules / "memgentic" / "x.py").write_text(
        "import os\nimport memgentic_api\n", encoding="utf-8"
    )
    _run(repo_with_rules, "add", "memgentic/x.py")
    _run(repo_with_rules, "commit", "-m", "bad")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo_with_rules), "--base", "main"])
    assert res.exit_code == 1
    assert "memgentic/x.py" in res.output


def test_violation_json_format(repo_with_rules):
    (repo_with_rules / "memgentic" / "x.py").write_text(
        "import os\nimport memgentic_api\n", encoding="utf-8"
    )
    _run(repo_with_rules, "add", "memgentic/x.py")
    _run(repo_with_rules, "commit", "-m", "bad")
    res = CliRunner().invoke(
        main, ["guard", "--repo", str(repo_with_rules), "--base", "main", "--format", "json"]
    )
    assert res.exit_code == 1
    assert '"violation_count": 1' in res.output


def test_not_a_repo_exit_2(tmp_path):
    res = CliRunner().invoke(main, ["guard", "--repo", str(tmp_path)])
    assert res.exit_code == 2
    assert "Not a git repository" in res.output


def test_rules_subcommand_lists_rules(repo_with_rules):
    res = CliRunner().invoke(main, ["guard", "rules", "--repo", str(repo_with_rules)])
    assert res.exit_code == 0
    assert "import_direction" in res.output


def test_rules_malformed_yaml_exit_2(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: [unclosed", encoding="utf-8")
    res = CliRunner().invoke(main, ["guard", "rules", "--repo", str(tmp_path), "--rules", str(bad)])
    assert res.exit_code == 2


def test_invalid_rule_with_markup_id_exits_2(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _run(repo, "add", "f.txt")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    (repo / "f.txt").write_text("xy", encoding="utf-8")
    _run(repo, "add", "f.txt")
    _run(repo, "commit", "-m", "c2")
    bad = repo / "d.yaml"
    bad.write_text(
        'rules:\n  - id: "bad[/x]rule"\n    type: not_a_real_type\n'
        '    targets: ["x"]\n    message: "m"\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        main, ["guard", "--repo", str(repo), "--base", "main", "--rules", str(bad)]
    )
    assert res.exit_code == 2


# ---------------------------------------------------------------------------
# BUG B: explicit --rules <missing path> must exit 2, not 0
# ---------------------------------------------------------------------------


def test_explicit_missing_rules_exits_2(tmp_path):
    """Explicitly-supplied --rules path that doesn't exist must exit 2."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    res = CliRunner().invoke(
        main, ["guard", "--repo", str(repo), "--rules", str(tmp_path / "nope.yaml")]
    )
    assert res.exit_code == 2


def test_default_missing_rules_exits_0(tmp_path):
    """Default (no --rules flag) missing decisions.yaml must silently exit 0."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo)])
    assert res.exit_code == 0


def test_explicit_missing_rules_on_guard_rules_exits_2(tmp_path):
    """'guard rules' with an explicit missing --rules must exit 2."""
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    res = CliRunner().invoke(
        main, ["guard", "rules", "--repo", str(repo), "--rules", str(tmp_path / "nope.yaml")]
    )
    assert res.exit_code == 2


# ---------------------------------------------------------------------------
# ITEM 1 — missing default base 'main' must hint --base
# ---------------------------------------------------------------------------


def test_master_only_repo_hints_base_flag(tmp_path):
    """When 'main' doesn't exist and --base was not passed, the error must hint --base."""
    repo = tmp_path / "m"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    (repo / "decisions.yaml").write_text(
        'rules:\n  - id: d\n    type: banned_import\n    targets: ["httpx"]\n    message: "m"\n',
        encoding="utf-8",
    )
    _run(repo, "add", "a.txt", "decisions.yaml")
    _run(repo, "commit", "-m", "base")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo)])
    assert res.exit_code == 2
    assert "--base" in res.output
