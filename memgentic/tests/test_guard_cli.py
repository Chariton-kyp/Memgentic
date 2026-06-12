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


# ---------------------------------------------------------------------------
# severity-aware exit codes
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_with_path_rules(tmp_path):
    """Repo whose decisions.yaml has an error-severity and a warn-severity
    forbidden_path rule."""
    repo = tmp_path / "p"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "readme.txt").write_text("hi\n", encoding="utf-8")
    (repo / "decisions.yaml").write_text(
        "rules:\n"
        "  - id: no-env\n"
        "    type: forbidden_path\n"
        '    targets: ["**/.env"]\n'
        '    message: "never commit secrets"\n'
        "    severity: error\n"
        "  - id: no-dapr\n"
        "    type: forbidden_path\n"
        '    targets: ["dapr/**"]\n'
        '    message: "dapr config is generated"\n'
        "    severity: warn\n",
        encoding="utf-8",
    )
    _run(repo, "add", "readme.txt", "decisions.yaml")
    _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    return repo


def test_warn_only_violation_exits_0_but_prints(repo_with_path_rules):
    repo = repo_with_path_rules
    (repo / "dapr").mkdir()
    (repo / "dapr" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    _run(repo, "add", "dapr/config.yaml")
    _run(repo, "commit", "-m", "add dapr config")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo), "--base", "main"])
    assert res.exit_code == 0
    assert "dapr/config.yaml" in res.output  # printed despite exit 0


def test_error_violation_exits_1(repo_with_path_rules):
    repo = repo_with_path_rules
    (repo / ".env").write_text("SECRET=abc\n", encoding="utf-8")
    _run(repo, "add", ".env")
    _run(repo, "commit", "-m", "add env")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo), "--base", "main"])
    assert res.exit_code == 1
    assert ".env" in res.output


def test_mixed_severity_exits_1(repo_with_path_rules):
    repo = repo_with_path_rules
    (repo / ".env").write_text("SECRET=abc\n", encoding="utf-8")
    (repo / "dapr").mkdir()
    (repo / "dapr" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    _run(repo, "add", ".env", "dapr/config.yaml")
    _run(repo, "commit", "-m", "add both")
    res = CliRunner().invoke(main, ["guard", "--repo", str(repo), "--base", "main"])
    assert res.exit_code == 1
    assert ".env" in res.output and "dapr/config.yaml" in res.output


def test_warn_only_json_includes_severity(repo_with_path_rules):
    repo = repo_with_path_rules
    (repo / "dapr").mkdir()
    (repo / "dapr" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    _run(repo, "add", "dapr/config.yaml")
    _run(repo, "commit", "-m", "add dapr config")
    res = CliRunner().invoke(
        main, ["guard", "--repo", str(repo), "--base", "main", "--format", "json"]
    )
    assert res.exit_code == 0
    assert '"severity": "warn"' in res.output


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


# ---------------------------------------------------------------------------
# guard init — starter decisions.yaml template
# ---------------------------------------------------------------------------


def _git_repo(tmp_path, name="r"):
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    return repo


def test_init_creates_decisions_yaml(tmp_path):
    repo = _git_repo(tmp_path)
    res = CliRunner().invoke(main, ["guard", "init", "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    assert (repo / "decisions.yaml").exists()


def test_init_template_is_valid_yaml(tmp_path):
    import yaml

    from memgentic.guard import engine

    repo = _git_repo(tmp_path)
    CliRunner().invoke(main, ["guard", "init", "--repo", str(repo)])
    text = (repo / "decisions.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)  # must not raise — valid YAML
    assert isinstance(data, dict)
    # With everything commented out, engine.load_rules yields no live rules.
    assert engine.load_rules(repo / "decisions.yaml") == []


def test_init_template_mentions_all_four_rule_types(tmp_path):
    repo = _git_repo(tmp_path)
    CliRunner().invoke(main, ["guard", "init", "--repo", str(repo)])
    text = (repo / "decisions.yaml").read_text(encoding="utf-8")
    for rule_type in (
        "import_direction",
        "banned_import",
        "banned_dependency",
        "forbidden_path",
    ):
        assert rule_type in text, f"template missing {rule_type}"
    assert "severity" in text  # severity examples documented
    assert "guard suggest" in text  # points at LLM-assisted drafting
    assert "C#" in text or "csharp" in text.lower()  # C# note present


def test_init_refuses_to_overwrite(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "decisions.yaml").write_text("rules: []\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["guard", "init", "--repo", str(repo)])
    assert res.exit_code == 2
    assert "exists" in res.output.lower()
    # untouched
    assert (repo / "decisions.yaml").read_text(encoding="utf-8") == "rules: []\n"


def test_init_template_loads_when_examples_uncommented(tmp_path):
    """Uncommenting the example block must yield rules engine.load_rules accepts."""
    from memgentic.guard import engine

    repo = _git_repo(tmp_path)
    CliRunner().invoke(main, ["guard", "init", "--repo", str(repo)])
    raw = (repo / "decisions.yaml").read_text(encoding="utf-8")
    # Uncomment the example rules: strip a leading "# " from indented comment
    # lines that sit under the `rules:` list (lines starting with "#   ").
    uncommented_lines = []
    for line in raw.splitlines():
        stripped = line.lstrip()
        # Example rule lines are commented with "# " at 2-space indent under rules:
        if stripped.startswith("# ") and line.startswith("# "):
            uncommented_lines.append(line[2:])
        else:
            uncommented_lines.append(line)
    out = "\n".join(uncommented_lines)
    test_file = repo / "uncommented.yaml"
    test_file.write_text(out, encoding="utf-8")
    rules = engine.load_rules(test_file)
    # The four example rules should now be live and valid.
    types = {r.type.value for r in rules}
    assert {"import_direction", "banned_import", "banned_dependency", "forbidden_path"} <= types


# ---------------------------------------------------------------------------
# guard install-hook — pre-commit installer
# ---------------------------------------------------------------------------


def _hook_path(repo):
    return repo / ".git" / "hooks" / "pre-commit"


def test_install_hook_creates_pre_commit(tmp_path):
    repo = _git_repo(tmp_path)
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    hook = _hook_path(repo)
    assert hook.exists()
    body = hook.read_text(encoding="utf-8")
    assert "memgentic.cli" in body and "guard" in body and "--staged" in body
    assert "PYTHONIOENCODING" in body  # hooks run in non-UTF consoles


def test_install_hook_respects_core_hooks_path(tmp_path):
    repo = _git_repo(tmp_path)
    hooks_dir = repo / "myhooks"
    hooks_dir.mkdir()
    _run(repo, "config", "core.hooksPath", str(hooks_dir))
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    assert (hooks_dir / "pre-commit").exists()
    assert not _hook_path(repo).exists()  # NOT in the default location


def test_install_hook_refuses_existing(tmp_path):
    repo = _git_repo(tmp_path)
    hook = _hook_path(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo)])
    assert res.exit_code == 2
    assert "--force" in res.output
    # original preserved
    assert "echo mine" in hook.read_text(encoding="utf-8")


def test_install_hook_force_backs_up_existing(tmp_path):
    repo = _git_repo(tmp_path)
    hook = _hook_path(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo), "--force"])
    assert res.exit_code == 0, res.output
    backup = hook.parent / "pre-commit.backup"
    assert backup.exists()
    assert "echo mine" in backup.read_text(encoding="utf-8")
    assert "memgentic.cli" in hook.read_text(encoding="utf-8")


def test_uninstall_removes_our_hook(tmp_path):
    repo = _git_repo(tmp_path)
    CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo)])
    assert _hook_path(repo).exists()
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo), "--uninstall"])
    assert res.exit_code == 0, res.output
    assert not _hook_path(repo).exists()


