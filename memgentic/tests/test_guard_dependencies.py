"""Tests for the banned-dependency guard check."""

from memgentic.guard.checks.dependencies import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(
    id="no-langchain-core",
    type="banned_dependency",
    scope="memgentic/pyproject.toml",
    targets=["langchain-core"],
    message="LLM stack belongs in [intelligence]",
)


def test_fires_on_added_dependency_line():
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={42: '    "langchain-core>=1.2",'})
    assert len(check(RULE, [df], lambda p: None)) == 1


def test_no_fp_on_unrelated_added_line():
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={42: '    "rich>=14.0",'})
    assert check(RULE, [df], lambda p: None) == []


def test_no_fp_on_substring_dependency():
    # 'langchain-core-extras' must NOT match a ban on 'langchain-core'
    df = DiffFile(
        path="memgentic/pyproject.toml", added_lines={42: '    "langchain-core-extras>=1",'}
    )
    assert check(RULE, [df], lambda p: None) == []


def test_no_fp_in_toml_comment():
    df = DiffFile(
        path="memgentic/pyproject.toml", added_lines={42: "    # langchain-core is banned here"}
    )
    assert check(RULE, [df], lambda p: None) == []


def test_only_in_scoped_manifest():
    df = DiffFile(path="other/pyproject.toml", added_lines={1: '    "langchain-core>=1",'})
    assert check(RULE, [df], lambda p: None) == []


def test_fires_in_package_json():
    rule = GuardRule(
        id="no-lodash",
        type="banned_dependency",
        scope="**",
        targets=["lodash"],
        message="no lodash",
    )
    df = DiffFile(path="frontend/package.json", added_lines={5: '    "lodash": "^4.17.21",'})
    assert len(check(rule, [df], lambda p: None)) == 1


def test_requirements_vcs_egg_not_truncated():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    df = DiffFile(
        path="requirements.txt", added_lines={1: "git+https://x.com/repo.git#egg=langchain-core"}
    )
    assert len(check(rule, [df], lambda p: None)) == 1


def test_wildcard_scope_matches_any_manifest():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={1: '    "langchain-core>=1",'})
    assert len(check(rule, [df], lambda p: None)) == 1


def test_no_fp_on_dependency_in_optional_extra():
    blob = (
        '[project]\ndependencies = ["rich>=14"]\n'
        '[project.optional-dependencies]\nintelligence = ["langchain-core>=1.2"]\n'
    )
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={4: '    "langchain-core>=1.2",'})
    assert check(RULE, [df], lambda p: blob) == []  # langchain-core only in the extra → no fire


def test_fires_when_dependency_in_core():
    blob = '[project]\ndependencies = ["rich>=14", "langchain-core>=1.2"]\n'
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={2: '    "langchain-core>=1.2",'})
    assert len(check(RULE, [df], lambda p: blob)) == 1


def test_requirements_still_fires_without_blob():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    df = DiffFile(path="requirements.txt", added_lines={1: "langchain-core>=1.2"})
    assert len(check(rule, [df], lambda p: None)) == 1


def test_matches_case_and_separator_variants():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    for variant in ["Langchain-Core>=1", "langchain_core>=1", "LANGCHAIN.CORE>=1"]:
        df = DiffFile(path="requirements.txt", added_lines={1: variant})
        assert len(check(rule, [df], lambda p: None)) == 1, variant
    # substring test still does NOT match
    df2 = DiffFile(path="requirements.txt", added_lines={1: "langchain-core-extras>=1"})
    assert check(rule, [df2], lambda p: None) == []


# ---------------------------------------------------------------------------
# BUG A: base-side check for dependencies
# ---------------------------------------------------------------------------


def test_no_fire_when_banned_dep_already_in_base():
    """A version-bump of an already-present banned dep must NOT fire."""
    # base has langchain-core in [project.dependencies] → it's pre-existing
    base_blob = '[project]\ndependencies = ["langchain-core>=1.0"]\n'
    # new has a bumped version
    new_blob = '[project]\ndependencies = ["langchain-core>=1.2"]\n'
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={2: '"langchain-core>=1.2"'})
    assert check(RULE, [df], lambda p: new_blob, base_blob_getter=lambda p: base_blob) == []


