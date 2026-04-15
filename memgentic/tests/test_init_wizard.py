"""Tests for the Memgentic init wizard."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from memgentic.cli import main
from memgentic.init_wizard import (
    MEMGENTIC_END_MARKER,
    MEMGENTIC_START_MARKER,
    DetectedTool,
    _configure_mcp_gemini,
    detect_tools,
    inject_memory_instructions,
)


class TestDetectTools:
    """Tests for detect_tools()."""

    @patch("memgentic.init_wizard.shutil.which")
    def test_detect_claude_by_command(self, mock_which: MagicMock, tmp_path: Path):
        """Detects Claude Code when CLI binary is found."""
        mock_which.side_effect = lambda cmd: "/usr/bin/claude" if cmd == "claude" else None

        with patch.object(Path, "is_dir", return_value=False):
            tools = detect_tools()

        claude = next(t for t in tools if t.name == "Claude Code")
        assert claude.command_found is True
        assert claude.detected is True

    @patch("memgentic.init_wizard.shutil.which", return_value=None)
    def test_detect_none_when_nothing_installed(self, mock_which: MagicMock):
        """Returns all tools as not detected when nothing is installed."""
        with patch.object(Path, "is_dir", return_value=False):
            tools = detect_tools()

        for tool in tools:
            assert tool.detected is False
            assert tool.command_found is False

    @patch("memgentic.init_wizard.shutil.which", return_value=None)
    def test_detect_by_data_dir(self, mock_which: MagicMock):
        """Detects tool when data directory exists even without CLI."""
        original_is_dir = Path.is_dir

        def fake_is_dir(self: Path) -> bool:
            if ".claude" in str(self):
                return True
            return original_is_dir(self)

        with patch.object(Path, "is_dir", fake_is_dir):
            tools = detect_tools()

        claude = next(t for t in tools if t.name == "Claude Code")
        assert claude.data_found is True
        assert claude.command_found is False
        assert claude.detected is True

    @patch("memgentic.init_wizard.shutil.which")
    def test_returns_three_tools(self, mock_which: MagicMock):
        """Always returns entries for all three supported tools."""
        mock_which.return_value = None
        with patch.object(Path, "is_dir", return_value=False):
            tools = detect_tools()

        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"Claude Code", "Gemini CLI", "Codex CLI"}


class TestInjectMemoryInstructions:
    """Tests for inject_memory_instructions()."""

    def test_creates_new_file(self, tmp_path: Path):
        """Creates context file with instructions when it doesn't exist."""
        context_file = tmp_path / "CLAUDE.md"
        assert not context_file.exists()

        result = inject_memory_instructions(context_file)

        assert result is True
        assert context_file.exists()
        content = context_file.read_text(encoding="utf-8")
        assert MEMGENTIC_START_MARKER in content
        assert MEMGENTIC_END_MARKER in content
        assert "memgentic_recall" in content

    def test_appends_to_existing_file(self, tmp_path: Path):
        """Appends instructions to existing file content."""
        context_file = tmp_path / "CLAUDE.md"
        context_file.write_text("# My Project\n\nSome existing content.\n", encoding="utf-8")

        result = inject_memory_instructions(context_file)

        assert result is True
        content = context_file.read_text(encoding="utf-8")
        assert content.startswith("# My Project")
        assert MEMGENTIC_START_MARKER in content
        assert "memgentic_recall" in content

    def test_idempotent_update(self, tmp_path: Path):
        """Running twice produces the same result (replaces existing section)."""
        context_file = tmp_path / "CLAUDE.md"
        context_file.write_text("# Header\n", encoding="utf-8")

        inject_memory_instructions(context_file)
        first_content = context_file.read_text(encoding="utf-8")

        inject_memory_instructions(context_file)
        second_content = context_file.read_text(encoding="utf-8")

        assert first_content == second_content

    def test_replaces_existing_section(self, tmp_path: Path):
        """Replaces old memgentic section with updated template."""
        context_file = tmp_path / "CLAUDE.md"
        old_content = f"# Header\n\n{MEMGENTIC_START_MARKER}\nOLD CONTENT\n{MEMGENTIC_END_MARKER}\n\n# Footer\n"
        context_file.write_text(old_content, encoding="utf-8")

        result = inject_memory_instructions(context_file)

        assert result is True
        content = context_file.read_text(encoding="utf-8")
        assert "OLD CONTENT" not in content
        assert "memgentic_recall" in content
        assert "# Header" in content
        assert "# Footer" in content

    def test_dry_run_no_changes(self, tmp_path: Path):
        """Dry run does not create or modify files."""
        context_file = tmp_path / "CLAUDE.md"

        result = inject_memory_instructions(context_file, dry_run=True)

        assert result is True
        assert not context_file.exists()

    def test_creates_parent_directories(self, tmp_path: Path):
        """Creates parent directories if they don't exist."""
        context_file = tmp_path / "subdir" / "nested" / "CLAUDE.md"

        result = inject_memory_instructions(context_file)

        assert result is True
        assert context_file.exists()