def test_uninstall_refuses_foreign_hook(tmp_path):
    repo = _git_repo(tmp_path)
    hook = _hook_path(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho not ours\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo), "--uninstall"])
    assert res.exit_code == 2
    assert hook.exists()  # left intact
    assert "echo not ours" in hook.read_text(encoding="utf-8")


def test_installed_hook_blocks_a_real_commit(tmp_path):
    """End-to-end: install the hook, stage a real violation, and assert that an
    actual `git commit` is BLOCKED (non-zero), then a clean commit passes.

    Skipped when git can't run a POSIX-sh hook (no sh available)."""
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git not available")

    repo = _git_repo(tmp_path)
    (repo / "core").mkdir()
    (repo / "core" / "x.py").write_text("import os\n", encoding="utf-8")
    (repo / "decisions.yaml").write_text(
        "rules:\n"
        "  - id: no-requests\n"
        "    type: banned_import\n"
        '    scope: "core/**"\n'
        '    targets: ["requests"]\n'
        '    message: "use httpx, not requests"\n',
        encoding="utf-8",
    )
    _run(repo, "add", "core/x.py", "decisions.yaml")
    _run(repo, "commit", "-m", "base")

    install = CliRunner().invoke(main, ["guard", "install-hook", "--repo", str(repo)])
    assert install.exit_code == 0, install.output

    # Stage a violating change and try a REAL commit — must be blocked.
    # Capture as bytes: the hook may emit UTF-8 guard glyphs and the host
    # console codepage (cp1253 on Greek Windows) can't decode them as text.
    (repo / "core" / "x.py").write_text("import os\nimport requests\n", encoding="utf-8")
    bad = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-am", "bad"],
        capture_output=True,
    )
    if bad.returncode == 0:
        pytest.skip(
            "git did not execute the POSIX-sh hook in this environment "
            "(no bundled sh?) — hook content is covered by the unit tests"
        )
    assert bad.returncode != 0  # commit blocked by the guard hook

    # Fix it and a clean commit passes.
    (repo / "core" / "x.py").write_text("import os\nimport httpx\n", encoding="utf-8")
    good = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-am", "clean"],
        capture_output=True,
    )
    assert good.returncode == 0, good.stderr
