"""CLI coverage for the capture profile commands."""

from __future__ import annotations

from click.testing import CliRunner

from memgentic.cli import main


class TestCaptureProfileGroupHelp:
    def test_group_shows_in_main_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "capture-profile" in result.output

    def test_group_help_lists_subcommands(self):
        runner = CliRunner()
        result = runner.invoke(main, ["capture-profile", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output
        assert "set" in result.output

    def test_set_validates_profile_choice(self):
        runner = CliRunner()
        result = runner.invoke(main, ["capture-profile", "set", "not-a-profile"])
        # Click raises a UsageError (exit code 2) for invalid choices.
        assert result.exit_code == 2
        assert "not-a-profile" in result.output or "Invalid value" in result.output

    def test_remember_help_exposes_profile_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["remember", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
        assert "raw" in result.output
        assert "dual" in result.output

    def test_import_existing_help_exposes_profile_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["import-existing", "--help"])
        assert result.exit_code == 0
        assert "--profile" in result.output