def test_fires_when_banned_dep_is_new_vs_base():
    """A newly-added banned dep (not in base at all) must fire."""
    # base has only rich; new adds langchain-core to [project.dependencies]
    base_blob = '[project]\ndependencies = ["rich>=14"]\n'
    new_blob = '[project]\ndependencies = ["rich>=14", "langchain-core>=1.2"]\n'
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={2: '"langchain-core>=1.2"'})
    assert len(check(RULE, [df], lambda p: new_blob, base_blob_getter=lambda p: base_blob)) == 1


# ---------------------------------------------------------------------------
# BUG C: pyproject with no [project.dependencies] (Poetry-style)
# ---------------------------------------------------------------------------


def test_poetry_style_pyproject_falls_back_to_fire():
    """A pyproject.toml with no [project.dependencies] section must still fire."""
    blob = '[tool.poetry.dependencies]\npython = "^3.12"\nlangchain-core = "^1.2"\n'
    rule = GuardRule(
        id="no-lc",
        type="banned_dependency",
        scope="pyproject.toml",
        targets=["langchain-core"],
        message="x",
    )
    df = DiffFile(path="pyproject.toml", added_lines={3: 'langchain-core = "^1.2"'})
    assert len(check(rule, [df], lambda p: blob)) == 1


# ---------------------------------------------------------------------------
# ITEM 3 — package.json section-awareness for the CORE check
# ---------------------------------------------------------------------------


def test_package_json_dev_dependency_does_not_fire():
    blob = '{"dependencies": {"react": "^19"}, "devDependencies": {"lodash": "^4"}}'
    rule = GuardRule(
        id="no-lodash", type="banned_dependency", scope="**", targets=["lodash"], message="x"
    )
    df = DiffFile(path="package.json", added_lines={3: '    "lodash": "^4",'})
    assert check(rule, [df], lambda p: blob) == []


def test_package_json_core_dependency_fires():
    blob = '{"dependencies": {"lodash": "^4"}}'
    rule = GuardRule(
        id="no-lodash", type="banned_dependency", scope="**", targets=["lodash"], message="x"
    )
    df = DiffFile(path="package.json", added_lines={2: '    "lodash": "^4",'})
    assert len(check(rule, [df], lambda p: blob)) == 1


# ---------------------------------------------------------------------------
# ITEM 4 — base-side suppression for requirements.txt + package.json
# ---------------------------------------------------------------------------


def test_requirements_version_bump_does_not_fire():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    df = DiffFile(path="requirements.txt", added_lines={1: "langchain-core>=1.3"})

    def base_with_lc(p: str) -> str:
        return "langchain-core>=1.2\nrich>=14\n"

    assert check(rule, [df], lambda p: None, base_blob_getter=base_with_lc) == []


def test_requirements_new_banned_dep_fires_with_base():
    rule = GuardRule(
        id="no-lc", type="banned_dependency", scope="**", targets=["langchain-core"], message="x"
    )
    df = DiffFile(path="requirements.txt", added_lines={2: "langchain-core>=1.3"})

    def base_without_lc(p: str) -> str:
        return "rich>=14\n"

    assert len(check(rule, [df], lambda p: None, base_blob_getter=base_without_lc)) == 1


def test_package_json_version_bump_does_not_fire():
    rule = GuardRule(
        id="no-lodash", type="banned_dependency", scope="**", targets=["lodash"], message="x"
    )
    new_blob = '{"dependencies": {"lodash": "^4.17.21"}}'
    base_blob = '{"dependencies": {"lodash": "^4.17.20"}}'
    df = DiffFile(path="package.json", added_lines={2: '    "lodash": "^4.17.21",'})
    assert check(rule, [df], lambda p: new_blob, base_blob_getter=lambda p: base_blob) == []
