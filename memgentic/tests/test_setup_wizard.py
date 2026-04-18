"""Tests for the `memgentic setup` interactive wizard (v0.5.0 Step 1 adds
storage-backend selection and optional sqlite-vec install).
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from memgentic.cli import main


def _invoke_setup(inputs: str, monkeypatch, tmp_path: Path):
    """Run `memgentic setup` with pre-canned stdin and pwd=tmp_path.

    Patches out network/subprocess side-effects so the wizard only touches
    the tmp .env file.
    """
    import memgentic.cli as cli_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_pull_ollama_model", lambda *_: None)
    monkeypatch.setattr(cli_module, "_install_sqlite_vec_extra", lambda: None)

    runner = CliRunner()
    return runner.invoke(main, ["setup"], input=inputs)


def test_setup_records_storage_backend_sqlite_vec(monkeypatch, tmp_path: Path):
    """Picking option 1 (sqlite-vec) writes MEMGENTIC_STORAGE_BACKEND=sqlite_vec
    to .env. Regression guard for the v0.5.0 Step 1 addition.
    """
    # Inputs: backend=1 (sqlite_vec), embedding=1 (preset), llm=1 (preset),
    # install sqlite-vec? yes, pull models? no.
    result = _invoke_setup("1\n1\n1\ny\nn\n", monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output

    env = (tmp_path / ".env").read_text()
    assert "MEMGENTIC_STORAGE_BACKEND=sqlite_vec" in env


def test_setup_records_storage_backend_qdrant_local(monkeypatch, tmp_path: Path):
    """Picking option 2 (Qdrant local) writes MEMGENTIC_STORAGE_BACKEND=local
    and does NOT prompt for sqlite-vec install.
    """
    install_called = {"count": 0}

    import memgentic.cli as cli_module

    def fake_install():
        install_called["count"] += 1

    monkeypatch.setattr(cli_module, "_install_sqlite_vec_extra", fake_install)

    # Inputs: backend=2 (local), embedding=1, llm=8 (heuristics), pull? no
    result = _invoke_setup("2\n1\n8\nn\n", monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output

    env = (tmp_path / ".env").read_text()
    assert "MEMGENTIC_STORAGE_BACKEND=local" in env
    assert install_called["count"] == 0, (
        "Qdrant-local path should not trigger the sqlite-vec installer."
    )


def test_setup_help_lists_storage_step(monkeypatch, tmp_path: Path):
    """`memgentic setup --help` advertises the storage-backend step so users
    know they can pick sqlite-vec non-interactively (via env var) or here.
    """
    runner = CliRunner()
    result = runner.invoke(main, ["setup", "--help"])
    assert result.exit_code == 0
    assert "Vector storage backend" in result.output
    assert "sqlite-vec" in result.output
