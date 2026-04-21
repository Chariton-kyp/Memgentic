"""CLI integration tests for ``memgentic persona ...``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from click.testing import CliRunner

from memgentic.cli import main
from memgentic.persona.loader import PERSONA_ENV_VAR


@pytest.fixture
def persona_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "persona.yaml"
    monkeypatch.setenv(PERSONA_ENV_VAR, str(target))
    return target


def test_persona_help_lists_all_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "--help"])
    assert result.exit_code == 0
    for sub in (
        "init",
        "show",
        "edit",
        "validate",
        "path",
        "set",
        "add-person",
        "add-project",
    ):
        assert sub in result.output


def test_persona_path_prints_env_override(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "path"])
    assert result.exit_code == 0
    assert str(persona_file) in result.output


def test_persona_show_without_file_is_informative(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "show"])
    assert result.exit_code == 0
    assert "No persona file" in result.output


def test_persona_show_render_uses_default_when_missing(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "show", "--render"])
    assert result.exit_code == 0
    assert "Persona" in result.output
    assert "Assistant" in result.output


def test_persona_validate_missing_file(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "validate"])
    assert result.exit_code == 1


def test_persona_validate_invalid_file(persona_file: Path):
    persona_file.write_text("identity: {}\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "validate"])
    assert result.exit_code == 2
    assert "Invalid" in result.output


def test_persona_add_person_creates_file(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["persona", "add-person", "Alice", "--relationship", "creator"])
    assert result.exit_code == 0
    data = yaml.safe_load(persona_file.read_text(encoding="utf-8"))
    assert data["people"][0]["name"] == "Alice"
    assert data["people"][0]["relationship"] == "creator"


def test_persona_add_project_creates_file(persona_file: Path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "persona",
            "add-project",
            "journaling-app",
            "--status",
            "active",
            "--stack",
            "next.js,postgres",
            "--tldr",
            "journals that process emotions",
        ],
    )
    assert result.exit_code == 0
    data = yaml.safe_load(persona_file.read_text(encoding="utf-8"))
    assert data["projects"][0]["name"] == "journaling-app"
    assert data["projects"][0]["stack"] == ["next.js", "postgres"]


def test_persona_set_scalar_field(persona_file: Path):
    runner = CliRunner()
    # Bootstrap an initial file
    runner.invoke(main, ["persona", "add-person", "Alice"])
    result = runner.invoke(main, ["persona", "set", "identity.name", "Atlas"])
    assert result.exit_code == 0
    data = yaml.safe_load(persona_file.read_text(encoding="utf-8"))
    assert data["identity"]["name"] == "Atlas"


def test_persona_set_boolean_field(persona_file: Path):
    runner = CliRunner()
    runner.invoke(main, ["persona", "add-person", "Alice"])
    result = runner.invoke(main, ["persona", "set", "metadata.workspace_inherit", "true"])
    assert result.exit_code == 0
    data = yaml.safe_load(persona_file.read_text(encoding="utf-8"))
    assert data["metadata"]["workspace_inherit"] is True


def test_persona_round_trip_init_show_set_validate(persona_file: Path):
    """The main integration case from the plan §10."""
    from memgentic.persona.schema import IdentityBlock, Persona

    fake_proposal = Persona(identity=IdentityBlock(name="Atlas", role="AI for Alice"))

    with patch("memgentic.persona.bootstrap", new=AsyncMock(return_value=fake_proposal)):
        runner = CliRunner()
        # init --yes skips the interactive confirm
        result = runner.invoke(main, ["persona", "init", "--yes"])
        assert result.exit_code == 0, result.output

    # show
    result = runner.invoke(main, ["persona", "show"])
    assert result.exit_code == 0
    assert "Atlas" in result.output

    # set
    result = runner.invoke(main, ["persona", "set", "identity.tone", "warm"])
    assert result.exit_code == 0

    # validate
    result = runner.invoke(main, ["persona", "validate"])
    assert result.exit_code == 0
