"""Tests for memgentic.utils.process_lock."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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


def test_acquire_lock_conflict(tmp_path: Path):
    lock = tmp_path / ".daemon.pid"
    lock.parent.mkdir(parents=True, exist_ok=True)
    # Simulate another process holding the lock
    lock.write_text("99999")
    with pytest.raises(ProcessLockError):
        acquire_lock(lock, role="daemon")


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
