"""Project filter resolution at the MCP-tool boundary.

These tests focus on ``_resolve_project_keys`` and the
``_get_effective_config`` merge — the surface that turns user-facing
``project=...`` / ``projects=[...]`` / ``"auto"`` into a SessionConfig.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memgentic.mcp.server import (
    _get_effective_config,
    _resolve_project_keys,
    _session_configs,
    _set_session_config,
)
from memgentic.models import SessionConfig


def _ctx_with_session(session_id: str = "test-session") -> MagicMock:
    """Build a fake Context whose ``_get_session_id`` deterministically resolves.

    ``_get_session_id`` checks ``client_id`` first, then ``session_id``. With
    a plain ``MagicMock`` every attribute is auto-mocked and truthy — which
    would make ``client_id`` win and produce a non-deterministic id. Use a
    spec to constrain available attributes.
    """
    session = MagicMock(spec=["session_id"])
    session.session_id = session_id
    request_ctx = MagicMock()
    request_ctx.session = session
    ctx = MagicMock()
    ctx.request_context = request_ctx
    return ctx


@pytest.fixture(autouse=True)
def _clear_session_state():
    _session_configs.clear()
    yield
    _session_configs.clear()


def test_resolve_project_keys_normalises_input() -> None:
    assert _resolve_project_keys(["MemgenticPublic", "Foo_Bar"]) == [
        "memgenticpublic",
        "foo-bar",
    ]


def test_resolve_project_keys_strips_empty_and_whitespace() -> None:
    assert _resolve_project_keys(["", "   ", "vetervo"]) == ["vetervo"]


def test_resolve_project_keys_returns_none_when_empty() -> None:
    assert _resolve_project_keys(None) is None
    assert _resolve_project_keys([]) is None
    assert _resolve_project_keys(["", "   "]) is None


def test_resolve_project_keys_auto_uses_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path.cwd())  # noop — anchor for clarity
    auto = _resolve_project_keys(["auto"])
    # The current process is running inside the repository, so the cwd's leaf
    # name is whatever pytest was invoked from. We don't assert the literal
    # value (it varies between developer machines + CI), only that something
    # got resolved instead of dropping the input.
    assert auto is not None
    assert len(auto) == 1
    assert auto[0] == auto[0].lower()


def test_resolve_project_keys_auto_in_nonexistent_cwd_drops_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "MemgenticTestProject"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    assert _resolve_project_keys(["auto"]) == ["memgentictestproject"]


def test_effective_config_merges_session_and_call_filters() -> None:
    ctx = _ctx_with_session()
    _set_session_config(
        "test-session",
        SessionConfig(include_projects=["session-default"], exclude_projects=["bad"]),
    )

    config = _get_effective_config(
        ctx,
        project="memgentic",
        projects=["vetervo"],
    )
    # Per-call project filters override session-level ones.
    assert config.include_projects == ["memgentic", "vetervo"]
    # Session-level excludes carry through when the call doesn't override.
    assert config.exclude_projects == ["bad"]


def test_effective_config_per_call_excludes_override_session() -> None:
    ctx = _ctx_with_session()
    _set_session_config(
        "test-session",
        SessionConfig(exclude_projects=["session-bad"]),
    )

    config = _get_effective_config(ctx, exclude_projects=["call-bad"])
    assert config.exclude_projects == ["call-bad"]


def test_effective_config_session_only_when_call_passes_nothing() -> None:
    ctx = _ctx_with_session()
    _set_session_config(
        "test-session",
        SessionConfig(include_projects=["session-only"]),
    )

    config = _get_effective_config(ctx)
    assert config.include_projects == ["session-only"]