class TestConfigureMcpGemini:
    """Tests for Gemini MCP configuration via settings.json."""

    def test_creates_new_settings_file(self, tmp_path: Path):
        """Creates settings.json with memgentic server when file doesn't exist."""
        settings_path = tmp_path / ".gemini" / "settings.json"

        with patch("memgentic.init_wizard.Path.home", return_value=tmp_path):
            result = _configure_mcp_gemini(dry_run=False)

        assert result is True
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "memgentic" in data["mcpServers"]
        assert data["mcpServers"]["memgentic"]["command"] == "uvx"

    def test_merges_with_existing_settings(self, tmp_path: Path):
        """Preserves existing settings when adding mneme."""
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings_path = gemini_dir / "settings.json"
        existing = {
            "mcpServers": {"other_tool": {"command": "other"}},
            "someKey": "someValue",
        }
        settings_path.write_text(json.dumps(existing))

        with patch("memgentic.init_wizard.Path.home", return_value=tmp_path):
            result = _configure_mcp_gemini(dry_run=False)

        assert result is True
        data = json.loads(settings_path.read_text())
        assert "memgentic" in data["mcpServers"]
        assert "other_tool" in data["mcpServers"]
        assert data["someKey"] == "someValue"

    def test_skips_if_already_configured(self, tmp_path: Path):
        """Returns True without modifying if memgentic already present."""
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()
        settings_path = gemini_dir / "settings.json"
        existing = {"mcpServers": {"memgentic": {"command": "old"}}}
        settings_path.write_text(json.dumps(existing))

        with patch("memgentic.init_wizard.Path.home", return_value=tmp_path):
            result = _configure_mcp_gemini(dry_run=False)

        assert result is True
        data = json.loads(settings_path.read_text())
        # Should not have been modified
        assert data["mcpServers"]["memgentic"]["command"] == "old"

    def test_dry_run_no_file_created(self, tmp_path: Path):
        """Dry run does not create settings.json."""
        settings_path = tmp_path / ".gemini" / "settings.json"

        with patch("memgentic.init_wizard.Path.home", return_value=tmp_path):
            result = _configure_mcp_gemini(dry_run=True)

        assert result is True
        assert not settings_path.exists()


class TestInitCLI:
    """Tests for the CLI init command."""

    def test_init_help(self):
        """init --help shows correct usage."""
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "One-command setup" in result.output
        assert "--dry-run" in result.output
        assert "--skip-import" in result.output

    @patch("memgentic.init_wizard._check_ollama", new_callable=AsyncMock)
    @patch("memgentic.init_wizard.detect_tools")
    def test_init_dry_run(
        self,
        mock_detect: MagicMock,
        mock_ollama: AsyncMock,
    ):
        """init --dry-run executes without errors and makes no changes."""
        mock_detect.return_value = [
            DetectedTool(
                name="Claude Code",
                command="claude",
                data_dir=Path.home() / ".claude",
                context_file=Path.home() / ".claude" / "CLAUDE.md",
                mcp_method="claude_cli",
                detected=True,
                command_found=True,
                data_found=True,
            ),
        ]
        mock_ollama.return_value = (False, False)

        runner = CliRunner()
        result = runner.invoke(main, ["init", "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    @patch("memgentic.init_wizard._check_ollama", new_callable=AsyncMock)
    @patch("memgentic.init_wizard.detect_tools")
    def test_init_no_tools_detected(
        self,
        mock_detect: MagicMock,
        mock_ollama: AsyncMock,
    ):
        """init exits gracefully when no AI tools are found."""
        mock_detect.return_value = [
            DetectedTool(
                name="Claude Code",
                command="claude",
                data_dir=None,
                context_file=Path("/fake/CLAUDE.md"),
                mcp_method="claude_cli",
                detected=False,
                command_found=False,
                data_found=False,
            ),
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["init", "--dry-run"])

        assert result.exit_code == 0
        assert "No AI tools detected" in result.output

    def test_init_listed_in_help(self):
        """init command appears in main help output."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "init" in result.output
