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
    # dream-preset=6 (skip), install sqlite-vec? yes, pull models? no.
    result = _invoke_setup("1\n1\n1\n6\ny\nn\n", monkeypatch, tmp_path)
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

    # Inputs: backend=2 (local), embedding=1, llm=8 (heuristics),
    # dream-preset=6 (skip), pull? no
    result = _invoke_setup("2\n1\n8\n6\nn\n", monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output

    env = (tmp_path / ".env").read_text()
    assert "MEMGENTIC_STORAGE_BACKEND=local" in env
    assert install_called["count"] == 0, (
        "Qdrant-local path should not trigger the sqlite-vec installer."
    )


def test_setup_openai_compat_embedding(monkeypatch, tmp_path: Path):
    """Embedding option 7 (OpenAI-compatible server) records the provider +
    base URL + model + dims in .env, so embeddings can run on llama.cpp / vLLM
    instead of Ollama.
    """
    # Inputs: backend=2 (local), embedding=7 (openai_compat) -> base URL,
    # model, dims; llm=8 (heuristics), dream-preset=6 (skip).
    result = _invoke_setup(
        "2\n7\nhttp://localhost:8082/v1\nbge-m3\n1024\n8\n6\n",
        monkeypatch,
        tmp_path,
    )
    assert result.exit_code == 0, result.output

    env = (tmp_path / ".env").read_text()
    assert "MEMGENTIC_EMBEDDING_PROVIDER=openai_compat" in env
    assert "MEMGENTIC_EMBEDDING_BASE_URL=http://localhost:8082/v1" in env
    assert "MEMGENTIC_EMBEDDING_MODEL=bge-m3" in env
    assert "MEMGENTIC_EMBEDDING_DIMENSIONS=1024" in env


def test_setup_openai_compat_skips_ollama_pull(monkeypatch, tmp_path: Path):
    """The openai_compat embedding path must NOT try to pull the model via
    Ollama (it isn't an Ollama model). Uses its own capturing patch rather than
    the no-op in ``_invoke_setup``."""
    import memgentic.cli as cli_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_install_sqlite_vec_extra", lambda: None)
    pulled: list[str] = []
    monkeypatch.setattr(cli_module, "_pull_ollama_model", lambda m: pulled.append(m))

    # backend=2, embedding=7 (compat) + url/model/dims, llm=8 (heuristics), dream=6
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["setup"],
        input="2\n7\nhttp://localhost:8082/v1\nbge-m3\n1024\n8\n6\n",
    )
    assert result.exit_code == 0, result.output
    assert pulled == [], f"openai_compat must not pull via Ollama, but pulled: {pulled}"


def test_setup_help_lists_storage_step(monkeypatch, tmp_path: Path):
    """`memgentic setup --help` advertises the storage-backend step so users
    know they can pick sqlite-vec non-interactively (via env var) or here.
    """
    runner = CliRunner()
    result = runner.invoke(main, ["setup", "--help"])
    assert result.exit_code == 0
    assert "Vector storage backend" in result.output
    assert "sqlite-vec" in result.output
