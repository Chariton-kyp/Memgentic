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

import os
import re
from collections.abc import Mapping
from pathlib import Path

# Sentinels that mean "ignore project scoping — search every project". Matched
# case-insensitively after stripping. Used by the MCP recall surface so a caller
# can force a global search with one shorthand (``project="*"``).
GLOBAL_PROJECT_SENTINELS: frozenset[str] = frozenset({"*", "all", "global"})

# Environment variable the SessionStart hook / launching shell can set so the
# MCP subprocess scopes recall to the active project even when its cwd is not a
# reliable signal.
PROJECT_ENV_VAR = "MEMGENTIC_PROJECT"

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


def is_global_project(value: str | None) -> bool:
    """Return True when ``value`` is a global-scope sentinel (``*``/``all``/``global``)."""
    if not value:
        return False
    return value.strip().lower() in GLOBAL_PROJECT_SENTINELS


def project_from_git_repo(cwd: str | None) -> str:
    """Return the git-repository project key for ``cwd`` when it is inside a repo.

    Prefers the *repository identity* over the leaf directory so that the same
    repo collapses to ONE project key from any subdirectory (e.g. both
    ``<repo>`` and ``<repo>/backend/api`` map to ``<repo>``), and two distinct
    repositories never share a key just because their leaf folders happen to
    match.

    For a normal checkout ``.git`` is a **directory** and the key is the
    normalised basename of the directory containing it.  For a **linked
    worktree** (or submodule) ``.git`` is a **file** whose content is
    ``gitdir: <path>``; we parse that path and walk up its parents to find
    the main repo's ``.git`` directory, then return the main repo root's
    normalised name — so all worktrees of the same repo share ONE key.  When
    the gitdir path is unparseable or the main repo does not exist locally we
    fall back to the worktree directory's name.

    This only fires when ``cwd`` exists on the local filesystem — adapters
    frequently pass foreign or historical paths recorded on another machine, so
    a non-existent path yields ``""`` and the caller falls back to the
    basename heuristic in :func:`project_from_cwd`.
    """
    if not cwd:
        return ""
    raw = cwd.strip().strip("\"'").strip()
    if not raw:
        return ""
    try:
        start = Path(raw)
        if not start.exists():
            return ""
        start = start.resolve()
    except OSError:
        return ""
    for candidate in (start, *start.parents):
        try:
            git_path = candidate / ".git"
            if not git_path.exists():
                continue
            if git_path.is_dir():
                # Normal checkout: .git is a directory, candidate IS the repo root.
                return normalize_project(candidate.name)
            # Linked worktree / submodule: .git is a file containing
            # "gitdir: <path>" that points into the main repo's .git dir
            # (e.g. <main>/.git/worktrees/<name>).  Parse the path, walk up
            # its ancestors until we find a directory literally named ".git"
            # (the main repo's .git directory), and return its parent's name.
            try:
                text = git_path.read_text(encoding="utf-8", errors="replace").strip()
                if text.startswith("gitdir:"):
                    gitdir_raw = text[len("gitdir:") :].strip()
                    gitdir = Path(gitdir_raw)
                    if not gitdir.is_absolute():
                        gitdir = (candidate / gitdir).resolve()
                    # Walk up from the gitdir to locate the main .git directory.
                    for parent in gitdir.parents:
                        if parent.name == ".git" and parent.is_dir():
                            main_root = parent.parent
                            if main_root.exists():
                                return normalize_project(main_root.name)
                            break  # main repo absent locally — use fallback
            except OSError:
                pass
            # Fallback: return the worktree directory's own name (pre-fix behaviour
            # for unparseable gitdir or a missing main repo).
            return normalize_project(candidate.name)
        except OSError:
            continue
    return ""


def project_from_cwd(cwd: str | None) -> str:
    """Derive a project name from a real working-directory path.

    Prefers the git-repository identity (see :func:`project_from_git_repo`) when
    ``cwd`` exists locally inside a repo, so any subdirectory of a repo maps to a
    single project key. Otherwise picks the last meaningful path segment.

    Splits on BOTH ``\\`` and ``/`` regardless of the host OS — adapters discover
    foreign-OS sessions (e.g. a Windows-recorded cwd read from WSL/Linux, or a
    Linux Codex session imported on Windows), and ``pathlib`` on POSIX treats
    ``\\`` as a regular filename character, which would swallow the whole Windows
    path as one segment.
    """
    if not cwd:
        return ""
    raw = cwd.strip().strip("\"'").strip()
    if not raw:
        return ""
    # Repo-aware: when the path is a live directory inside a git repo, collapse
    # to the repository's key so subdirectories never fragment the project.
    repo = project_from_git_repo(raw)
    if repo:
        return repo
    # Separator-agnostic split; runs of separators (UNC prefixes, trailing
    # slashes, doubled backslashes) collapse, and empty segments are dropped.
    segments = [s for s in re.split(r"[\\/]+", raw) if s]
    for segment in reversed(segments):
        if segment == ".":
            # Trailing "." is a no-op path component — look further left.
            continue
        if segment == "..":
            # Can't resolve a parent reference without a filesystem — treat
            # as no signal rather than guessing the wrong directory name.
            return ""
        if re.fullmatch(r"[A-Za-z]:", segment):
            # Bare drive-letter token from an absolute Windows path ("C:") —
            # never a project name (only meaningful for drive roots).
            continue
        return normalize_project(segment)
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


def resolve_current_project(
    *,
    explicit: str | None = None,
    session_project: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> str | None:
    """Resolve the active project key for the MCP server, in priority order.

    Priority (first concrete match wins):

    1. ``explicit`` — a project arg supplied directly on the call.
    2. ``session_project`` — the project configured for this connection via
       ``memgentic_configure_session``.
    3. the ``MEMGENTIC_PROJECT`` env var (read from ``env`` when given, else
       ``os.environ``) — set by the SessionStart hook / launching shell.
    4. ``project_from_cwd(cwd)`` — the subprocess working directory, made
       repo-aware so any subdirectory of a repo resolves to one key.

    Returns the normalised project key, or ``None`` when nothing resolves (→
    global recall). A global sentinel (``*``/``all``/``global``) at any level
    short-circuits to ``None`` so an explicit "search everywhere" wins over a
    lower-priority concrete project.
    """
    env_map = os.environ if env is None else env

    # Each candidate is (value, is_present). A present global sentinel forces
    # global (None); a present concrete value wins; absence falls through.
    candidates: tuple[str | None, ...] = (
        explicit,
        session_project,
        env_map.get(PROJECT_ENV_VAR),
    )
    for value in candidates:
        if value is None or not str(value).strip():
            continue
        if is_global_project(value):
            return None
        key = normalize_project(value)
        if key:
            return key

    if cwd:
        key = project_from_cwd(cwd)
        # A directory literally named with a sentinel (e.g. "global") must not
        # be treated as a real project key — return None to trigger global scope.
        if is_global_project(key):
            return None
        return key or None
    return None
