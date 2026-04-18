"""Install-hint tests for the sqlite-vec backend.

These guard the UX when the optional extra isn't installed. They do NOT
require ``sqlite-vec`` itself — we fake its absence via ``sys.modules``.
"""

from __future__ import annotations

import sys

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.exceptions import StorageError
from memgentic.storage.backends.sqlite_vec import SqliteVecBackend


@pytest.fixture()
def _no_sqlite_vec(monkeypatch):
    """Make ``import sqlite_vec`` raise ImportError regardless of whether the
    package is installed in the test environment."""
    import builtins

    # Drop any cached real module so the fake hook below fires on next import.
    monkeypatch.delitem(sys.modules, "sqlite_vec", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sqlite_vec":
            raise ImportError("No module named 'sqlite_vec' (faked)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


async def test_missing_sqlite_vec_raises_storage_error_with_install_hint(tmp_path, _no_sqlite_vec):
    """When sqlite-vec isn't installed, initialize() must raise a StorageError
    whose message tells the user exactly how to install it, quoted so the
    shell doesn't glob-expand the brackets.
    """
    settings = MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.SQLITE_VEC,
        embedding_dimensions=8,
    )
    backend = SqliteVecBackend(settings)

    with pytest.raises(StorageError) as exc_info:
        await backend.initialize()

    msg = str(exc_info.value)
    # Verbatim install commands with quotes around the extra — shells won't
    # glob these.
    assert "pip install 'memgentic[sqlite-vec]'" in msg
    assert "uv add 'memgentic[sqlite-vec]'" in msg
    # And tell the user the env var that triggered the branch.
    assert "MEMGENTIC_STORAGE_BACKEND" in msg


def test_doctor_sqlite_vec_detail_escapes_rich_markup():
    """The ``sqlite-vec extension`` doctor row's detail string must escape
    square brackets so Rich doesn't swallow ``[sqlite-vec]`` as a tag and
    leave users with ``pip install 'memgentic'`` (which does nothing).
    """
    # We can't easily run `memgentic doctor` under test without Ollama etc.,
    # so inspect the source: the detail literal must contain an escaped
    # bracket (``\[``) before ``sqlite-vec]``.
    import inspect

    import memgentic.cli as cli_module
    from memgentic.cli import _doctor as doctor_module_symbol  # noqa: F401

    source = inspect.getsource(cli_module._doctor)
    assert r"\[sqlite-vec]" in source, (
        "doctor must emit an escaped `\\[sqlite-vec]` in the install hint so "
        "Rich renders the bracket literally. Otherwise the user sees "
        "`pip install 'memgentic'` without the extra."
    )
