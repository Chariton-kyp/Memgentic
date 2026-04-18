"""Process lock file — single-writer guard for local-mode daemon/serve.

See ``docs/adr/0006-daemon-mcp-concurrency.md`` for the full rationale.
"""

from __future__ import annotations

import os
from pathlib import Path

_WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WINDOWS_STILL_ACTIVE = 259


class ProcessLockError(RuntimeError):
    """Raised when a conflicting Memgentic process lock already exists."""


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    # ``ctypes.windll`` only exists in the Windows build of Python; pyright
    # on Linux CI flags it, hence the ignore. Callers gate on os.name="nt".
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong(0)
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return bool(ok) and exit_code.value == _WINDOWS_STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is currently running.

    Uses OS primitives instead of psutil so we keep the dependency surface
    tiny for a utility called once per serve/daemon startup. A PID of 0 or
    negative is always treated as dead.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        # OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION (0x1000). If it
        # opens, the pid exists. GetExitCodeProcess returns STILL_ACTIVE
        # (259) while the process is running; anything else = already exited.
        return _windows_pid_alive(pid)
    # POSIX: signal 0 performs error-checking without actually sending a signal.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user; treat as alive so we
        # don't blow away someone else's lock.
        return True
    return True


def _parse_pid(content: str) -> int | None:
    try:
        pid = int(content.strip())
    except (ValueError, TypeError):
        return None
    return pid if pid > 0 else None


def acquire_lock(lock_path: Path, role: str) -> None:
    """Write a PID file to indicate this role is active.

    If a lock file exists but its PID is dead (crash, SIGKILL, reboot), it is
    treated as stale and silently reclaimed — otherwise a single crash of
    ``memgentic serve --watch`` would permanently block future starts until
    the user discovered the stray file under ``~/.memgentic/data/``.

    Raises ``ProcessLockError`` when a live Memgentic process already holds
    the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            content = lock_path.read_text().strip()
        except OSError:
            content = ""
        pid = _parse_pid(content)
        if pid is not None and pid != os.getpid():
            if not _pid_alive(pid):
                # Stale lock from a prior crashed/killed process — take it.
                import contextlib

                with contextlib.suppress(OSError):
                    lock_path.unlink()
            else:
                raise ProcessLockError(
                    f"Another Memgentic process holds the lock at {lock_path} "
                    f"(pid={pid}, role={role}). Stop it first. "
                    f"For local use, the recommended mode is now a single fused "
                    f"process: `memgentic serve --watch` (runs MCP + the capture "
                    f"daemon in one asyncio loop — no lock contention). "
                    f"Alternatively, set MEMGENTIC_QDRANT_URL to use Qdrant "
                    f"server mode which supports concurrent writers."
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
