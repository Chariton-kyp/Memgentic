"""WSL filesystem discovery for cross-tool capture.

Many Memgentic users on Windows run their AI CLIs (Codex, Gemini CLI,
Claude Code, Aider, GitHub Copilot CLI, ...) inside WSL rather than
PowerShell. The CLIs then write conversation files into the WSL distro's
filesystem at ``/home/<user>/...``, which is invisible to a Windows-side
adapter that only watches the user's Windows profile.

This module exposes a single helper, :func:`wsl_user_paths`, that returns
the list of UNC paths to a given subdirectory across every installed WSL
distro and Linux user on the current machine. Adapters merge it into
their own ``watch_paths`` so the daemon picks up captures regardless of
which shell the user runs the CLI in.

Notes:

- Python's ``pathlib.Path`` reaches WSL via the
  ``//wsl.localhost/<distro>/...`` UNC variant only — the legacy
  ``\\\\wsl$\\<distro>\\`` form does not consistently round-trip
  through ``pathlib`` (bash seems to handle it but Python does not).
  We therefore generate forward-slash UNC paths exclusively.
- The Docker Desktop helper distros (``docker-desktop``,
  ``docker-desktop-data``) are skipped — they are infrastructure shells
  with no human user accounts.
- Discovery is cached for the process lifetime via ``functools.lru_cache``
  to avoid re-spawning ``wsl.exe`` on every adapter property access.
  Restart the daemon to pick up newly installed WSL distros.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Distro names we never enumerate — they're Docker / WSL infrastructure
# rather than user-shell environments.
_SKIP_DISTRO_PREFIXES: tuple[str, ...] = ("docker-desktop",)


@lru_cache(maxsize=1)
def _installed_wsl_distros() -> tuple[str, ...]:
    """Return the names of every installed WSL distro on this machine.

    Empty tuple on non-Windows platforms or when ``wsl.exe`` is not
    available / no distros are installed.
    """
    if sys.platform != "win32":
        return ()

    wsl_exe = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl_exe is None:
        return ()

    try:
        result = subprocess.run(
            [wsl_exe, "-l", "-q"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        raw = result.stdout
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("wsl.list_failed", error=str(exc))
        return ()

    # ``wsl -l -q`` is UTF-16-LE on real Windows, UTF-8 on some
    # CI / WSL-from-WSL setups. Try both, drop BOM and embedded nulls.
    text = ""
    for encoding in ("utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(encoding).replace("\x00", "")
            if text.strip():
                break
        except UnicodeDecodeError:
            continue
    if not text:
        return ()

    distros = tuple(
        name
        for name in (line.strip() for line in text.splitlines())
        if name and not any(name.lower().startswith(prefix) for prefix in _SKIP_DISTRO_PREFIXES)
    )
    return distros


def _enumerate_users(distro: str) -> list[str]:
    """List the home directories under ``/home/`` for one distro."""
    home_root = Path(f"//wsl.localhost/{distro}/home")
    if not home_root.exists():
        return []
    try:
        return [d.name for d in home_root.iterdir() if d.is_dir()]
    except (OSError, PermissionError):
        return []


def wsl_user_paths(relative_subpath: str) -> list[Path]:
    """Return WSL paths for ``<distro>/home/<user>/<relative_subpath>``.

    For each installed WSL distro and each user under that distro's
    ``/home/``, build the corresponding ``//wsl.localhost/<distro>/home/
    <user>/<relative_subpath>`` UNC path and keep it if the directory
    exists. Returns an empty list on non-Windows platforms, when WSL
    isn't installed, or when no distro has the requested subpath.

    Examples:

    - ``wsl_user_paths(".codex/sessions")`` → list of every
      ``/home/<user>/.codex/sessions`` directory across distros.
    - ``wsl_user_paths(".claude/projects")`` → same for Claude Code.
    - ``wsl_user_paths(".gemini/tmp")`` → same for Gemini CLI.

    Args:
        relative_subpath: Path relative to the WSL user's home, using
            forward slashes (e.g., ``".codex/sessions"``). May start
            with or without a leading slash; any leading slashes are
            stripped before joining.

    Returns:
        List of existing :class:`Path` objects pointing into WSL.
        Logged at ``info`` once per process when results are non-empty.
    """
    if sys.platform != "win32":
        return []

    sub = relative_subpath.lstrip("/").lstrip("\\")
    distros = _installed_wsl_distros()
    if not distros:
        return []

    found: list[Path] = []
    for distro in distros:
        for user in _enumerate_users(distro):
            candidate = Path(f"//wsl.localhost/{distro}/home/{user}/{sub}")
            if candidate.exists():
                found.append(candidate)

    if found:
        logger.info(
            "wsl.paths_discovered",
            subpath=relative_subpath,
            count=len(found),
            paths=[str(p) for p in found],
        )

    return found
