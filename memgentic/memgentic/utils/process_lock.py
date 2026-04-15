"""Process lock file — single-writer guard for local-mode daemon/serve.

See ``docs/adr/0006-daemon-mcp-concurrency.md`` for the full rationale.
"""

from __future__ import annotations

import os
from pathlib import Path


class ProcessLockError(RuntimeError):
    """Raised when a conflicting Memgentic process lock already exists."""


def acquire_lock(lock_path: Path, role: str) -> None:
    """Write a PID file to indicate this role is active.

    Raises ``ProcessLockError`` if another Memgentic process already holds
    the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            content = lock_path.read_text().strip()
        except OSError:
            content = ""
        if content and content != str(os.getpid()):
            raise ProcessLockError(
                f"Another Memgentic process holds the lock at {lock_path} "
                f"(pid={content}, role={role}). Stop it first, or set "
                f"MEMGENTIC_QDRANT_URL to use Qdrant server mode which "
                f"supports concurrent writers."
            )
    lock_path.write_text(f"{os.getpid()}")


def release_lock(lock_path: Path) -> None:
    """Remove the lock file if it exists and we own it."""
    try:
        if lock_path.exists() and lock_path.read_text().strip() == str(os.getpid()):
            lock_path.unlink()
    except OSError:
        pass


__all__ = ["ProcessLockError", "acquire_lock", "release_lock"]
