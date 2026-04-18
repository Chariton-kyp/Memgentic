"""Tests for memgentic.utils.process_lock."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from memgentic.utils import process_lock as pl
from memgentic.utils.process_lock import (
    ProcessLockError,
    acquire_lock,
    release_lock,
)


def test_acquire_lock_success(tmp_path: Path):
    lock = tmp_path / ".daemon.pid"
    acquire_lock(lock, role="daemon")
    assert lock.exists()
    assert lock.read_text().strip() == str(os.getpid())


def test_acquire_lock_conflict_when_pid_alive(tmp_path: Path, monkeypatch):
    """If another memgentic process is actually running, its lock wins."""
    monkeypatch.setattr(pl, "_pid_alive", lambda pid: True)
    lock = tmp_path / ".daemon.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999")
    with pytest.raises(ProcessLockError) as exc:
        acquire_lock(lock, role="daemon")
    # Error must be actionable — name the foreign pid and recommend the
    # fused serve --watch path.
    assert "99999" in str(exc.value)
    assert "serve --watch" in str(exc.value)


def test_stale_lock_is_reclaimed_when_pid_dead(tmp_path: Path, monkeypatch):
    """A leftover .daemon.pid whose PID no longer exists must not block
    future starts — that's the v0.5.0 user-sim footgun on Windows.
    """
    monkeypatch.setattr(pl, "_pid_alive", lambda pid: False)
    lock = tmp_path / ".daemon.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999")

    acquire_lock(lock, role="daemon")

    assert lock.exists()
    assert lock.read_text().strip() == str(os.getpid())


def test_malformed_lock_is_reclaimed(tmp_path: Path):
    """Non-integer content (corrupted file) is treated as reclaimable."""
    lock = tmp_path / ".daemon.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("not-a-pid")

    acquire_lock(lock, role="daemon")

    assert lock.read_text().strip() == str(os.getpid())


def test_release_lock(tmp_path: Path):
    lock = tmp_path / ".daemon.pid"
    acquire_lock(lock, role="daemon")
    assert lock.exists()
    release_lock(lock)
    assert not lock.exists()


def test_release_lock_owned_by_other_is_noop(tmp_path: Path):
    lock = tmp_path / ".daemon.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999")
    release_lock(lock)
    # Should not remove the lock since we don't own it
    assert lock.exists()


def test_pid_alive_for_own_process_returns_true():
    """Sanity check the OS probe — own PID must report alive."""
    assert pl._pid_alive(os.getpid()) is True


def test_pid_alive_for_impossible_pid_returns_false():
    """PID 0 / negative / very large unlikely-used are dead."""
    assert pl._pid_alive(0) is False
    assert pl._pid_alive(-1) is False
