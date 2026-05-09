"""Unit tests for project-key derivation across path styles."""

from __future__ import annotations

import pytest

from memgentic.processing.project import (
    derive_project,
    normalize_project,
    project_from_claude_code_slug,
    project_from_cwd,
)


class TestNormalizeProject:
    def test_empty_returns_empty(self) -> None:
        assert normalize_project(None) == ""
        assert normalize_project("") == ""
        assert normalize_project("   ") == ""

    def test_lowercases(self) -> None:
        assert normalize_project("MemgenticPublic") == "memgenticpublic"

    def test_collapses_separators(self) -> None:
        assert normalize_project("foo_bar baz") == "foo-bar-baz"
        assert normalize_project("foo//bar\\\\baz") == "foo-bar-baz"

    def test_collapses_repeated_dashes(self) -> None:
        assert normalize_project("foo---bar") == "foo-bar"

    def test_strips_outer_dashes(self) -> None:
        assert normalize_project("--foo-bar--") == "foo-bar"


class TestProjectFromCwd:
    def test_windows_path(self) -> None:
        cwd = r"C:\Users\harit\Desktop\Business_Projects\memgentic-public-export"
        assert project_from_cwd(cwd) == "memgentic-public-export"

    def test_posix_path(self) -> None:
        assert project_from_cwd("/home/harit/projects/Vetervo") == "vetervo"

    def test_trailing_separator(self) -> None:
        assert project_from_cwd(r"C:\Users\harit\Desktop\Business_Projects\Inproma\\") == "inproma"

    def test_quoted_path(self) -> None:
        assert project_from_cwd('"C:\\Users\\harit\\Desktop\\EllinAI"') == "ellinai"

    def test_underscore_normalised(self) -> None:
        assert (
            project_from_cwd(r"C:\Users\harit\Desktop\Business_Projects\Scribble_Vet")
            == "scribble-vet"
        )

    def test_empty_returns_empty(self) -> None:
        assert project_from_cwd(None) == ""
        assert project_from_cwd("") == ""
        assert project_from_cwd("   ") == ""


class TestProjectFromClaudeCodeSlug:
    def test_strips_known_business_projects_prefix(self) -> None:
        slug = "C--Users-harit-Desktop-Business-Projects-memgentic-public-export"
        assert project_from_claude_code_slug(slug) == "memgentic-public-export"

    def test_strips_known_desktop_prefix(self) -> None:
        slug = "C--Users-harit-Desktop-Inproma"
        assert project_from_claude_code_slug(slug) == "inproma"

    def test_strips_users_prefix(self) -> None:
        slug = "C--Users-harit-something"
        assert project_from_claude_code_slug(slug) == "something"

    def test_home_prefix(self) -> None:
        assert project_from_claude_code_slug("home-harit-projects-vetervo") == "vetervo"

    def test_unknown_prefix_falls_through(self) -> None:
        # No recognised prefix → keep as-is (lowercased).
        assert project_from_claude_code_slug("standalone-project") == "standalone-project"

    def test_empty(self) -> None:
        assert project_from_claude_code_slug(None) == ""
        assert project_from_claude_code_slug("") == ""


class TestDeriveProject:
    def test_cwd_wins_over_slug(self) -> None:
        out = derive_project(
            cwd=r"C:\Users\harit\Desktop\Business_Projects\memgentic-public-export",
            slug="C--Users-harit-Desktop-Business-Projects-different-name",
        )
        assert out == "memgentic-public-export"

    def test_slug_used_when_no_cwd(self) -> None:
        out = derive_project(
            slug="C--Users-harit-Desktop-Business-Projects-Vetervo",
        )
        assert out == "vetervo"

    def test_extracts_slug_from_file_path(self) -> None:
        out = derive_project(
            file_path=(
                "C:/Users/harit/.claude/projects/"
                "C--Users-harit-Desktop-Business-Projects-Inproma/"
                "abc123.jsonl"
            ),
        )
        assert out == "inproma"

    def test_returns_empty_when_no_signal(self) -> None:
        assert derive_project() == ""
        assert derive_project(file_path="/some/random/file.jsonl") == ""

    @pytest.mark.parametrize(
        "cwd,expected",
        [
            (
                r"C:\Users\harit\Desktop\Business_Projects\memgentic-public-export",
                "memgentic-public-export",
            ),
            (r"C:\Users\harit\Desktop\Business_Projects\Vetervo", "vetervo"),
            ("/home/harit/projects/EllinAI", "ellinai"),
            ("/Users/harit/code/ScribbleVet", "scribblevet"),
        ],
    )
    def test_canonical_keys(self, cwd: str, expected: str) -> None:
        assert derive_project(cwd=cwd) == expected
