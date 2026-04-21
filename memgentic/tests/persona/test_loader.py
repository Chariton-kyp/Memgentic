"""Loader/serialiser tests for the Persona card."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from memgentic.persona.loader import (
    PERSONA_ENV_VAR,
    PersonaMalformedError,
    file_lock,
    get_persona_path,
    load,
    save,
)
from memgentic.persona.schema import IdentityBlock, Persona


@pytest.fixture
def persona_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the persona path at a tmp file via the env override."""
    target = tmp_path / "nested" / "persona.yaml"
    monkeypatch.setenv(PERSONA_ENV_VAR, str(target))
    return target


def test_get_persona_path_respects_env(persona_env: Path):
    assert get_persona_path() == persona_env


def test_load_returns_none_when_missing(persona_env: Path):
    assert not persona_env.exists()
    assert load() is None


def test_save_then_load_roundtrip(persona_env: Path):
    p = Persona(
        identity=IdentityBlock(name="Atlas", role="AI for Alice", tone="warm"),
    )
    path = save(p)
    assert path == persona_env
    assert persona_env.exists()

    reloaded = load()
    assert reloaded is not None
    assert reloaded.identity.name == "Atlas"
    assert reloaded.metadata.updated_at is not None


def test_save_sets_restrictive_permissions_on_posix(persona_env: Path):
    p = Persona(identity=IdentityBlock(name="Atlas"))
    save(p)
    if sys.platform.startswith("win"):
        pytest.skip("POSIX permission bits not meaningful on Windows")
    mode = persona_env.stat().st_mode & 0o777
    assert mode == 0o600
    dir_mode = persona_env.parent.stat().st_mode & 0o777
    assert dir_mode == 0o700


def test_save_writes_yaml_with_top_level_keys(persona_env: Path):
    """Sanity-check that the on-disk format is human-friendly YAML."""
    p = Persona(identity=IdentityBlock(name="Atlas"))
    save(p)
    text = persona_env.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert set(data.keys()) >= {"version", "identity", "metadata"}


def test_save_is_atomic_no_tmp_leftover(persona_env: Path):
    p = Persona(identity=IdentityBlock(name="Atlas"))
    save(p)
    leftovers = [x for x in persona_env.parent.iterdir() if x.name.startswith(".persona-")]
    assert not leftovers, f"temp files leaked: {leftovers}"


def test_load_raises_on_malformed_yaml(persona_env: Path):
    persona_env.parent.mkdir(parents=True, exist_ok=True)
    persona_env.write_text(":\n  : : bad", encoding="utf-8")
    with pytest.raises(PersonaMalformedError):
        load()


def test_load_returns_none_for_empty_file(persona_env: Path):
    persona_env.parent.mkdir(parents=True, exist_ok=True)
    persona_env.write_text("", encoding="utf-8")
    assert load() is None


def test_file_lock_reentrant_same_process(persona_env: Path):
    """Back-to-back locks in the same process should not deadlock."""
    with file_lock():
        pass
    with file_lock():
        pass


def test_save_respects_explicit_path(tmp_path: Path):
    target = tmp_path / "persona.yaml"
    p = Persona(identity=IdentityBlock(name="Atlas"))
    save(p, path=target)
    assert target.exists()
    assert load(target) is not None
