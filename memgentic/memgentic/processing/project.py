"""Project-name derivation from working directory and platform-specific paths.

A "project" is the friendly key under which memories from a single source tree
collapse — e.g. all memgentic-public-export memories from claude_code, codex_cli
and gemini_cli share ``project="memgentic-public-export"`` so a single filter
hides cross-project noise during recall.

The chosen key is ``Path(cwd).name.lower()`` whenever an adapter has the real
working directory (Claude Code turn header, Codex ``session_meta``, Gemini
``cwd``); when only a Claude-Code-style slug is available we strip the known
``C--Users-<user>-Desktop-`` prefix and split on ``-``. Slug decoding is lossy
(``\\`` and ``_`` both collapse to ``-``) so cwd is always preferred.
"""

from __future__ import annotations

import re
from pathlib import PurePath, PurePosixPath, PureWindowsPath

# Claude Code encodes a Windows or POSIX path by replacing every ``\``, ``/``
# and ``_`` with a single ``-``. We can't recover the lost characters, so we
# strip a recognised prefix and treat the remainder as the friendly project
# name. Examples:
#   C--Users-harit-Desktop-Business-Projects-memgentic-public-export
#       -> memgentic-public-export
#   home-harit-projects-memgentic
#       -> memgentic   (after the ``home-<user>-`` prefix)
_SLUG_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[A-Za-z]--Users-[^-]+-Desktop-Business-Projects-"),
    re.compile(r"^[A-Za-z]--Users-[^-]+-Desktop-"),
    re.compile(r"^[A-Za-z]--Users-[^-]+-"),
    re.compile(r"^home-[^-]+-projects-"),
    re.compile(r"^home-[^-]+-"),
    re.compile(r"^Users-[^-]+-"),
)


def normalize_project(name: str | None) -> str:
    """Normalise a project key — lowercase, strip whitespace, collapse separators.

    Returns ``""`` for falsy inputs so callers can store the column with a
    NOT NULL DEFAULT '' constraint.
    """
    if not name:
        return ""
    cleaned = name.strip().lower()
    # Collapse runs of whitespace/separators to a single ``-``
    cleaned = re.sub(r"[\s_/\\]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def project_from_cwd(cwd: str | None) -> str:
    """Derive a project name from a real working-directory path.

    Picks ``Path(cwd).name``. Handles both Windows and POSIX paths regardless
    of the host OS so adapters that capture a foreign-OS cwd (e.g. Codex
    sessions imported from a Linux machine on Windows) still work.
    """
    if not cwd:
        return ""
    raw = cwd.strip().strip("\"'")
    if not raw:
        return ""
    # Try the host-native parser first; fall back to the other variant if the
    # name comes back empty (typical when a Windows path is parsed on POSIX).
    candidates: list[PurePath] = [PurePath(raw)]
    if "\\" in raw:
        candidates.append(PureWindowsPath(raw))
    if "/" in raw:
        candidates.append(PurePosixPath(raw))
    for candidate in candidates:
        name = candidate.name
        if name and name not in (".", ".."):
            return normalize_project(name)
    return ""


def project_from_claude_code_slug(slug: str | None) -> str:
    """Decode a Claude Code project-directory slug into a friendly project name.

    Claude Code writes JSONL under ``~/.claude/projects/<slug>/`` where the
    slug encodes the original cwd with all separators replaced by ``-``. This
    is a best-effort fallback for older sessions whose JSONL turns lacked a
    ``cwd`` field.
    """
    if not slug:
        return ""
    candidate = slug.strip()
    for pattern in _SLUG_PREFIX_PATTERNS:
        stripped = pattern.sub("", candidate)
        if stripped and stripped != candidate:
            return normalize_project(stripped)
    return normalize_project(candidate)


def derive_project(
    *,
    cwd: str | None = None,
    file_path: str | None = None,
    slug: str | None = None,
) -> str:
    """Return the canonical project key for a memory.

    Resolution order: explicit ``cwd`` (richest, always correct) → Claude Code
    parent-directory ``slug`` decoded heuristically → empty string when no
    signal is available. ``file_path`` is accepted for symmetry with adapters
    but is ignored unless it matches the ``~/.claude/projects/<slug>/`` shape,
    in which case the slug is extracted automatically.
    """
    if cwd:
        derived = project_from_cwd(cwd)
        if derived:
            return derived

    if slug is None and file_path:
        # Accept either a raw POSIX path or a Windows path here.
        normalized = file_path.replace("\\", "/")
        marker = "/.claude/projects/"
        if marker in normalized:
            tail = normalized.split(marker, 1)[1]
            slug = tail.split("/", 1)[0] if tail else None

    if slug:
        return project_from_claude_code_slug(slug)

    return ""
