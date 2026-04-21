"""On-disk I/O for the Persona card.

Responsibilities:

- Resolve the persona path (``MEMGENTIC_PERSONA_PATH`` env var wins; else
  ``~/.memgentic/persona.yaml``).
- Read + validate YAML into a :class:`~memgentic.persona.schema.Persona`.
- Write atomically (temp file + ``os.replace``) with a 5 s advisory lock.
- Set ``0700`` on the directory and ``0600`` on the file (POSIX only —
  Windows silently no-ops, which is acceptable for a local dev tool).

The lock mechanism is cross-platform: ``fcntl`` on POSIX,
``msvcrt.locking`` on Windows. Both are advisory; the contract is
"cooperative writers honour the lock".
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import yaml

from memgentic.persona.schema import Persona, validate

PERSONA_FILENAME = "persona.yaml"
PERSONA_ENV_VAR = "MEMGENTIC_PERSONA_PATH"

DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.1


class PersonaLockError(RuntimeError):
    """Raised when the persona file lock cannot be acquired within the timeout."""


class PersonaMalformedError(ValueError):
    """Raised when ``persona.yaml`` exists but cannot be parsed as YAML."""


def get_persona_path() -> Path:
    """Return the resolved persona file path.

    Respects ``MEMGENTIC_PERSONA_PATH`` for testing and for users who want
    to keep the card somewhere other than ``~/.memgentic/``.
    """
    override = os.environ.get(PERSONA_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".memgentic" / PERSONA_FILENAME


def _chmod_quiet(path: Path, mode: int) -> None:
    """Best-effort chmod that never raises on unsupported platforms.

    On Windows, POSIX permission bits are a no-op, so we skip to avoid
    noisy warnings. On POSIX, failures are swallowed silently because the
    persona file is local-only and permission errors here are not worth
    aborting a CLI command over (we'll log at the caller where relevant).
    """
    if sys.platform.startswith("win"):
        return
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def _ensure_parent(path: Path) -> None:
    """Create the parent directory (``0700`` on POSIX) if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_quiet(path.parent, 0o700)


@contextmanager
def _posix_lock(fh: IO, timeout: float) -> Iterator[None]:
    """Acquire an exclusive advisory lock on an open file (POSIX)."""
    import fcntl  # type: ignore[import-not-found]

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise PersonaLockError(
                    f"Could not acquire persona lock within {timeout:.1f}s"
                ) from None
            time.sleep(_POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


@contextmanager
def _windows_lock(fh: IO, timeout: float) -> Iterator[None]:
    """Acquire an exclusive advisory lock on an open file (Windows)."""
    import msvcrt

    deadline = time.monotonic() + timeout
    # msvcrt.locking requires a nonzero byte count; we lock a single byte at
    # offset 0 which is enough to serialise writers on the same file.
    while True:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise PersonaLockError(
                    f"Could not acquire persona lock within {timeout:.1f}s"
                ) from None
            time.sleep(_POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]


@contextmanager
def file_lock(
    path: Path | None = None,
    timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire an advisory lock for the persona file.

    Uses a sidecar ``.lock`` file so we don't need the persona file to
    already exist. Cross-platform: ``fcntl`` on POSIX, ``msvcrt`` on
    Windows. Timeout is 5 s by default — if a second writer is holding
    the lock longer than that, surface a :class:`PersonaLockError` to the
    caller (CLI and REST translate this to a user-visible error).
    """
    target = path or get_persona_path()
    _ensure_parent(target)
    lock_path = target.with_suffix(target.suffix + ".lock")

    with open(lock_path, "a+b") as fh:
        if sys.platform.startswith("win"):
            with _windows_lock(fh, timeout):
                yield
        else:
            with _posix_lock(fh, timeout):
                yield


def load(path: Path | None = None) -> Persona | None:
    """Load + validate the persona from disk.

    Returns ``None`` when the file does not exist. Raises
    :class:`PersonaMalformedError` when the YAML is invalid, and lets the
    underlying :class:`pydantic.ValidationError` propagate when the shape
    is wrong — callers that want a safe fallback should catch both.
    """
    target = path or get_persona_path()
    if not target.exists():
        return None
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PersonaMalformedError(f"Could not read {target}: {exc}") from exc
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PersonaMalformedError(f"Invalid YAML in {target}: {exc}") from exc
    if parsed is None:
        return None
    return validate(parsed)


def _persona_to_yaml(persona: Persona) -> str:
    """Render a Persona as a deterministic, human-friendly YAML document."""
    data = persona.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def save(
    persona: Persona,
    path: Path | None = None,
    *,
    touch_updated_at: bool = True,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Path:
    """Atomically write the persona to disk.

    Flow: create parent dir (``0700``) → acquire advisory lock → write to
    a sibling temp file → fsync → ``os.replace`` over the target →
    ``chmod 0600``. Returns the final path.

    ``touch_updated_at`` is True by default — callers that want to
    preserve the existing timestamp (e.g. migrations) can opt out.
    """
    target = path or get_persona_path()
    _ensure_parent(target)

    if touch_updated_at:
        persona.metadata.updated_at = datetime.now(UTC)

    serialised = _persona_to_yaml(persona)

    with file_lock(target, timeout=lock_timeout):
        # Write to a sibling temp file so the replace is atomic on both
        # POSIX and Windows. delete=False because we hand the fd back
        # to os.replace ourselves.
        fd, tmp_name = tempfile.mkstemp(
            prefix=".persona-",
            suffix=".yaml.tmp",
            dir=str(target.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(serialised)
                fh.flush()
                # fsync may fail on some filesystems (tmpfs, CI sandboxes)
                # — durability isn't load-bearing for a local config file.
                with contextlib.suppress(OSError):
                    os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if tmp_path.exists():
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            raise

    _chmod_quiet(target, 0o600)
    return target


__all__ = [
    "DEFAULT_LOCK_TIMEOUT_SECONDS",
    "PERSONA_ENV_VAR",
    "PERSONA_FILENAME",
    "PersonaLockError",
    "PersonaMalformedError",
    "file_lock",
    "get_persona_path",
    "load",
    "save",
]
