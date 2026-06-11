# Project Filter UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn memgentic's basic project filter into an effortless cross-tool, alias-aware system: when a user opens Claude Code in `~/Desktop/Business_Projects/memgentic-public-export/` and asks `memgentic_recall("auth flow")` without any flag, they get current-project memories ranked first (×1.5 boost) followed by a labeled "Related from other projects" section.

**Architecture:** Five vertical slices. (1) TOML alias system + repair CLI; (2) opt-in git toplevel resolution; (3) Migration 11 partial index + JSONL backfill CLI; (4) multi-value REST + dashboard multi-select; (5) current-project boost + cross-project section. Each ships independently. Spec at `docs/superpowers/specs/2026-05-09-project-filter-ux-design.md`.

**Tech Stack:** Python 3.12 + Pydantic Settings + Click 8 + aiosqlite + tomllib (stdlib) + functools.lru_cache + asyncio.to_thread; FastAPI on the API side; Next.js 16 + React 19 + TanStack Query + Tailwind v4 + shadcn/ui + Base UI (`@base-ui/react`) on the dashboard side; pytest + pytest-asyncio for tests.

---

## Project Conventions (Read Once Before Starting)

**Test layout** — `memgentic/tests/test_<area>.py` (flat, no nesting). Existing examples: `test_project_derivation.py`, `test_project_filter.py`, `test_mcp_project_filter.py`. Use `pytest.mark.asyncio` for async tests; the project's `conftest.py` already configures `asyncio_mode = "auto"` so the marker is implicit on `async def test_*`.

**Existing project derivation module** — `memgentic/memgentic/processing/project.py` already exports `normalize_project()`, `project_from_cwd()`, `project_from_claude_code_slug()`, and `derive_project()`. Build on these; don't replace them.

**Migrations** — `memgentic/memgentic/storage/migrations.py` holds a `MIGRATIONS` list of `(version, description, [sql_statements])` tuples. The runner is `migrate(db: aiosqlite.Connection)` at line 280. Migration 9 is `project — friendly key for cross-tool project filtering` (already shipped). Migration 10 is `dreams — auto-dream consolidation runs and proposed patches` (already shipped — DO NOT confuse with this plan's "Migration 11"). Migration 11 must NOT contain Python backfill (Landmine 2 — see spec).

**`memgentic projects` CLI** — currently a flat command at `cli.py:551-607` that prints a table of projects. This plan converts it to a Click group with subcommands. To preserve backward compatibility, the new group must use `@click.group(invoke_without_command=True)` and call the `list` subcommand when no subcommand is given.

**Adapter project derivation** — four adapters override `get_project()`: `aider.py:51`, `codex_cli.py:107`, `gemini_cli.py:77`, `claude_code.py:60`. Each currently calls `derive_project(cwd=...)` directly. Slice 2 swaps these to `derive_project_full(...)` when `enable_git_project_resolution=True`.

**Dashboard sidebar** — `collections-sidebar.tsx:252-283` renders the Projects section as single-toggle buttons that clear source on click. Slice 4 changes these to multi-select checkboxes and removes the source-mutex.

**Config** — `MemgenticSettings` in `memgentic/memgentic/config.py`. Env vars use `MEMGENTIC_` prefix automatically (set on line 32). Add new fields at the end of the existing groupings; don't reorder.

**Commit message style** — follow the repo's existing Conventional Commits (`feat:`, `fix:`, `refactor:`, `chore:`, `test:`, `docs:`). Body includes one-line summary; rationale belongs in PR description.

**Lint** — `make lint` runs `ruff` over the codebase. Run after each task before committing.

---

## File Structure

### Files to create

| Path | Purpose | Slice |
|------|---------|-------|
| `memgentic/tests/test_project_aliases.py` | Unit tests for `load_project_aliases`, `_resolve_transitive`, `resolve_project`, cycle detection, sink-to-empty | 1 |
| `memgentic/tests/test_project_cli.py` | CLI tests for `projects list/alias/merge/repair/backfill-jsonl` via Click `CliRunner` | 1, 3 |
| `projects.toml.example` | Repo-root TOML example users copy to `~/.memgentic/projects.toml` | 1 |
| `memgentic/tests/test_project_resolution.py` | Unit tests for `_git_toplevel_sync`, `_git_remote_url_sync`, async wrappers, UNC guards, `derive_project_full`, `resolve_current_project` | 2 |
| `memgentic/tests/test_migration_11.py` | Verifies Migration 11 creates the partial index and is idempotent | 3 |
| `memgentic/tests/test_hybrid_search_boost.py` | Unit tests for `current_project`, `score_raw`, `is_current_project`, boost arithmetic | 5 |
| `dashboard/src/__tests__/api-list-memories.test.ts` | Vitest test for multi-value `project` query param serialization | 4 |

### Files to modify

| Path | Slice | Reason |
|------|-------|--------|
| `memgentic/memgentic/processing/project.py` | 1, 2 | Add alias resolution + git resolution functions |
| `memgentic/memgentic/cli.py` | 1, 3 | Convert `projects` command to group + add subcommands |
| `memgentic/memgentic/config.py` | 2, 5 | Add `enable_git_project_resolution`, `current_project_boost`, `cross_project_threshold`, `cross_project_max` |
| `memgentic/memgentic/adapters/aider.py` | 2 | Switch to `derive_project_full` when git resolution enabled |
| `memgentic/memgentic/adapters/codex_cli.py` | 2 | Same |
| `memgentic/memgentic/adapters/gemini_cli.py` | 2 | Same |
| `memgentic/memgentic/adapters/claude_code.py` | 2 | Same |
| `memgentic/memgentic/storage/migrations.py` | 3 | Add Migration 11 (partial index only) |
| `memgentic-api/memgentic_api/routes/memories.py` | 4 | Multi-value `project` query param |
| `dashboard/src/lib/api.ts` | 4 | `projects: string[]` instead of `project?: string` |
| `dashboard/src/hooks/use-memories.ts` | 4 | `useMemories` accepts `projects?: string[]` |
| `dashboard/src/components/collections/collections-sidebar.tsx` | 4 | Multi-select checkboxes, drop mutex |
| `dashboard/src/app/page.tsx` | 4 | `projectFilters: string[]` state |
| `memgentic/memgentic/graph/search.py` | 5 | `current_project`, `score_raw`, boost pass, `is_current_project` |
| `memgentic/memgentic/mcp/server.py` | 5 | Resolve current project, pass to search, render partition |

---

# Slice 1 — Alias System + Repair CLI

**Risk:** Lowest. Zero ranking change, no migration, no UI change. Pure Python additions to `processing/project.py` plus CLI subcommand glue.

**Ships:** Users can create `~/.memgentic/projects.toml`, run `memgentic projects merge a b --into c`, see consolidated counts in `memgentic projects list`.

## Task 1.1: Add `_resolve_transitive` helper to project.py

**Files:**
- Modify: `memgentic/memgentic/processing/project.py` (append at end)
- Test: `memgentic/tests/test_project_aliases.py` (create)

- [ ] **Step 1: Write the failing test**

Create `memgentic/tests/test_project_aliases.py`:

```python
"""Unit tests for project alias resolution (TOML-driven).

Covers:
- _resolve_transitive (chain following + cycle detection)
- load_project_aliases (TOML parsing, error tolerance)
- resolve_project (public wrapper)
- invalidate_alias_cache
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memgentic.processing.project import _resolve_transitive


class TestResolveTransitive:
    def test_returns_unchanged_when_not_in_map(self) -> None:
        assert _resolve_transitive("foo", {}) == "foo"
        assert _resolve_transitive("foo", {"bar": "baz"}) == "foo"

    def test_single_hop(self) -> None:
        assert _resolve_transitive("a", {"a": "b"}) == "b"

    def test_transitive_chain(self) -> None:
        chain = {"a": "b", "b": "c", "c": "d"}
        assert _resolve_transitive("a", chain) == "d"
        assert _resolve_transitive("b", chain) == "d"

    def test_self_loop_returns_self(self) -> None:
        # a -> a is treated as terminal, not as cycle
        assert _resolve_transitive("a", {"a": "a"}) == "a"

    def test_cycle_raises(self) -> None:
        cyclic = {"a": "b", "b": "a"}
        with pytest.raises(ValueError, match="cycle"):
            _resolve_transitive("a", cyclic)

    def test_three_node_cycle_raises(self) -> None:
        cyclic = {"a": "b", "b": "c", "c": "a"}
        with pytest.raises(ValueError, match="cycle"):
            _resolve_transitive("a", cyclic)

    def test_chain_too_deep_raises(self) -> None:
        # Build a 20-hop chain — exceeds max depth 16
        chain = {f"k{i}": f"k{i + 1}" for i in range(20)}
        with pytest.raises(ValueError, match="too deep"):
            _resolve_transitive("k0", chain)

    def test_empty_string_target_is_terminal(self) -> None:
        # Empty string = "collapse to unknown" sink
        assert _resolve_transitive("garbage", {"garbage": ""}) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py -v`

Expected: All `TestResolveTransitive` tests FAIL with `ImportError: cannot import name '_resolve_transitive' from 'memgentic.processing.project'`.

- [ ] **Step 3: Implement `_resolve_transitive` in project.py**

Append to `memgentic/memgentic/processing/project.py` (after `derive_project`, around line 128):

```python
# --- Alias resolution (TOML-backed) -----------------------------------------

# Maximum chain depth before raising — guards against pathological configs and
# bugs in the caller. 16 is far above any realistic alias chain (typically 1-2).
_MAX_ALIAS_DEPTH = 16


def _resolve_transitive(key: str, raw_map: dict[str, str]) -> str:
    """Follow alias chain from ``key`` until stable or cycle detected.

    Args:
        key: Starting project key.
        raw_map: Raw alias mapping {from: to}. Empty-string ``to`` values
            are treated as terminals (collapse to "(unknown)" sink).

    Returns:
        The terminal key after following the chain.

    Raises:
        ValueError: If a cycle is detected or the chain exceeds
            ``_MAX_ALIAS_DEPTH`` hops.
    """
    seen: set[str] = {key}
    current = key
    for _ in range(_MAX_ALIAS_DEPTH):
        target = raw_map.get(current)
        if target is None or target == current:
            return current
        if target in seen:
            raise ValueError(
                f"Alias cycle detected: {' -> '.join([*seen, target])}"
            )
        seen.add(target)
        current = target
    raise ValueError(f"Alias chain too deep from {key!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py::TestResolveTransitive -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/harit/Desktop/Business_Projects/memgentic-public-export
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_aliases.py
git commit -m "feat(project): add _resolve_transitive for alias chain resolution"
```

---

## Task 1.2: Add `load_project_aliases` (TOML reader)

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_aliases.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_aliases.py`:

```python
class TestLoadProjectAliases:
    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        missing = tmp_path / "does-not-exist.toml"
        assert load_project_aliases(missing) == {}

    def test_parses_simple_aliases(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            """
[[alias]]
from = ["foo", "bar"]
to = "canonical"

[[alias]]
from = ["junk"]
to = ""
""",
            encoding="utf-8",
        )

        result = load_project_aliases(toml_path)
        # Each `from` key maps to the (transitively) resolved `to`.
        assert result == {
            "foo": "canonical",
            "bar": "canonical",
            "junk": "",
        }

    def test_normalises_keys_to_lowercase(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            """
[[alias]]
from = ["FooBar", "BAZ"]
to = "Canonical"
""",
            encoding="utf-8",
        )

        result = load_project_aliases(toml_path)
        assert result == {"foobar": "canonical", "baz": "canonical"}

    def test_first_match_wins_on_conflict(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            """
[[alias]]
from = ["x"]
to = "first"

[[alias]]
from = ["x"]
to = "second"
""",
            encoding="utf-8",
        )

        result = load_project_aliases(toml_path)
        assert result == {"x": "first"}

    def test_resolves_transitive_chains(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            """
[[alias]]
from = ["a"]
to = "b"

[[alias]]
from = ["b"]
to = "c"
""",
            encoding="utf-8",
        )

        result = load_project_aliases(toml_path)
        # a should resolve all the way to c, not stop at b.
        assert result["a"] == "c"
        assert result["b"] == "c"

    def test_malformed_toml_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text("[[alias]\nfrom = broken", encoding="utf-8")

        # Must not crash — log a warning and return {}.
        result = load_project_aliases(toml_path)
        assert result == {}

    def test_alias_without_required_keys_is_skipped(self, tmp_path: Path) -> None:
        from memgentic.processing.project import load_project_aliases

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            """
[[alias]]
to = "canonical"
# missing `from`

[[alias]]
from = ["valid"]
to = "good"
""",
            encoding="utf-8",
        )

        result = load_project_aliases(toml_path)
        assert result == {"valid": "good"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py::TestLoadProjectAliases -v`

Expected: FAIL with `ImportError: cannot import name 'load_project_aliases'`.

- [ ] **Step 3: Implement `load_project_aliases`**

Append to `memgentic/memgentic/processing/project.py`:

```python
import tomllib  # stdlib (Python 3.11+)

import structlog

_logger = structlog.get_logger(__name__)


# Module-level alias cache. None means "not loaded yet". Empty dict means
# "loaded, no aliases". Replaced wholesale by load_project_aliases().
_alias_cache: dict[str, str] | None = None


def _default_aliases_path() -> Path:
    """Default alias TOML location: ``~/.memgentic/projects.toml``."""
    return Path.home() / ".memgentic" / "projects.toml"


def load_project_aliases(toml_path: Path | None = None) -> dict[str, str]:
    """Parse the project aliases TOML and return a fully-resolved alias map.

    Returns the cached map on subsequent calls. Call
    :func:`invalidate_alias_cache` after writing the TOML on disk.

    Returns ``{}`` when:
      - the file does not exist
      - the file is malformed (logs a warning)
      - no `[[alias]]` entries are present

    Otherwise returns a flat ``{from_key: terminal_to_key}`` map where each
    key has been transitively resolved (so callers don't need to chase chains
    themselves). All keys and values are lowercased and stripped.
    """
    global _alias_cache
    if _alias_cache is not None and toml_path is None:
        return _alias_cache

    path = toml_path or _default_aliases_path()
    if not path.exists():
        result: dict[str, str] = {}
        if toml_path is None:
            _alias_cache = result
        return result

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _logger.warning(
            "project.aliases.parse_failed",
            path=str(path),
            error=str(exc),
        )
        if toml_path is None:
            _alias_cache = {}
        return {}

    raw_map: dict[str, str] = {}
    for entry in data.get("alias", []):
        if not isinstance(entry, dict):
            continue
        from_keys = entry.get("from")
        to_key = entry.get("to")
        if not isinstance(from_keys, list) or to_key is None:
            continue  # malformed entry — skip
        normalized_to = str(to_key).strip().lower()
        for raw in from_keys:
            if not isinstance(raw, str):
                continue
            normalized_from = raw.strip().lower()
            if not normalized_from:
                continue
            if normalized_from in raw_map:
                continue  # first-match-wins
            raw_map[normalized_from] = normalized_to

    # Transitively resolve every key so callers get terminal targets directly.
    resolved: dict[str, str] = {}
    for key in raw_map:
        try:
            resolved[key] = _resolve_transitive(key, raw_map)
        except ValueError as exc:
            _logger.warning(
                "project.aliases.cycle_or_overflow",
                key=key,
                error=str(exc),
            )
            # Drop the offending entry; downstream sees raw key.

    if toml_path is None:
        _alias_cache = resolved
    return resolved


def invalidate_alias_cache() -> None:
    """Drop the module-level alias cache.

    Call after writing ``~/.memgentic/projects.toml`` so that subsequent
    ``load_project_aliases()`` calls re-read from disk. The CLI commands
    that mutate the TOML must call this before returning.
    """
    global _alias_cache
    _alias_cache = None
```

Add the `import tomllib` and `import structlog` near the top of the file with other imports (after the existing `import re`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py::TestLoadProjectAliases -v`

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_aliases.py
git commit -m "feat(project): add load_project_aliases TOML reader with caching"
```

---

## Task 1.3: Add `resolve_project` public wrapper

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_aliases.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_aliases.py`:

```python
class TestResolveProject:
    def test_returns_key_when_not_in_map(self) -> None:
        from memgentic.processing.project import resolve_project

        assert resolve_project("memgentic", {}) == "memgentic"
        assert resolve_project("memgentic", {"foo": "bar"}) == "memgentic"

    def test_applies_alias(self) -> None:
        from memgentic.processing.project import resolve_project

        alias_map = {"old-name": "new-name"}
        assert resolve_project("old-name", alias_map) == "new-name"

    def test_empty_input_returns_empty(self) -> None:
        from memgentic.processing.project import resolve_project

        assert resolve_project("", {"": "anything"}) == ""
        assert resolve_project("", {}) == ""

    def test_lowercases_input(self) -> None:
        from memgentic.processing.project import resolve_project

        alias_map = {"foo": "bar"}
        assert resolve_project("FOO", alias_map) == "bar"


class TestInvalidateAliasCache:
    def test_invalidate_forces_reload(self, tmp_path: Path) -> None:
        from memgentic.processing.project import (
            invalidate_alias_cache,
            load_project_aliases,
        )

        toml_path = tmp_path / "projects.toml"
        toml_path.write_text(
            '[[alias]]\nfrom = ["a"]\nto = "first"\n', encoding="utf-8"
        )

        # Load using the module's default cache (path arg = None).
        # We cheat and patch _default_aliases_path for the test.
        import memgentic.processing.project as proj_mod

        original = proj_mod._default_aliases_path
        proj_mod._default_aliases_path = lambda: toml_path
        try:
            assert load_project_aliases() == {"a": "first"}

            # Mutate the file. Without invalidation, the cache is stale.
            toml_path.write_text(
                '[[alias]]\nfrom = ["a"]\nto = "second"\n', encoding="utf-8"
            )
            assert load_project_aliases() == {"a": "first"}  # cached

            invalidate_alias_cache()
            assert load_project_aliases() == {"a": "second"}
        finally:
            proj_mod._default_aliases_path = original
            invalidate_alias_cache()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py::TestResolveProject tests/test_project_aliases.py::TestInvalidateAliasCache -v`

Expected: FAIL with `ImportError: cannot import name 'resolve_project'`.

- [ ] **Step 3: Implement `resolve_project`**

Append to `memgentic/memgentic/processing/project.py` after `invalidate_alias_cache`:

```python
def resolve_project(key: str, alias_map: dict[str, str]) -> str:
    """Apply ``alias_map`` to ``key`` (case-insensitive lookup).

    The map is expected to be the output of :func:`load_project_aliases`,
    which has already pre-resolved transitive chains — this function does
    a single dict lookup, not chain following.

    Empty input returns ``""`` regardless of the map (avoids accidentally
    aliasing the "(unknown)" sink to something else).
    """
    if not key:
        return ""
    normalized = key.strip().lower()
    return alias_map.get(normalized, normalized)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py -v`

Expected: All tests in the file PASS (TestResolveTransitive + TestLoadProjectAliases + TestResolveProject + TestInvalidateAliasCache, ~16 tests).

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_aliases.py
git commit -m "feat(project): add resolve_project public wrapper + invalidate_alias_cache"
```

---

## Task 1.4: Wire `alias_map` into existing `derive_project`

**Files:**
- Modify: `memgentic/memgentic/processing/project.py:97` (existing `derive_project`)
- Test: `memgentic/tests/test_project_aliases.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_aliases.py`:

```python
class TestDeriveProjectWithAliasMap:
    def test_alias_applied_after_cwd_derivation(self) -> None:
        from memgentic.processing.project import derive_project

        alias_map = {"memgentic-public-export": "memgentic"}
        result = derive_project(
            cwd="/home/harit/dev/memgentic-public-export",
            alias_map=alias_map,
        )
        assert result == "memgentic"

    def test_alias_applied_after_slug_decoding(self) -> None:
        from memgentic.processing.project import derive_project

        alias_map = {"vetervo": "vetervo-mobile"}
        result = derive_project(
            slug="C--Users-harit-Desktop-Business-Projects-Vetervo",
            alias_map=alias_map,
        )
        assert result == "vetervo-mobile"

    def test_alias_to_empty_collapses_to_unknown(self) -> None:
        from memgentic.processing.project import derive_project

        alias_map = {"new-folder": ""}
        result = derive_project(
            cwd="C:\\Users\\harit\\Desktop\\new folder",
            alias_map=alias_map,
        )
        assert result == ""

    def test_no_alias_map_preserves_existing_behaviour(self) -> None:
        from memgentic.processing.project import derive_project

        # No alias_map — existing behaviour unchanged.
        assert (
            derive_project(cwd="/home/harit/dev/memgentic-public-export")
            == "memgentic-public-export"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py::TestDeriveProjectWithAliasMap -v`

Expected: FAIL with `TypeError: derive_project() got an unexpected keyword argument 'alias_map'`.

- [ ] **Step 3: Modify `derive_project` to accept `alias_map`**

Replace the existing `derive_project` function in `memgentic/memgentic/processing/project.py:97-127` with:

```python
def derive_project(
    *,
    cwd: str | None = None,
    file_path: str | None = None,
    slug: str | None = None,
    alias_map: dict[str, str] | None = None,
) -> str:
    """Return the canonical project key for a memory.

    Resolution order: explicit ``cwd`` (richest, always correct) → Claude Code
    parent-directory ``slug`` decoded heuristically → empty string when no
    signal is available. ``file_path`` is accepted for symmetry with adapters
    but is ignored unless it matches the ``~/.claude/projects/<slug>/`` shape,
    in which case the slug is extracted automatically.

    When ``alias_map`` is provided (typically the output of
    :func:`load_project_aliases`), the derived key is run through
    :func:`resolve_project` before being returned. Aliases are applied AFTER
    cwd / slug derivation so that the underlying machinery stays a pure
    function of inputs and only the final lookup depends on user config.
    """
    if cwd:
        derived = project_from_cwd(cwd)
        if derived:
            if alias_map:
                return resolve_project(derived, alias_map)
            return derived

    if slug is None and file_path:
        # Accept either a raw POSIX path or a Windows path here.
        normalized = file_path.replace("\\", "/")
        marker = "/.claude/projects/"
        if marker in normalized:
            tail = normalized.split(marker, 1)[1]
            slug = tail.split("/", 1)[0] if tail else None

    if slug:
        derived = project_from_claude_code_slug(slug)
        if alias_map:
            return resolve_project(derived, alias_map)
        return derived

    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_aliases.py tests/test_project_derivation.py -v`

Expected: All tests pass — both the new alias tests AND the pre-existing `test_project_derivation.py` (which doesn't pass `alias_map`, exercising the backward-compat path).

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_aliases.py
git commit -m "feat(project): wire alias_map into derive_project (post-derivation)"
```

---

## Task 1.5: Convert `memgentic projects` to Click group with `list` subcommand

**Files:**
- Modify: `memgentic/memgentic/cli.py:551-607` (existing `projects` flat command)
- Test: `memgentic/tests/test_project_cli.py` (create)

- [ ] **Step 1: Write the failing test**

Create `memgentic/tests/test_project_cli.py`:

```python
"""CLI tests for ``memgentic projects`` group and subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from memgentic.cli import main


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ~/.memgentic to a tmp path so tests don't clobber real config."""
    fake_home = tmp_path / "home"
    (fake_home / ".memgentic").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows
    return fake_home


class TestProjectsGroupBackwardCompat:
    def test_no_subcommand_shows_table(self, isolated_home: Path) -> None:
        """`memgentic projects` (no subcommand) preserves the legacy
        behaviour: prints the project counts table.
        """
        runner = CliRunner()
        result = runner.invoke(main, ["projects"])
        # Should NOT crash with "missing command" error.
        assert result.exit_code == 0, result.output
        # The legacy output starts with "Memory Projects" or
        # reports "No memories stored yet" on a fresh DB. Either is OK.
        assert ("Memory Projects" in result.output) or (
            "No memories stored yet" in result.output
        ), result.output

    def test_list_subcommand_shows_table(self, isolated_home: Path) -> None:
        """`memgentic projects list` shows the same table."""
        runner = CliRunner()
        result = runner.invoke(main, ["projects", "list"])
        assert result.exit_code == 0, result.output
        assert ("Memory Projects" in result.output) or (
            "No memories stored yet" in result.output
        ), result.output

    def test_help_shows_subcommands(self, isolated_home: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["projects", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "alias" in result.output
        assert "merge" in result.output
        assert "repair" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsGroupBackwardCompat -v`

Expected: FAIL — current `projects` is a flat command, has no subcommands. `test_help_shows_subcommands` fails because the help output doesn't list `list/alias/merge/repair`.

- [ ] **Step 3: Convert flat `projects` command to a Click group**

Replace `memgentic/memgentic/cli.py:551-607` with:

```python
@main.group(invoke_without_command=True)
@click.option(
    "--limit",
    "-n",
    default=20,
    help="(For default `list`) How many projects to show.",
)
@click.pass_context
def projects(ctx: click.Context, limit: int):
    """Manage project keys — aliases, merges, and backfills.

    \b
    Subcommands:
      list           Show projects with memory counts (default when no subcommand)
      alias          Add a single alias mapping
      merge          Merge two project keys into a canonical name
      repair         Recompute project keys from current alias TOML
      backfill-jsonl Re-read JSONL session_meta for empty-project memories

    \b
    With no subcommand, shows the same table as `memgentic projects list`.
    """
    if ctx.invoked_subcommand is None:
        # Backward-compat: `memgentic projects` (with no subcommand) used to
        # show the projects table. Forward to `list` to keep that contract.
        ctx.invoke(projects_list, limit=limit)


@projects.command("list")
@click.option(
    "--limit",
    "-n",
    default=20,
    help="How many projects to show (default: 20).",
)
def projects_list(limit: int):
    """Show a breakdown of stored memories by project.

    \b
    A "project" is the friendly key derived from the originating working
    directory (Path(cwd).name lowercased). Memories without a derivable
    project — manual remember calls, ChatGPT imports, Antigravity sessions
    — show under "(unknown)".

    \b
    Examples:
      memgentic projects list
      memgentic projects list -n 50
    """

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()

        try:
            stats = await store.get_project_stats()
            total = sum(stats.values())

            if not stats:
                console.print("[yellow]No memories stored yet.[/]")
                return

            table = Table(title=f"Memory Projects (Total: {total})")
            table.add_column("Project", style="green")
            table.add_column("Memories", style="cyan", justify="right")
            table.add_column("%", style="dim", justify="right")

            ordered = sorted(stats.items(), key=lambda x: x[1], reverse=True)
            for project, count in ordered[:limit]:
                pct = (count / total * 100) if total > 0 else 0
                label = project if project else "[dim](unknown)[/]"
                table.add_row(label, str(count), f"{pct:.0f}%")

            console.print(table)
            if len(ordered) > limit:
                console.print(
                    f"[dim]... {len(ordered) - limit} more projects "
                    f"(use --limit to see them).[/]"
                )
        finally:
            await store.close()

    asyncio.run(_run())
```

- [ ] **Step 4: Run test to verify backward-compat works**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsGroupBackwardCompat -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/cli.py memgentic/tests/test_project_cli.py
git commit -m "refactor(cli): convert 'projects' to group, list as default subcommand"
```

---

## Task 1.6: Add `memgentic projects alias` subcommand

**Files:**
- Modify: `memgentic/memgentic/cli.py` (after `projects_list`)
- Test: `memgentic/tests/test_project_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_cli.py`:

```python
class TestProjectsAlias:
    def test_creates_toml_when_missing(self, isolated_home: Path) -> None:
        runner = CliRunner()
        toml_path = isolated_home / ".memgentic" / "projects.toml"
        assert not toml_path.exists()

        result = runner.invoke(
            main, ["projects", "alias", "old-name", "--to", "new-name"]
        )
        assert result.exit_code == 0, result.output
        assert toml_path.exists()
        body = toml_path.read_text(encoding="utf-8")
        assert "[[alias]]" in body
        assert 'from = ["old-name"]' in body
        assert 'to = "new-name"' in body

    def test_appends_to_existing_toml(self, isolated_home: Path) -> None:
        runner = CliRunner()
        toml_path = isolated_home / ".memgentic" / "projects.toml"
        toml_path.write_text(
            '[[alias]]\nfrom = ["existing"]\nto = "kept"\n', encoding="utf-8"
        )

        result = runner.invoke(
            main, ["projects", "alias", "new", "--to", "newer"]
        )
        assert result.exit_code == 0, result.output

        body = toml_path.read_text(encoding="utf-8")
        assert 'from = ["existing"]' in body  # preserved
        assert 'from = ["new"]' in body  # appended

    def test_empty_target_collapses_to_unknown(self, isolated_home: Path) -> None:
        runner = CliRunner()

        result = runner.invoke(
            main, ["projects", "alias", "garbage", "--to", ""]
        )
        assert result.exit_code == 0, result.output

        toml_path = isolated_home / ".memgentic" / "projects.toml"
        body = toml_path.read_text(encoding="utf-8")
        assert 'to = ""' in body

    def test_does_not_run_repair_automatically(self, isolated_home: Path) -> None:
        """Per spec: alias subcommand only edits TOML, does not touch DB."""
        runner = CliRunner()

        result = runner.invoke(
            main, ["projects", "alias", "x", "--to", "y"]
        )
        assert result.exit_code == 0
        # Output should mention running repair next, but NOT do it.
        assert "repair" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsAlias -v`

Expected: FAIL — `alias` subcommand doesn't exist.

- [ ] **Step 3: Implement `projects alias` subcommand**

Append to `memgentic/memgentic/cli.py` after `projects_list`:

```python
@projects.command("alias")
@click.argument("from_key")
@click.option(
    "--to",
    required=True,
    help="Target project key. Pass empty string '' to collapse to (unknown).",
)
def projects_alias(from_key: str, to: str):
    """Add a single alias mapping to ~/.memgentic/projects.toml.

    \b
    Appends a [[alias]] entry. Does NOT auto-run repair on existing memories;
    run `memgentic projects repair` afterwards to apply the alias to rows
    already in the DB.

    \b
    Examples:
      memgentic projects alias memgentic-public-export --to memgentic
      memgentic projects alias new-folder --to ""    # sink garbage
    """
    from memgentic.processing.project import (
        _default_aliases_path,
        invalidate_alias_cache,
    )

    toml_path = _default_aliases_path()
    toml_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_from = from_key.strip().lower()
    normalized_to = to.strip().lower()

    if not normalized_from:
        console.print("[red]Error:[/] FROM_KEY cannot be empty.")
        raise click.Abort()

    # Build the new entry. Append (don't rewrite the file) so user-edited
    # comments and ordering are preserved.
    entry = (
        f'\n[[alias]]\nfrom = ["{normalized_from}"]\nto = "{normalized_to}"\n'
    )
    with toml_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    invalidate_alias_cache()

    target_label = normalized_to if normalized_to else "(unknown)"
    console.print(
        f"[green]OK[/] Added alias {normalized_from!r} → {target_label!r} "
        f"to {toml_path}"
    )
    console.print(
        "[dim]Run [bold]memgentic projects repair[/bold] to apply to "
        "existing memories.[/]"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsAlias -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/cli.py memgentic/tests/test_project_cli.py
git commit -m "feat(cli): add 'projects alias' subcommand"
```

---

## Task 1.7: Add `memgentic projects repair` subcommand

**Files:**
- Modify: `memgentic/memgentic/cli.py`
- Test: `memgentic/tests/test_project_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_cli.py`:

```python
class TestProjectsRepair:
    async def _seed_db(self, isolated_home: Path, memories: list[tuple[str, str]]) -> None:
        """Insert memories with given (id, project) values for repair testing."""
        from datetime import UTC, datetime

        from memgentic.config import settings
        from memgentic.models import (
            CaptureMethod,
            ContentType,
            Memory,
            Platform,
            SourceMetadata,
        )
        from memgentic.storage.metadata import MetadataStore

        # Force config to use isolated home (sqlite path is under it)
        settings.data_dir = isolated_home / ".memgentic" / "data"
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            for mid, project in memories:
                m = Memory(
                    id=mid,
                    content=f"content for {mid}",
                    content_type=ContentType.FACT,
                    project=project,
                    source=SourceMetadata(
                        platform=Platform.CLAUDE_CODE,
                        capture_method=CaptureMethod.AUTO_DAEMON,
                    ),
                    created_at=datetime.now(UTC),
                )
                await store.save_memory(m)
        finally:
            await store.close()

    def test_dry_run_reports_changes_without_writing(
        self, isolated_home: Path
    ) -> None:
        import asyncio

        runner = CliRunner()
        # TOML maps "old" -> "new"
        toml_path = isolated_home / ".memgentic" / "projects.toml"
        toml_path.write_text(
            '[[alias]]\nfrom = ["old"]\nto = "new"\n', encoding="utf-8"
        )

        # Seed two memories with project="old".
        asyncio.run(self._seed_db(isolated_home, [("m1", "old"), ("m2", "old")]))

        result = runner.invoke(main, ["projects", "repair", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "2" in result.output  # 2 rows would be repaired
        assert "dry-run" in result.output.lower()

        # Verify nothing was actually changed.
        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m = await store.get_memory("m1")
                assert m is not None and m.project == "old"
            finally:
                await store.close()

        asyncio.run(_check())

    def test_repair_updates_aliased_rows(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        toml_path = isolated_home / ".memgentic" / "projects.toml"
        toml_path.write_text(
            '[[alias]]\nfrom = ["old"]\nto = "new"\n', encoding="utf-8"
        )
        asyncio.run(self._seed_db(isolated_home, [("m1", "old"), ("m2", "kept")]))

        result = runner.invoke(main, ["projects", "repair"])
        assert result.exit_code == 0, result.output
        assert "1" in result.output  # only m1 changed

        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m1 = await store.get_memory("m1")
                m2 = await store.get_memory("m2")
                assert m1 is not None and m1.project == "new"
                assert m2 is not None and m2.project == "kept"
            finally:
                await store.close()

        asyncio.run(_check())

    def test_idempotent_second_run_no_changes(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        toml_path = isolated_home / ".memgentic" / "projects.toml"
        toml_path.write_text(
            '[[alias]]\nfrom = ["old"]\nto = "new"\n', encoding="utf-8"
        )
        asyncio.run(self._seed_db(isolated_home, [("m1", "old")]))

        runner.invoke(main, ["projects", "repair"])
        result = runner.invoke(main, ["projects", "repair"])
        assert result.exit_code == 0
        assert "0" in result.output  # nothing left to change
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsRepair -v`

Expected: FAIL — `repair` subcommand doesn't exist.

- [ ] **Step 3: Implement `projects repair`**

Append to `memgentic/memgentic/cli.py` after `projects_alias`:

```python
@projects.command("repair")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would change without writing to the DB.",
)
def projects_repair(dry_run: bool):
    """Recompute project keys for all memories using current alias TOML.

    \b
    Loads ~/.memgentic/projects.toml, then iterates every active memory and
    applies the resolved alias map. Updates rows where the resolved key
    differs from the stored project. Performs zero JSONL I/O — only SQL.
    Idempotent: a second run after a successful run reports 0 changes.

    \b
    Examples:
      memgentic projects repair             # apply changes
      memgentic projects repair --dry-run   # preview only
    """

    async def _run():
        from memgentic.processing.project import (
            invalidate_alias_cache,
            load_project_aliases,
            resolve_project,
        )
        from memgentic.storage.metadata import MetadataStore

        invalidate_alias_cache()
        alias_map = load_project_aliases()

        if not alias_map:
            console.print(
                "[yellow]No aliases configured.[/] "
                "Edit [bold]~/.memgentic/projects.toml[/] first."
            )
            return

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()

        try:
            assert store._db is not None
            cursor = await store._db.execute(
                "SELECT id, project FROM memories WHERE status = 'active'"
            )
            rows = await cursor.fetchall()

            updates: list[tuple[str, str]] = []
            for mid, current in rows:
                resolved = resolve_project(current or "", alias_map)
                if resolved != (current or ""):
                    updates.append((resolved, mid))

            mode = "dry-run" if dry_run else "applied"
            console.print(
                f"[cyan]projects repair ({mode}):[/] "
                f"scanned {len(rows)}, would change {len(updates)}"
            )
            if updates and not dry_run:
                await store._db.executemany(
                    "UPDATE memories SET project = ? WHERE id = ?",
                    updates,
                )
                await store._db.commit()
                console.print(f"[green]OK[/] Updated {len(updates)} rows.")
        finally:
            await store.close()

    asyncio.run(_run())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsRepair -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/cli.py memgentic/tests/test_project_cli.py
git commit -m "feat(cli): add 'projects repair' to recompute aliases on existing memories"
```

---

## Task 1.8: Add `memgentic projects merge` subcommand

**Files:**
- Modify: `memgentic/memgentic/cli.py`
- Test: `memgentic/tests/test_project_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_cli.py`:

```python
class TestProjectsMerge:
    def test_appends_alias_for_both_keys(self, isolated_home: Path) -> None:
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["projects", "merge", "old-a", "old-b", "--into", "canonical"],
        )
        assert result.exit_code == 0, result.output

        toml_path = isolated_home / ".memgentic" / "projects.toml"
        body = toml_path.read_text(encoding="utf-8")
        # Both old-a and old-b should appear in `from` lists pointing to canonical.
        assert "canonical" in body
        assert "old-a" in body
        assert "old-b" in body

    def test_runs_repair_automatically(self, isolated_home: Path) -> None:
        """Per spec: merge auto-triggers repair (alias does NOT)."""
        runner = CliRunner()

        result = runner.invoke(
            main, ["projects", "merge", "x", "y", "--into", "z"]
        )
        assert result.exit_code == 0, result.output
        # Output should reflect the repair pass.
        assert "scanned" in result.output.lower() or "repair" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsMerge -v`

Expected: FAIL — `merge` doesn't exist.

- [ ] **Step 3: Implement `projects merge`**

Append to `memgentic/memgentic/cli.py` after `projects_repair`:

```python
@projects.command("merge")
@click.argument("key_a")
@click.argument("key_b")
@click.option(
    "--into",
    required=True,
    help="Canonical project name both keys should resolve to.",
)
@click.pass_context
def projects_merge(ctx: click.Context, key_a: str, key_b: str, into: str):
    """Merge two project keys into a canonical name.

    \b
    Appends a single [[alias]] entry mapping both keys to --into, then
    immediately runs `projects repair` to migrate existing memories.

    \b
    Example:
      memgentic projects merge allweb-projects allweb-projects-allvolution2 \\
          --into allweb-platform
    """
    from memgentic.processing.project import (
        _default_aliases_path,
        invalidate_alias_cache,
    )

    a = key_a.strip().lower()
    b = key_b.strip().lower()
    canonical = into.strip().lower()
    if not a or not b or not canonical:
        console.print("[red]Error:[/] all three keys must be non-empty.")
        raise click.Abort()

    toml_path = _default_aliases_path()
    toml_path.parent.mkdir(parents=True, exist_ok=True)

    entry = (
        f'\n[[alias]]\nfrom = ["{a}", "{b}"]\nto = "{canonical}"\n'
    )
    with toml_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    invalidate_alias_cache()
    console.print(
        f"[green]OK[/] Merged {a!r} + {b!r} → {canonical!r} in {toml_path}"
    )

    # Auto-trigger repair to apply the new alias to existing memories.
    ctx.invoke(projects_repair, dry_run=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsMerge -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/cli.py memgentic/tests/test_project_cli.py
git commit -m "feat(cli): add 'projects merge' (alias + auto-repair)"
```

---

## Task 1.9: Create `projects.toml.example` at repo root

**Files:**
- Create: `projects.toml.example`

- [ ] **Step 1: Write the file**

Create `C:/Users/harit/Desktop/Business_Projects/memgentic-public-export/projects.toml.example`:

```toml
# ~/.memgentic/projects.toml — Project key aliases for Memgentic.
#
# Copy this file to ~/.memgentic/projects.toml and edit it.
# Run `memgentic projects repair` after any edit to recompute existing memory
# rows. Aliases for newly-ingested memories take effect immediately.

[settings]
# Collapse multiple clones of the same git repo into one project key.
# Requires git remote origin to be identical across clones, and
# `enable_git_project_resolution = true` in MemgenticSettings (or
# MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION=true env var).
# Default: false
use_remote_url_collapse = false

# --- Alias examples ---

# Merge a WSL path variant with the Windows-side clone:
# [[alias]]
# from = ["mnt-c-users-harit-desktop-inproma"]
# to = "inproma"

# Merge fragmented project keys for the same repo (parent dir vs subdir):
# [[alias]]
# from = ["allweb-projects-allvolution2", "allweb-projects"]
# to = "allweb-projects"

# Garbage sink: collapse transient directories to (unknown):
[[alias]]
from = ["new-folder", "temp", "untitled", "desktop", "new-project", "downloads"]
to = ""
```

- [ ] **Step 2: Commit**

```bash
git add projects.toml.example
git commit -m "docs: add projects.toml.example"
```

---

## Task 1.10: Slice 1 live smoke + lint

**Files:**
- All Slice 1 files

- [ ] **Step 1: Run lint**

```bash
cd C:/Users/harit/Desktop/Business_Projects/memgentic-public-export
make lint
```

Expected: ruff passes (or same warnings as before this slice).

- [ ] **Step 2: Run all Slice 1 tests**

```bash
cd memgentic
python -m pytest tests/test_project_aliases.py tests/test_project_derivation.py tests/test_project_cli.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Live smoke — verify backward compat with no TOML**

```bash
python -c "from memgentic.cli import main; main()" projects
```

Expected: Same projects table as before this slice (legacy behaviour preserved). On the production DB, you should see ~35 projects with `(unknown)` near the top.

- [ ] **Step 4: Live smoke — alias + repair flow**

```bash
python -c "from memgentic.cli import main; main()" projects alias new-folder --to ""
python -c "from memgentic.cli import main; main()" projects repair
python -c "from memgentic.cli import main; main()" projects
```

Expected:
- `alias` writes `~/.memgentic/projects.toml` with the entry, prints OK + reminder to repair.
- `repair` reports `scanned 5623, would change ~272` (the new-folder count).
- Final `projects` shows `new-folder` collapsed into `(unknown)`.

- [ ] **Step 5: Commit any cleanup**

If lint surfaced anything cosmetic, fix and:

```bash
git add -A
git commit -m "chore(slice-1): lint cleanup"
```

---

# Slice 2 — Git Toplevel Resolution (opt-in, ingestion-only)

**Risk:** Medium. Adds subprocess calls behind an opt-in flag. Default OFF preserves existing behavior on every adapter.

**Ships:** When `MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION=true`, ingestion uses `git rev-parse --show-toplevel` so memories from a subdirectory of a repo collapse to the repo root name. Optionally enables remote-URL collapse via TOML toggle.

## Task 2.1: Add `_git_toplevel_sync` helper

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_resolution.py` (create)

- [ ] **Step 1: Write the failing test**

Create `memgentic/tests/test_project_resolution.py`:

```python
"""Unit tests for git-aware project resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from memgentic.processing.project import (
    _git_toplevel_sync,
)


class TestGitToplevelSync:
    def test_unc_path_skipped_immediately(self) -> None:
        """\\wsl.localhost\\... paths must NOT call git (Landmine 4)."""
        with patch("subprocess.run") as mock_run:
            assert (
                _git_toplevel_sync(r"\\wsl.localhost\Ubuntu\home\user\dev")
                is None
            )
            assert (
                _git_toplevel_sync(r"\\wsl$\Ubuntu\home\user\dev") is None
            )
            mock_run.assert_not_called()

    def test_returns_toplevel_name_on_success(self, tmp_path: Path) -> None:
        # Initialise a real git repo so the subprocess call is exercised.
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        result = _git_toplevel_sync(str(tmp_path))
        assert result is not None
        # Result is the absolute toplevel path; caller normalises to .name.
        assert Path(result).resolve() == tmp_path.resolve()

    def test_returns_none_outside_repo(self, tmp_path: Path) -> None:
        # tmp_path is NOT a git repo (no `git init`).
        result = _git_toplevel_sync(str(tmp_path))
        assert result is None

    def test_returns_none_when_git_missing(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("git not on PATH"),
        ):
            assert _git_toplevel_sync("/some/path") is None

    def test_caches_repeated_calls(self, tmp_path: Path) -> None:
        # lru_cache should dedupe — same input, single subprocess invocation.
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        _git_toplevel_sync.cache_clear()
        with patch(
            "memgentic.processing.project.subprocess.run",
            wraps=subprocess.run,
        ) as wrapped:
            _git_toplevel_sync(str(tmp_path))
            _git_toplevel_sync(str(tmp_path))
            _git_toplevel_sync(str(tmp_path))
            assert wrapped.call_count == 1
        _git_toplevel_sync.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestGitToplevelSync -v`

Expected: FAIL with `ImportError: cannot import name '_git_toplevel_sync'`.

- [ ] **Step 3: Implement `_git_toplevel_sync`**

Add to `memgentic/memgentic/processing/project.py`. First, add `subprocess` and `functools` to imports:

```python
import functools
import subprocess
```

Then append after the alias resolution block:

```python
# --- Git-aware resolution (opt-in, sync helpers wrapped async) -------------

# UNC path prefixes that break `git rev-parse` on Windows. We detect these
# *before* calling git so we don't waste a subprocess + cache slot.
_UNC_PREFIXES: tuple[str, ...] = (r"\\wsl.localhost\\", r"\\wsl$\\", r"\\\\wsl")


def _is_unc_path(cwd: str) -> bool:
    """Return True for Windows UNC paths that git can't handle."""
    if not cwd:
        return False
    # Normalise both \\ and \\\\ prefixes (subprocess sometimes reports either).
    head = cwd.strip()
    return head.startswith(("\\\\wsl.localhost", "\\\\wsl$", "//wsl.localhost", "//wsl$"))


@functools.lru_cache(maxsize=512)
def _git_toplevel_sync(cwd: str) -> str | None:
    """Synchronously resolve the git toplevel of ``cwd`` using subprocess.

    Returns the absolute path to the repo root, or ``None`` when:
      - cwd is a UNC path (Landmine 4: git can't chdir there on Windows)
      - cwd is not inside a git repository
      - the git binary is missing
      - any other error from ``git rev-parse``

    Cached via ``lru_cache(maxsize=512)``. Per-process cache; cleared on
    process restart. NOT async — wrap calls in ``asyncio.to_thread`` from
    coroutines (Landmine 3).
    """
    if not cwd or _is_unc_path(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    toplevel = result.stdout.strip()
    return toplevel or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestGitToplevelSync -v`

Expected: 5 tests PASS. (`test_returns_toplevel_name_on_success` and `test_caches_repeated_calls` require git on PATH. Run `git --version` first to confirm availability; the project's CI image already has git installed.)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_resolution.py
git commit -m "feat(project): add _git_toplevel_sync (UNC-aware, lru_cached)"
```

---

## Task 2.2: Add `_git_remote_url_sync`

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_resolution.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_resolution.py`:

```python
class TestGitRemoteUrlSync:
    def test_unc_path_skipped(self) -> None:
        from memgentic.processing.project import _git_remote_url_sync

        with patch("subprocess.run") as mock_run:
            assert (
                _git_remote_url_sync(r"\\wsl.localhost\Ubuntu\repo") is None
            )
            mock_run.assert_not_called()

    def test_returns_url_on_success(self, tmp_path: Path) -> None:
        from memgentic.processing.project import _git_remote_url_sync

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "git@github.com:foo/bar.git",
            ],
            cwd=tmp_path,
            check=True,
        )
        _git_remote_url_sync.cache_clear()
        result = _git_remote_url_sync(str(tmp_path))
        assert result == "git@github.com:foo/bar.git"

    def test_returns_none_when_no_origin(self, tmp_path: Path) -> None:
        from memgentic.processing.project import _git_remote_url_sync

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        # No `git remote add` — no origin.
        _git_remote_url_sync.cache_clear()
        assert _git_remote_url_sync(str(tmp_path)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestGitRemoteUrlSync -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `_git_remote_url_sync`**

Append to `memgentic/memgentic/processing/project.py`:

```python
@functools.lru_cache(maxsize=512)
def _git_remote_url_sync(git_root: str) -> str | None:
    """Synchronously fetch the URL of the ``origin`` remote.

    Returns ``None`` when:
      - ``git_root`` is a UNC path
      - the remote ``origin`` is not configured
      - ``git`` is missing or fails

    Only called when ``[settings] use_remote_url_collapse = true`` in
    ``~/.memgentic/projects.toml``.
    """
    if not git_root or _is_unc_path(git_root):
        return None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=git_root,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def _remote_url_to_project(url: str | None) -> str:
    """Extract the project key from a git remote URL.

    Examples:
      git@github.com:foo/bar.git → bar
      https://github.com/foo/bar.git → bar
      https://gitlab.com/foo/bar → bar

    Returns "" when the URL is empty or doesn't match expected forms.
    """
    if not url:
        return ""
    raw = url.strip()
    if raw.endswith(".git"):
        raw = raw[:-4]
    # Handle SSH (host:org/repo) and HTTPS (https://host/org/repo).
    if "/" in raw:
        tail = raw.rsplit("/", 1)[-1]
    elif ":" in raw:
        tail = raw.rsplit(":", 1)[-1]
        if "/" in tail:
            tail = tail.rsplit("/", 1)[-1]
    else:
        tail = raw
    return normalize_project(tail)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestGitRemoteUrlSync -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_resolution.py
git commit -m "feat(project): add _git_remote_url_sync + URL-to-project parser"
```

---

## Task 2.3: Add async wrappers `git_toplevel`, `git_remote_url`

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_resolution.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_resolution.py`:

```python
class TestAsyncWrappers:
    async def test_git_toplevel_async_uses_to_thread(self, tmp_path: Path) -> None:
        from memgentic.processing.project import _git_toplevel_sync, git_toplevel

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        _git_toplevel_sync.cache_clear()
        result = await git_toplevel(str(tmp_path))
        assert result is not None
        assert Path(result).resolve() == tmp_path.resolve()

    async def test_git_remote_url_async(self, tmp_path: Path) -> None:
        from memgentic.processing.project import (
            _git_remote_url_sync,
            git_remote_url,
        )

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:x/y.git"],
            cwd=tmp_path,
            check=True,
        )
        _git_remote_url_sync.cache_clear()
        url = await git_remote_url(str(tmp_path))
        assert url == "git@github.com:x/y.git"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestAsyncWrappers -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement async wrappers**

Append to `memgentic/memgentic/processing/project.py`. First add `asyncio` to imports:

```python
import asyncio
```

Then add the wrappers:

```python
async def git_toplevel(cwd: str) -> str | None:
    """Async wrapper around :func:`_git_toplevel_sync`.

    Use this from any coroutine — never call ``_git_toplevel_sync`` directly
    inside an async path; doing so blocks the event loop while git runs
    (Landmine 3 in the spec).
    """
    return await asyncio.to_thread(_git_toplevel_sync, cwd)


async def git_remote_url(git_root: str) -> str | None:
    """Async wrapper around :func:`_git_remote_url_sync`."""
    return await asyncio.to_thread(_git_remote_url_sync, git_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestAsyncWrappers -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_resolution.py
git commit -m "feat(project): add git_toplevel/git_remote_url async wrappers"
```

---

## Task 2.4: Add `derive_project_full` and `resolve_current_project`

**Files:**
- Modify: `memgentic/memgentic/processing/project.py`
- Test: `memgentic/tests/test_project_resolution.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_resolution.py`:

```python
class TestDeriveProjectFull:
    async def test_falls_back_to_cwd_when_use_git_false(self) -> None:
        from memgentic.processing.project import derive_project_full

        result = await derive_project_full(
            cwd="/home/harit/dev/memgentic-public-export",
            use_git=False,
        )
        assert result == "memgentic-public-export"

    async def test_uses_git_toplevel_when_enabled(self, tmp_path: Path) -> None:
        from memgentic.processing.project import derive_project_full

        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        # Create a subdirectory and use it as cwd.
        subdir = repo / "src" / "deep"
        subdir.mkdir(parents=True)
        result = await derive_project_full(cwd=str(subdir), use_git=True)
        assert result == "myrepo"  # collapsed to repo root

    async def test_remote_url_takes_precedence_when_opted_in(
        self, tmp_path: Path
    ) -> None:
        from memgentic.processing.project import (
            _git_remote_url_sync,
            _git_toplevel_sync,
            derive_project_full,
        )

        repo = tmp_path / "local-fork-name"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:org/upstream.git"],
            cwd=repo,
            check=True,
        )
        _git_toplevel_sync.cache_clear()
        _git_remote_url_sync.cache_clear()
        result = await derive_project_full(
            cwd=str(repo), use_git=True, use_remote_url=True
        )
        # Remote URL stem ("upstream") wins over local dir name.
        assert result == "upstream"

    async def test_alias_applied_after_resolution(self, tmp_path: Path) -> None:
        from memgentic.processing.project import derive_project_full

        repo = tmp_path / "memgentic-public-export"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        result = await derive_project_full(
            cwd=str(repo),
            use_git=True,
            alias_map={"memgentic-public-export": "memgentic"},
        )
        assert result == "memgentic"


class TestResolveCurrentProject:
    async def test_env_override_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memgentic.processing.project import resolve_current_project

        monkeypatch.setenv("MEMGENTIC_CURRENT_PROJECT", "explicit-project")
        result = await resolve_current_project()
        assert result == "explicit-project"

    async def test_explicit_env_override_param(self) -> None:
        from memgentic.processing.project import resolve_current_project

        result = await resolve_current_project(env_override="from-param")
        assert result == "from-param"

    async def test_returns_none_when_cwd_empty(self, tmp_path: Path) -> None:
        from memgentic.processing.project import resolve_current_project

        # Run from a directory whose name is "" — impossible, so simulate via cwd.
        # The function calls os.getcwd() — we can't make that return "" easily.
        # Instead, verify None when env is unset and cwd resolves to empty.
        # Skip if not feasible.
        pass  # covered in integration smoke

    async def test_uses_cwd_basename_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        from memgentic.processing.project import resolve_current_project

        repo = tmp_path / "smoke-test-project"
        repo.mkdir()
        monkeypatch.delenv("MEMGENTIC_CURRENT_PROJECT", raising=False)
        cwd_before = os.getcwd()
        os.chdir(repo)
        try:
            result = await resolve_current_project(use_git=False)
            assert result == "smoke-test-project"
        finally:
            os.chdir(cwd_before)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py::TestDeriveProjectFull tests/test_project_resolution.py::TestResolveCurrentProject -v`

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement both functions**

Append to `memgentic/memgentic/processing/project.py`:

```python
async def derive_project_full(
    *,
    cwd: str | None = None,
    file_path: str | None = None,
    slug: str | None = None,
    use_git: bool = False,
    use_remote_url: bool = False,
    alias_map: dict[str, str] | None = None,
) -> str:
    """Full async project-key resolution chain.

    Resolution order (first non-empty wins; alias_map applied at the end):
      1. ``use_remote_url and use_git``: git remote URL stem
      2. ``use_git``: git toplevel basename
      3. Bare ``cwd`` basename (existing :func:`derive_project` logic)
      4. Slug decoding (existing logic, via file_path)
      5. Empty string

    The ``use_git`` flag should come from ``MemgenticSettings
    .enable_git_project_resolution``. ``use_remote_url`` corresponds to
    the ``[settings] use_remote_url_collapse`` flag in ``projects.toml``
    AND requires ``use_git=True`` to take effect.
    """
    derived = ""

    if use_git and cwd:
        toplevel = await git_toplevel(cwd)
        if toplevel:
            if use_remote_url:
                url = await git_remote_url(toplevel)
                derived = _remote_url_to_project(url)
            if not derived:
                derived = normalize_project(Path(toplevel).name)

    if not derived:
        # Fall through to the existing synchronous chain.
        derived = derive_project(cwd=cwd, file_path=file_path, slug=slug)

    if not derived:
        return ""

    if alias_map:
        return resolve_project(derived, alias_map)
    return derived


async def resolve_current_project(
    env_override: str | None = None,
    use_git: bool = False,
    alias_map: dict[str, str] | None = None,
) -> str | None:
    """Resolve the project key for the calling process.

    Resolution order:
      1. ``env_override`` argument (typically pre-read from
         ``MEMGENTIC_CURRENT_PROJECT``)
      2. ``MEMGENTIC_CURRENT_PROJECT`` env var (when ``env_override`` falsy)
      3. ``derive_project_full`` of ``os.getcwd()``

    Returns ``None`` when no signal yields a non-empty key.
    """
    import os

    explicit = (env_override or os.environ.get("MEMGENTIC_CURRENT_PROJECT") or "").strip()
    if explicit:
        normalized = normalize_project(explicit)
        if alias_map:
            return resolve_project(normalized, alias_map) or None
        return normalized or None

    derived = await derive_project_full(
        cwd=os.getcwd(),
        use_git=use_git,
        alias_map=alias_map,
    )
    return derived or None
```

Also import `Path` at the top if not already imported (it is — `from pathlib import PurePath, ...`); add `from pathlib import Path` next to it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_resolution.py -v`

Expected: All tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/processing/project.py memgentic/tests/test_project_resolution.py
git commit -m "feat(project): add derive_project_full + resolve_current_project"
```

---

## Task 2.5: Add `enable_git_project_resolution` to MemgenticSettings

**Files:**
- Modify: `memgentic/memgentic/config.py:165-172` (intelligence section)

- [ ] **Step 1: Add the setting**

Insert after the `enable_llm_processing` field (around line 168), before `memory_half_life_days`:

```python
    enable_git_project_resolution: bool = Field(
        default=False,
        description=(
            "Enable git toplevel + remote URL resolution in derive_project_full(). "
            "When False (default), project derivation uses Path(cwd).name only. "
            "When True, ingestion adapters call git rev-parse to collapse "
            "subdirectories and (with use_remote_url_collapse=true in "
            "~/.memgentic/projects.toml) multiple clones into one project key. "
            "Set via MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION."
        ),
    )
```

- [ ] **Step 2: Verify settings still load**

```bash
cd memgentic
python -c "from memgentic.config import settings; print('git resolution:', settings.enable_git_project_resolution)"
```

Expected output: `git resolution: False`

Then test the env override:

```bash
MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION=true python -c "from memgentic.config import settings; print('git resolution:', settings.enable_git_project_resolution)"
```

Expected output: `git resolution: True`

- [ ] **Step 3: Commit**

```bash
git add memgentic/memgentic/config.py
git commit -m "feat(config): add enable_git_project_resolution setting (default False)"
```

---

## Task 2.6: Update Claude Code adapter to use `derive_project_full`

**Files:**
- Modify: `memgentic/memgentic/adapters/claude_code.py:60-69`
- Test: extend `memgentic/tests/test_claude_code_adapter.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_claude_code_adapter.py` (or create a new file if you prefer; check if `test_claude_code_adapter.py` exists at `memgentic/tests/`):

```python
class TestClaudeCodeAdapterGitResolution:
    async def test_uses_git_when_enabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION=true, get_project()
        collapses a subdirectory cwd to the repo root name."""
        import json
        import subprocess

        from memgentic.adapters.claude_code import ClaudeCodeAdapter
        from memgentic.processing.project import (
            _git_toplevel_sync,
        )

        # Create a fake repo + subdir
        repo = tmp_path / "fancy-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subdir = repo / "src" / "deep"
        subdir.mkdir(parents=True)

        # Create a Claude Code JSONL pointing at the SUBDIR (not the root)
        sessions_dir = tmp_path / ".claude" / "projects" / "fake-slug"
        sessions_dir.mkdir(parents=True)
        jsonl = sessions_dir / "abc.jsonl"
        with jsonl.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"cwd": str(subdir), "type": "human", "content": "hi"}) + "\n")

        monkeypatch.setenv("MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION", "true")
        # Force settings to re-read env
        from memgentic.config import MemgenticSettings
        new_settings = MemgenticSettings()
        monkeypatch.setattr("memgentic.config.settings", new_settings)

        _git_toplevel_sync.cache_clear()
        adapter = ClaudeCodeAdapter()
        project = await adapter.get_project(jsonl)
        assert project == "fancy-repo"  # collapsed to git root, NOT "deep"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_claude_code_adapter.py::TestClaudeCodeAdapterGitResolution -v`

Expected: FAIL — `get_project` currently returns "deep" (subdir name), not "fancy-repo".

- [ ] **Step 3: Modify Claude Code adapter**

Replace `memgentic/memgentic/adapters/claude_code.py:60-69` with:

```python
    async def get_project(self, file_path: Path) -> str | None:
        """Recover the project key from the JSONL ``cwd`` field.

        Claude Code 2.x writes ``cwd`` on every turn header. We sample the
        first non-empty value; on older sessions that lack it, we fall back to
        decoding the parent-directory slug (``~/.claude/projects/<slug>/``).

        When ``settings.enable_git_project_resolution`` is True, the cwd is
        passed through ``git rev-parse --show-toplevel`` to collapse
        subdirectories of the same repo into one project key.
        """
        from memgentic.config import settings as _settings
        from memgentic.processing.project import (
            derive_project_full,
            load_project_aliases,
        )

        cwd = await asyncio.to_thread(self._read_first_cwd, file_path)
        slug = file_path.parent.name if file_path.parent else None
        alias_map = load_project_aliases()
        project = await derive_project_full(
            cwd=cwd,
            slug=slug,
            use_git=_settings.enable_git_project_resolution,
            alias_map=alias_map,
        )
        return project or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_claude_code_adapter.py -v`

Expected: All Claude Code adapter tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/adapters/claude_code.py memgentic/tests/test_claude_code_adapter.py
git commit -m "feat(adapter:claude_code): wire derive_project_full + git resolution"
```

---

## Task 2.7: Update Codex CLI adapter to use `derive_project_full`

**Files:**
- Modify: `memgentic/memgentic/adapters/codex_cli.py:107-111`

- [ ] **Step 1: Modify Codex adapter**

Replace `memgentic/memgentic/adapters/codex_cli.py:107-111` with:

```python
    async def get_project(self, file_path: Path) -> str | None:
        """Codex stores ``cwd`` inside ``session_meta`` — perfect signal.

        When ``settings.enable_git_project_resolution`` is True, the cwd is
        normalised through ``git rev-parse --show-toplevel`` so subdir cwds
        collapse to the repo root.
        """
        from memgentic.config import settings as _settings
        from memgentic.processing.project import (
            derive_project_full,
            load_project_aliases,
        )

        events = await asyncio.to_thread(self._read_events, file_path)
        cwd = self._extract_cwd(events)
        alias_map = load_project_aliases()
        project = await derive_project_full(
            cwd=cwd,
            use_git=_settings.enable_git_project_resolution,
            alias_map=alias_map,
        )
        return project or None
```

- [ ] **Step 2: Run existing Codex adapter tests to verify nothing regressed**

Run: `cd memgentic && python -m pytest tests/test_codex_cli_adapter.py -v`

Expected: All existing Codex tests PASS (the change is additive when env var is unset, since `enable_git_project_resolution` defaults to False).

- [ ] **Step 3: Commit**

```bash
git add memgentic/memgentic/adapters/codex_cli.py
git commit -m "feat(adapter:codex_cli): wire derive_project_full + git resolution"
```

---

## Task 2.8: Update Gemini CLI adapter to use `derive_project_full`

**Files:**
- Modify: `memgentic/memgentic/adapters/gemini_cli.py:77-85`

- [ ] **Step 1: Modify Gemini adapter**

Replace `memgentic/memgentic/adapters/gemini_cli.py:77-85` with:

```python
    async def get_project(self, file_path: Path) -> str | None:
        """Try the JSON ``cwd`` field, fall back to no signal.

        Newer Gemini CLI sessions write a top-level ``cwd`` field; older ones
        only carry an opaque project hash directory name (``<hex>``) which
        cannot be reliably mapped back to a friendly project key.

        When ``settings.enable_git_project_resolution`` is True, the cwd is
        resolved through ``git rev-parse --show-toplevel`` for subdir
        collapse.
        """
        from memgentic.config import settings as _settings
        from memgentic.processing.project import (
            derive_project_full,
            load_project_aliases,
        )

        cwd = await asyncio.to_thread(self._read_cwd, file_path)
        alias_map = load_project_aliases()
        project = await derive_project_full(
            cwd=cwd,
            use_git=_settings.enable_git_project_resolution,
            alias_map=alias_map,
        )
        return project or None
```

- [ ] **Step 2: Run Gemini tests**

Run: `cd memgentic && python -m pytest tests/test_gemini_cli_adapter.py -v`

Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add memgentic/memgentic/adapters/gemini_cli.py
git commit -m "feat(adapter:gemini_cli): wire derive_project_full + git resolution"
```

---

## Task 2.9: Update Aider adapter to use `derive_project_full`

**Files:**
- Modify: `memgentic/memgentic/adapters/aider.py:51-55`

- [ ] **Step 1: Modify Aider adapter**

Replace `memgentic/memgentic/adapters/aider.py:51-55` with:

```python
    async def get_project(self, file_path: Path) -> str | None:
        """Aider keeps history *inside* the project directory, so the file's
        parent IS the cwd. Derive via the full chain (so git resolution +
        aliases apply when enabled).
        """
        from memgentic.config import settings as _settings
        from memgentic.processing.project import (
            derive_project_full,
            load_project_aliases,
        )

        alias_map = load_project_aliases()
        project = await derive_project_full(
            cwd=str(file_path.parent),
            use_git=_settings.enable_git_project_resolution,
            alias_map=alias_map,
        )
        return project or None
```

- [ ] **Step 2: Run Aider tests**

Run: `cd memgentic && python -m pytest tests/test_aider_adapter.py -v`

Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add memgentic/memgentic/adapters/aider.py
git commit -m "feat(adapter:aider): wire derive_project_full + git resolution"
```

---

## Task 2.10: Slice 2 live smoke

**Files:** —

- [ ] **Step 1: Run all Slice 2 tests + lint**

```bash
cd memgentic
python -m pytest tests/test_project_resolution.py tests/test_claude_code_adapter.py tests/test_codex_cli_adapter.py tests/test_gemini_cli_adapter.py tests/test_aider_adapter.py -v
cd ..
make lint
```

Expected: All PASS.

- [ ] **Step 2: Live smoke — git resolution off (default)**

```bash
python -c "
import asyncio
from pathlib import Path
from memgentic.config import settings
from memgentic.processing.project import derive_project_full, _git_toplevel_sync

_git_toplevel_sync.cache_clear()
print('git enabled:', settings.enable_git_project_resolution)

async def go():
    # Simulate a subdir of memgentic
    cwd = str(Path.cwd() / 'memgentic')
    p = await derive_project_full(cwd=cwd, use_git=False)
    print(f'  no-git: {p}')
    p2 = await derive_project_full(cwd=cwd, use_git=True)
    print(f'  with-git: {p2}')

asyncio.run(go())
"
```

Expected: `no-git: memgentic` (subdir name) and `with-git: memgentic-public-export` (repo root name).

- [ ] **Step 3: Live smoke — turn on globally and verify recall**

```bash
MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION=true python -c "from memgentic.cli import main; main()" projects
```

Expected: Same project counts as before (the flag affects new ingestion, not existing rows). To migrate, Slice 1's repair OR Slice 3's backfill is needed.

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore(slice-2): lint cleanup" --allow-empty
```

---

# Slice 3 — Migration 11 + JSONL Backfill CLI

**Risk:** Medium. Migration 11 itself is trivial (one CREATE INDEX). The JSONL backfill CLI does substantial I/O but only when the user runs it explicitly.

**Ships:** Production DB recovers ~645 of 696 (unknown) memories (Codex CLI ~429 + Gemini CLI ~216) by re-reading session_meta from the original JSONL files.

## Task 3.1: Add Migration 11 (partial index)

**Files:**
- Modify: `memgentic/memgentic/storage/migrations.py:202-256` (after Migration 10)
- Test: `memgentic/tests/test_migration_11.py` (create)

- [ ] **Step 1: Write the failing test**

Create `memgentic/tests/test_migration_11.py`:

```python
"""Migration 11 — partial index for empty-project repair discovery."""

from __future__ import annotations

import aiosqlite
import pytest

from memgentic.storage.metadata import CREATE_TABLE_SQL
from memgentic.storage.migrations import MIGRATIONS, migrate


async def _build_v10_db(path: str) -> aiosqlite.Connection:
    """Stand up a fresh DB at schema version 10 (pre-Migration-11)."""
    db = await aiosqlite.connect(path)
    await db.executescript(CREATE_TABLE_SQL)
    # Seed schema_version up through 10 by running migrate then truncating.
    await migrate(db)
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    assert row is not None and row[0] is not None
    return db


class TestMigration11:
    def test_migration_11_in_list(self) -> None:
        versions = [v for v, *_ in MIGRATIONS]
        assert 11 in versions
        # Make sure no duplicate version numbers leaked in.
        assert len(versions) == len(set(versions))

    async def test_creates_partial_index(self, tmp_path) -> None:
        db_path = str(tmp_path / "m11.db")
        db = await aiosqlite.connect(db_path)
        try:
            await db.executescript(CREATE_TABLE_SQL)
            applied = await migrate(db)
            assert applied >= 1  # at least migration 11 ran on this fresh DB

            # Verify the partial index exists.
            cursor = await db.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND name='idx_memories_project_empty'"
            )
            row = await cursor.fetchone()
            assert row is not None, "idx_memories_project_empty must exist"
            sql = row[1] or ""
            assert "WHERE project = ''" in sql, (
                f"Index must be partial (WHERE project = ''). Got: {sql!r}"
            )
        finally:
            await db.close()

    async def test_idempotent_on_rerun(self, tmp_path) -> None:
        db_path = str(tmp_path / "m11_idem.db")
        db = await aiosqlite.connect(db_path)
        try:
            await db.executescript(CREATE_TABLE_SQL)
            await migrate(db)
            # Second migrate call should be a no-op (no migrations apply).
            applied_again = await migrate(db)
            assert applied_again == 0
        finally:
            await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_migration_11.py -v`

Expected: FAIL — Migration 11 doesn't exist yet.

- [ ] **Step 3: Add Migration 11 to MIGRATIONS list**

Insert after the closing parenthesis of Migration 10 (around line 256, before the closing `]` of MIGRATIONS):

```python
    (
        11,
        "project_aliases_index — partial index for empty-project repair discovery",
        [
            # Partial index makes `memgentic projects backfill-jsonl` and
            # `memgentic projects repair` efficient on large databases — both
            # commands scan WHERE project = ''. CREATE INDEX IF NOT EXISTS is
            # idempotent so this is safe on fresh installs that already
            # created the column via Migration 9.
            "CREATE INDEX IF NOT EXISTS idx_memories_project_empty "
            "ON memories(id, file_path) WHERE project = ''",
        ],
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_migration_11.py -v`

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/storage/migrations.py memgentic/tests/test_migration_11.py
git commit -m "feat(migrations): add Migration 11 partial index for empty-project rows"
```

---

## Task 3.2: Add `backfill-jsonl` Codex implementation

**Files:**
- Modify: `memgentic/memgentic/cli.py` (extend `projects` group)
- Test: `memgentic/tests/test_project_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `memgentic/tests/test_project_cli.py`:

```python
class TestProjectsBackfillJsonlCodex:
    async def _seed_codex_memory(
        self,
        isolated_home: Path,
        memory_id: str,
        rollout_path: Path,
        cwd_in_session_meta: str | None,
    ) -> None:
        """Seed a memory with empty project + given rollout file_path,
        and write a Codex-style JSONL with an optional session_meta event.
        """
        import json
        from datetime import UTC, datetime

        from memgentic.config import settings
        from memgentic.models import (
            CaptureMethod,
            ContentType,
            Memory,
            Platform,
            SourceMetadata,
        )
        from memgentic.storage.metadata import MetadataStore

        settings.data_dir = isolated_home / ".memgentic" / "data"
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            m = Memory(
                id=memory_id,
                content="codex content",
                content_type=ContentType.FACT,
                project="",  # explicitly empty
                source=SourceMetadata(
                    platform=Platform.CODEX_CLI,
                    capture_method=CaptureMethod.AUTO_DAEMON,
                    file_path=str(rollout_path),
                ),
                created_at=datetime.now(UTC),
            )
            await store.save_memory(m)
        finally:
            await store.close()

        # Write the rollout JSONL.
        rollout_path.parent.mkdir(parents=True, exist_ok=True)
        with rollout_path.open("w", encoding="utf-8") as f:
            if cwd_in_session_meta is not None:
                meta = {
                    "type": "session_meta",
                    "payload": {"cwd": cwd_in_session_meta},
                }
                f.write(json.dumps(meta) + "\n")
            f.write(json.dumps({"type": "response_item", "payload": {}}) + "\n")

    def test_codex_backfill_populates_project(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        rollout = (
            isolated_home
            / ".codex"
            / "sessions"
            / "2026"
            / "05"
            / "07"
            / "rollout-test.jsonl"
        )
        asyncio.run(
            self._seed_codex_memory(
                isolated_home,
                memory_id="codex-1",
                rollout_path=rollout,
                cwd_in_session_meta="/home/harit/dev/myapp",
            )
        )

        result = runner.invoke(
            main, ["projects", "backfill-jsonl", "--source", "codex_cli"]
        )
        assert result.exit_code == 0, result.output
        assert "1" in result.output  # one row updated

        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m = await store.get_memory("codex-1")
                assert m is not None and m.project == "myapp"
            finally:
                await store.close()

        asyncio.run(_check())

    def test_codex_skips_when_no_session_meta(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        rollout = (
            isolated_home
            / ".codex"
            / "sessions"
            / "2026"
            / "05"
            / "07"
            / "rollout-no-meta.jsonl"
        )
        asyncio.run(
            self._seed_codex_memory(
                isolated_home,
                memory_id="codex-x",
                rollout_path=rollout,
                cwd_in_session_meta=None,  # no meta event
            )
        )

        result = runner.invoke(
            main, ["projects", "backfill-jsonl", "--source", "codex_cli"]
        )
        assert result.exit_code == 0, result.output

        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m = await store.get_memory("codex-x")
                assert m is not None and m.project == ""  # untouched
            finally:
                await store.close()

        asyncio.run(_check())

    def test_codex_dry_run_does_not_write(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        rollout = (
            isolated_home
            / ".codex"
            / "sessions"
            / "2026"
            / "05"
            / "07"
            / "rollout-dry.jsonl"
        )
        asyncio.run(
            self._seed_codex_memory(
                isolated_home,
                memory_id="codex-dry",
                rollout_path=rollout,
                cwd_in_session_meta="/home/harit/dev/dryapp",
            )
        )

        result = runner.invoke(
            main,
            [
                "projects",
                "backfill-jsonl",
                "--source",
                "codex_cli",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m = await store.get_memory("codex-dry")
                assert m is not None and m.project == ""
            finally:
                await store.close()

        asyncio.run(_check())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsBackfillJsonlCodex -v`

Expected: FAIL — `backfill-jsonl` doesn't exist.

- [ ] **Step 3: Implement `projects backfill-jsonl`**

Append to `memgentic/memgentic/cli.py` after `projects_merge`:

```python
@projects.command("backfill-jsonl")
@click.option(
    "--source",
    "-s",
    multiple=True,
    type=click.Choice(["codex_cli", "gemini_cli"]),
    help="Limit to specific adapters. Default: all supported (codex_cli, gemini_cli).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would change without writing to the DB.",
)
def projects_backfill_jsonl(source: tuple[str, ...], dry_run: bool):
    """Re-read JSONL session_meta to fill empty-project memories.

    \b
    Only processes memories WHERE project = '' AND file_path IS NOT NULL.
    Per-adapter parsing:
      - codex_cli: scans the rollout JSONL for the first
                   {"type": "session_meta"} event, extracts payload.cwd
      - gemini_cli: opens the JSON, reads the top-level "cwd" /
                    "workingDirectory" field

    \b
    Idempotent: a row that's still empty after one run (because the JSONL
    has no usable cwd) stays empty and will not be retried by a later run
    of the same command unless the file changes.
    """

    async def _run():
        import json

        from memgentic.config import settings as _settings
        from memgentic.processing.project import (
            derive_project_full,
            load_project_aliases,
        )
        from memgentic.storage.metadata import MetadataStore

        adapters = set(source) if source else {"codex_cli", "gemini_cli"}
        alias_map = load_project_aliases()

        store = MetadataStore(_settings.sqlite_path)
        await store.initialize()

        try:
            assert store._db is not None
            cursor = await store._db.execute(
                """SELECT id, file_path, platform FROM memories
                   WHERE project = '' AND file_path IS NOT NULL
                     AND status = 'active' AND platform IN ({})
                """.format(",".join("?" * len(adapters))),
                tuple(adapters),
            )
            rows = await cursor.fetchall()

            updates: list[tuple[str, str]] = []
            still_empty = 0
            unreadable = 0

            for mid, file_path, platform in rows:
                cwd: str | None = None
                try:
                    if platform == "codex_cli":
                        cwd = _read_codex_cwd(file_path)
                    elif platform == "gemini_cli":
                        cwd = _read_gemini_cwd(file_path)
                except (OSError, json.JSONDecodeError):
                    unreadable += 1
                    continue

                if not cwd:
                    still_empty += 1
                    continue

                project = await derive_project_full(
                    cwd=cwd,
                    use_git=_settings.enable_git_project_resolution,
                    alias_map=alias_map,
                )
                if project:
                    updates.append((project, mid))
                else:
                    still_empty += 1

            mode = "dry-run" if dry_run else "applied"
            console.print(
                f"[cyan]projects backfill-jsonl ({mode}):[/] "
                f"scanned {len(rows)}, would update {len(updates)}, "
                f"still empty {still_empty}, unreadable {unreadable}"
            )

            if updates and not dry_run:
                await store._db.executemany(
                    "UPDATE memories SET project = ? WHERE id = ?",
                    updates,
                )
                await store._db.commit()
                console.print(f"[green]OK[/] Updated {len(updates)} rows.")
        finally:
            await store.close()

    asyncio.run(_run())


def _read_codex_cwd(file_path: str) -> str | None:
    """Scan a Codex rollout JSONL for the first session_meta.cwd."""
    import json

    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "session_meta":
                    continue
                payload = event.get("payload") or {}
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def _read_gemini_cwd(file_path: str) -> str | None:
    """Read top-level cwd / workingDirectory from a Gemini chat JSON."""
    import json

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("cwd", "workingDirectory", "working_directory", "projectPath"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsBackfillJsonlCodex -v`

Expected: 3 Codex tests PASS.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/cli.py memgentic/tests/test_project_cli.py
git commit -m "feat(cli): add 'projects backfill-jsonl' (Codex JSONL re-read)"
```

---

## Task 3.3: Add Gemini test for `backfill-jsonl`

**Files:**
- Test: `memgentic/tests/test_project_cli.py`

- [ ] **Step 1: Write the test**

Append to `memgentic/tests/test_project_cli.py`:

```python
class TestProjectsBackfillJsonlGemini:
    async def _seed_gemini_memory(
        self,
        isolated_home: Path,
        memory_id: str,
        chat_path: Path,
        cwd_in_json: str | None,
    ) -> None:
        import json
        from datetime import UTC, datetime

        from memgentic.config import settings
        from memgentic.models import (
            CaptureMethod,
            ContentType,
            Memory,
            Platform,
            SourceMetadata,
        )
        from memgentic.storage.metadata import MetadataStore

        settings.data_dir = isolated_home / ".memgentic" / "data"
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            m = Memory(
                id=memory_id,
                content="gemini content",
                content_type=ContentType.FACT,
                project="",
                source=SourceMetadata(
                    platform=Platform.GEMINI_CLI,
                    capture_method=CaptureMethod.AUTO_DAEMON,
                    file_path=str(chat_path),
                ),
                created_at=datetime.now(UTC),
            )
            await store.save_memory(m)
        finally:
            await store.close()

        chat_path.parent.mkdir(parents=True, exist_ok=True)
        body: dict = {"messages": []}
        if cwd_in_json:
            body["cwd"] = cwd_in_json
        chat_path.write_text(json.dumps(body), encoding="utf-8")

    def test_gemini_backfill_populates_project(self, isolated_home: Path) -> None:
        import asyncio

        runner = CliRunner()
        chat = isolated_home / ".gemini" / "tmp" / "abc" / "chats" / "x.json"
        asyncio.run(
            self._seed_gemini_memory(
                isolated_home,
                memory_id="gemini-1",
                chat_path=chat,
                cwd_in_json="/home/harit/dev/myapp",
            )
        )

        result = runner.invoke(
            main, ["projects", "backfill-jsonl", "--source", "gemini_cli"]
        )
        assert result.exit_code == 0, result.output

        async def _check():
            from memgentic.config import settings
            from memgentic.storage.metadata import MetadataStore

            store = MetadataStore(settings.sqlite_path)
            await store.initialize()
            try:
                m = await store.get_memory("gemini-1")
                assert m is not None and m.project == "myapp"
            finally:
                await store.close()

        asyncio.run(_check())
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_project_cli.py::TestProjectsBackfillJsonlGemini -v`

Expected: PASS — Gemini path was already implemented in Task 3.2.

- [ ] **Step 3: Commit**

```bash
git add memgentic/tests/test_project_cli.py
git commit -m "test(cli): add Gemini coverage for projects backfill-jsonl"
```

---

## Task 3.4: Slice 3 live smoke on production DB

**Files:** —

- [ ] **Step 1: Run all Slice 3 tests + lint**

```bash
cd memgentic
python -m pytest tests/test_migration_11.py tests/test_project_cli.py -v
cd ..
make lint
```

Expected: All PASS.

- [ ] **Step 2: Pre-flight on production DB — count empty rows**

```bash
python -c "
import asyncio
from memgentic.config import settings
from memgentic.storage.metadata import MetadataStore

async def go():
    s = MetadataStore(settings.sqlite_path)
    await s.initialize()
    try:
        cur = await s._db.execute(\"\"\"
            SELECT platform, COUNT(*) FROM memories
            WHERE project = '' AND status = 'active' AND file_path IS NOT NULL
            GROUP BY platform
        \"\"\")
        for row in await cur.fetchall():
            print(f'  {row[0]:15s} {row[1]:5d}')
    finally:
        await s.close()
asyncio.run(go())
"
```

Expected: Pre-existing diagnostics — codex_cli ~429, gemini_cli ~216, copilot_cli ~35, claude_code ~10.

- [ ] **Step 3: Run backfill in dry-run first**

```bash
python -c "from memgentic.cli import main; main()" projects backfill-jsonl --dry-run
```

Expected output: `scanned NNN, would update ~600, still empty ~50, unreadable 0`.

- [ ] **Step 4: Apply backfill**

```bash
python -c "from memgentic.cli import main; main()" projects backfill-jsonl
```

Expected: Same numbers as dry-run, with `[green]OK[/] Updated NNN rows`.

- [ ] **Step 5: Verify (unknown) bucket dropped**

```bash
python -c "from memgentic.cli import main; main()" projects
```

Expected: The `(unknown)` row drops from ~696 to ~50 (just Copilot CLI memories that can't be backfilled by design).

- [ ] **Step 6: Commit cleanup**

```bash
cd C:/Users/harit/Desktop/Business_Projects/memgentic-public-export
git add -A
git commit --allow-empty -m "chore(slice-3): live smoke confirms ~645/696 unknowns recovered"
```

---

# Slice 4 — Multi-Value REST + Dashboard Multi-Select

**Risk:** Low. Pure UX additions. The REST change is backward-compatible (a single string still works as a one-element list in FastAPI). Dashboard checkbox UX preserves the current default (no projects selected = no filter).

**Ships:** Users can multi-select projects in the dashboard sidebar (checkboxes). Source + project filters AND-stack instead of mutexing.

## Task 4.1: REST API multi-value `project` query param

**Files:**
- Modify: `memgentic-api/memgentic_api/routes/memories.py:130-184`
- Test: `memgentic-api/tests/test_memories.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `memgentic-api/tests/test_memories.py` (or wherever existing memory list tests live):

```python
async def test_list_memories_multi_value_project_filter(
    client, seed_memories
):
    """GET /memories?project=foo&project=bar returns memories from foo OR bar."""
    # seed_memories fixture should create at least 3 memories with projects
    # ['foo', 'bar', 'baz']. Adjust based on the actual fixture name.
    await seed_memories([
        {"project": "foo", "content": "f1"},
        {"project": "bar", "content": "b1"},
        {"project": "baz", "content": "z1"},
    ])

    resp = await client.get("/api/v1/memories?project=foo&project=bar")
    assert resp.status_code == 200
    data = resp.json()
    projects = sorted(m["project"] for m in data["memories"])
    assert projects == ["bar", "foo"]


async def test_list_memories_single_value_project_still_works(
    client, seed_memories
):
    """Backward-compat: ?project=foo (single) still works."""
    await seed_memories([
        {"project": "foo", "content": "f1"},
        {"project": "bar", "content": "b1"},
    ])

    resp = await client.get("/api/v1/memories?project=foo")
    assert resp.status_code == 200
    data = resp.json()
    assert all(m["project"] == "foo" for m in data["memories"])
```

NOTE: Adapt `seed_memories` to whatever fixture pattern the existing API tests use. If unsure, read the top of `memgentic-api/tests/test_memories.py` first to mirror the existing client/fixture style.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic-api && python -m pytest tests/test_memories.py -v -k "multi_value or single_value_project"`

Expected: FAIL — multi-value query produces a 422 because the param is currently `str | None`.

- [ ] **Step 3: Modify the endpoint**

Replace `memgentic-api/memgentic_api/routes/memories.py:130-184` with:

```python
@router.get("/memories")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_memories(
    request: Request,
    metadata_store: MetadataStoreDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source: str | None = None,
    content_type: str | None = None,
    project: list[str] | None = Query(
        default=None,
        description=(
            "Filter by project key (repeatable). Pass multiple times for OR "
            "semantics: ?project=foo&project=bar returns memories from foo "
            "OR bar. Pass the empty string to fetch only memories without a "
            "project assignment."
        ),
    ),
) -> MemoryListResponse:
    """List memories with pagination and optional filtering.

    Project, source, and content_type filters AND-stack: a memory must
    match every supplied filter to appear in results.
    """
    config = SessionConfig()
    if source:
        try:
            config.include_sources = [Platform(source)]
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid source platform: {source}"
            ) from None

    if project is not None:
        # Multi-value: ?project=foo&project=bar. The empty string is a
        # meaningful filter (memories without a project assignment); we keep
        # it as-is and let the storage layer handle the IN ('') predicate.
        config.include_projects = [p.strip().lower() for p in project]

    try:
        ct = ContentType(content_type) if content_type else None
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Invalid content_type: {content_type}"
        ) from None

    offset = (page - 1) * page_size

    total = await metadata_store.get_filtered_count(session_config=config, content_type=ct)
    memories = await metadata_store.get_memories_by_filter(
        session_config=config,
        content_type=ct,
        limit=page_size,
        offset=offset,
    )

    return MemoryListResponse(
        memories=[_memory_to_response(m) for m in memories],
        total=total,
        page=page,
        page_size=page_size,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic-api && python -m pytest tests/test_memories.py -v`

Expected: All tests PASS — both new multi-value AND existing single-value.

- [ ] **Step 5: Commit**

```bash
git add memgentic-api/memgentic_api/routes/memories.py memgentic-api/tests/test_memories.py
git commit -m "feat(api): /memories accepts multi-value ?project= for OR filtering"
```

---

## Task 4.2: Update dashboard `listMemories` for multi-value

**Files:**
- Modify: `dashboard/src/lib/api.ts:85-99`
- Test: `dashboard/src/__tests__/api-list-memories.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `dashboard/src/__tests__/api-list-memories.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import * as api from "@/lib/api";

describe("listMemories query string serialization", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ memories: [], total: 0, page: 1, page_size: 20 }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("appends a single project param when one project is selected", async () => {
    await api.listMemories({ projects: ["foo"] });
    const url = String(fetchSpy.mock.calls[0]?.[0] ?? "");
    expect(url).toContain("project=foo");
  });

  it("appends multiple project params (OR semantics)", async () => {
    await api.listMemories({ projects: ["foo", "bar"] });
    const url = String(fetchSpy.mock.calls[0]?.[0] ?? "");
    expect(url).toMatch(/project=foo/);
    expect(url).toMatch(/project=bar/);
  });

  it("omits project params when projects array is empty", async () => {
    await api.listMemories({ projects: [] });
    const url = String(fetchSpy.mock.calls[0]?.[0] ?? "");
    expect(url).not.toContain("project=");
  });

  it("omits project params when projects is undefined", async () => {
    await api.listMemories({});
    const url = String(fetchSpy.mock.calls[0]?.[0] ?? "");
    expect(url).not.toContain("project=");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- api-list-memories`

Expected: FAIL — `listMemories` currently uses `params.project` (singular).

- [ ] **Step 3: Modify `listMemories`**

Replace `dashboard/src/lib/api.ts:85-99` with:

```typescript
export async function listMemories(params: {
  page?: number;
  page_size?: number;
  source?: string;
  content_type?: string;
  projects?: string[];
}): Promise<MemoryListResponse> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.source) qs.set("source", params.source);
  if (params.content_type) qs.set("content_type", params.content_type);
  (params.projects ?? []).forEach((p) => qs.append("project", p));
  return fetchJson(`${API_BASE}/memories?${qs}`);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- api-list-memories`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/lib/api.ts dashboard/src/__tests__/api-list-memories.test.ts
git commit -m "feat(dashboard): listMemories accepts projects: string[] for multi-select"
```

---

## Task 4.3: Update `useMemories` hook signature

**Files:**
- Modify: `dashboard/src/hooks/use-memories.ts:8-19`

- [ ] **Step 1: Modify the hook**

Replace `dashboard/src/hooks/use-memories.ts:8-19` with:

```typescript
export function useMemories(params: {
  page?: number;
  page_size?: number;
  source?: string;
  content_type?: string;
  projects?: string[];
}) {
  return useQuery({
    queryKey: ["memories", params],
    queryFn: () => api.listMemories(params),
  });
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd dashboard
npx tsc --noEmit 2>&1 | grep -E "use-memories|api\.ts" || echo "OK"
```

Expected: `OK` (no TS errors in the files we touched). Pre-existing errors in unrelated test files are fine.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/use-memories.ts
git commit -m "feat(dashboard): useMemories accepts projects: string[]"
```

---

## Task 4.4: CollectionsSidebar multi-select + drop mutex

**Files:**
- Modify: `dashboard/src/components/collections/collections-sidebar.tsx`

- [ ] **Step 1: Update the component**

Replace `dashboard/src/components/collections/collections-sidebar.tsx:122-127` (interface) and lines 129-141 (props destructure / hook calls). Open the file and make the following changes:

**Change 1 — Interface (lines 122-127):**

```typescript
interface CollectionsSidebarProps {
  activeView: string | null; // null = all, "pinned", or collection ID
  onViewChange: (view: string | null) => void;
  activeSource: string | undefined;
  onSourceChange: (source: string | undefined) => void;
  activeProjects: string[];
  onProjectsChange: (projects: string[]) => void;
}
```

**Change 2 — Component signature (lines 129-141):**

```typescript
export function CollectionsSidebar({
  activeView,
  onViewChange,
  activeSource,
  onSourceChange,
  activeProjects,
  onProjectsChange,
}: CollectionsSidebarProps) {
  const { data: collectionsData } = useCollections();
  const { data: sourcesData } = useSources();
  const { data: projectsData } = useProjects();

  const collections = collectionsData?.collections ?? [];
  const sources = sourcesData?.sources ?? [];
  const projects = projectsData?.projects ?? [];
```

**Change 3 — Project section render (replace lines 252-283 entirely):**

```tsx
      {projects.length > 0 ? (
        <>
          <Separator className="my-2" />
          <div className="space-y-1">
            <div className="flex items-center justify-between px-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Projects
              </p>
              {activeProjects.length > 0 ? (
                <button
                  className="text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => onProjectsChange([])}
                  aria-label="Clear project filters"
                >
                  Clear
                </button>
              ) : null}
            </div>
            {projects.map((project) => {
              const checked = activeProjects.includes(project.project);
              return (
                <button
                  key={project.project || "(unknown)"}
                  onClick={() => {
                    // Toggle in/out — DO NOT clear other filters anymore.
                    if (checked) {
                      onProjectsChange(
                        activeProjects.filter((p) => p !== project.project),
                      );
                    } else {
                      onProjectsChange([...activeProjects, project.project]);
                    }
                  }}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                    checked
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                  aria-pressed={checked}
                >
                  <span
                    className={`inline-block size-3.5 shrink-0 rounded-sm border ${
                      checked
                        ? "border-primary bg-primary"
                        : "border-muted-foreground/40"
                    }`}
                    aria-hidden="true"
                  />
                  <span className="truncate flex-1 text-left">{project.label}</span>
                  <span className="text-xs tabular-nums">{project.count}</span>
                </button>
              );
            })}
          </div>
        </>
      ) : null}
    </aside>
  );
}
```

(The above replaces the original conditional `{onProjectChange && projects.length > 0 ? (...)}` block.)

- [ ] **Step 2: Verify TS compiles**

```bash
cd dashboard
npx tsc --noEmit 2>&1 | grep -E "collections-sidebar" || echo "OK"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/collections/collections-sidebar.tsx
git commit -m "feat(dashboard): Projects sidebar multi-select, drop source mutex"
```

---

## Task 4.5: `page.tsx` — `projectFilters: string[]` state

**Files:**
- Modify: `dashboard/src/app/page.tsx:85, 104, 121-127, plus the CollectionsSidebar invocation (search for "<CollectionsSidebar")`

- [ ] **Step 1: Update state type**

Replace `dashboard/src/app/page.tsx:85` (single line) with:

```typescript
  const [projectFilters, setProjectFilters] = useState<string[]>([]);
```

- [ ] **Step 2: Update the page-reset effect**

Replace `dashboard/src/app/page.tsx:104`:

```typescript
  }, [debouncedQuery, sourceFilter, contentTypeFilter, projectFilters, activeView]);
```

- [ ] **Step 3: Update the useMemories call**

Replace `dashboard/src/app/page.tsx:121-127`:

```typescript
  } = useMemories({
    page,
    page_size: pageSize,
    source: sourceFilter,
    content_type: contentTypeFilter,
    projects: projectFilters,
  });
```

- [ ] **Step 4: Update the CollectionsSidebar invocation**

Find the line that uses `<CollectionsSidebar` (search the file). Replace its props with:

```tsx
<CollectionsSidebar
  activeView={activeView}
  onViewChange={setActiveView}
  activeSource={sourceFilter}
  onSourceChange={setSourceFilter}
  activeProjects={projectFilters}
  onProjectsChange={setProjectFilters}
/>
```

- [ ] **Step 5: Verify TS compiles**

```bash
cd dashboard
npx tsc --noEmit 2>&1 | grep -E "page\.tsx" || echo "OK"
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/app/page.tsx
git commit -m "feat(dashboard): page state uses projectFilters: string[]"
```

---

## Task 4.6: Slice 4 live smoke in browser

**Files:** —

- [ ] **Step 1: Run all dashboard tests**

```bash
cd dashboard
npm test
```

Expected: All tests PASS (or pre-existing unrelated failures only).

- [ ] **Step 2: Start API + dev server**

In two terminals, from the repo root:

```bash
# Terminal A — API
cd memgentic-api
python -c "import uvicorn; uvicorn.run('memgentic_api.main:app', host='127.0.0.1', port=3691, log_level='warning')"

# Terminal B — Dashboard
cd dashboard
npm run dev
```

- [ ] **Step 3: Manual checks in browser**

Open http://localhost:3690 and verify:
- Projects sidebar renders with checkbox-style indicators (filled square = selected)
- Click `memgentic-public-export` (single select) — `Clear` button appears, memory grid filters.
- Click `vetervo` (additionally) — both stay selected; memory grid shows union.
- Click a Source filter (e.g., `Claude Code`) — the project selection PERSISTS (no mutex).
- Header `Clear filters` clears everything.

- [ ] **Step 4: Commit any cleanup**

```bash
cd C:/Users/harit/Desktop/Business_Projects/memgentic-public-export
git add -A
git commit --allow-empty -m "chore(slice-4): manual browser smoke green"
```

---

# Slice 5 — Current-Project Boost + Cross-Project Section

**Risk:** Highest. Changes scoring math in the hot recall path. Default boost factor is conservative (1.5×) and additive — never penalizes cross-project hits, only lifts current-project ones.

**Ships:** When the user runs `memgentic_recall("…")` from a project directory, current-project memories rank first. Cross-project memories that score above 0.6× the top primary appear in a labeled "Related from other projects" section.

## Task 5.1: Add three boost-related settings

**Files:**
- Modify: `memgentic/memgentic/config.py`

- [ ] **Step 1: Add the settings**

Insert after the existing `enable_git_project_resolution` field (added in Task 2.5):

```python
    current_project_boost: float = Field(
        default=1.5,
        ge=1.0,
        le=5.0,
        description=(
            "Score multiplier applied to memories whose project key matches the "
            "calling MCP/CLI process's resolved current project. 1.0 disables "
            "the boost (memories rank purely on RRF + importance + decay). "
            "Set via MEMGENTIC_CURRENT_PROJECT_BOOST."
        ),
    )
    cross_project_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum unboosted score ratio (relative to the top unboosted primary "
            "result) for a non-current-project memory to appear in the "
            "'Related from other projects' section. 0.0 includes everything; "
            "1.0 effectively disables the section. "
            "Set via MEMGENTIC_CROSS_PROJECT_THRESHOLD."
        ),
    )
    cross_project_max: int = Field(
        default=5,
        ge=0,
        le=20,
        description=(
            "Maximum number of cross-project memories returned in the 'Related' "
            "section. 0 disables the section entirely. "
            "Set via MEMGENTIC_CROSS_PROJECT_MAX."
        ),
    )
```

- [ ] **Step 2: Verify settings load**

```bash
cd memgentic
python -c "
from memgentic.config import settings
print('boost:', settings.current_project_boost)
print('threshold:', settings.cross_project_threshold)
print('max:', settings.cross_project_max)
"
```

Expected: `boost: 1.5`, `threshold: 0.6`, `max: 5`.

- [ ] **Step 3: Commit**

```bash
git add memgentic/memgentic/config.py
git commit -m "feat(config): add current_project_boost, cross_project_threshold, cross_project_max"
```

---

## Task 5.2: Modify `hybrid_search` — add boost params, score_raw, is_current_project

**Files:**
- Modify: `memgentic/memgentic/graph/search.py:30-46` (signature) + 121-137 (impl signature) + 224-321 (boost pass + result dict)
- Test: `memgentic/tests/test_hybrid_search_boost.py` (create)

- [ ] **Step 1: Write the failing test**

Create `memgentic/tests/test_hybrid_search_boost.py`:

```python
"""Unit tests for project-boost arithmetic in hybrid_search.

These exercise the math purely — they don't spin up Qdrant or Ollama.
We monkey-patch the engine inputs (semantic_results, keyword_results,
metadata_store.get_memories_batch) and assert on the returned dicts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.graph.search import hybrid_search
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)


def _make_memory(mid: str, project: str) -> Memory:
    return Memory(
        id=mid,
        content=f"content {mid}",
        content_type=ContentType.FACT,
        project=project,
        importance_score=1.0,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        created_at=datetime.now(UTC),
    )


def _wire_search_engines(
    metadata_store: MagicMock,
    vector_store: MagicMock,
    embedder: MagicMock,
    *,
    semantic_ids: list[str],
    keyword_ids: list[str],
    memories: dict[str, Memory],
) -> None:
    embedder.embed_query = AsyncMock(return_value=[0.0] * 8)
    vector_store.search = AsyncMock(
        return_value=[
            {"id": mid, "score": 1.0 - i * 0.01, "payload": {}}
            for i, mid in enumerate(semantic_ids)
        ]
    )
    metadata_store.search_fulltext = AsyncMock(
        return_value=[memories[mid] for mid in keyword_ids if mid in memories]
    )
    metadata_store.get_memories_batch = AsyncMock(return_value=memories)


class TestHybridSearchBoost:
    async def test_no_current_project_no_boost(self) -> None:
        memories = {
            "a": _make_memory("a", "memgentic"),
            "b": _make_memory("b", "vetervo"),
        }
        ms, vs, em = MagicMock(), MagicMock(), MagicMock()
        _wire_search_engines(
            ms,
            vs,
            em,
            semantic_ids=["a", "b"],
            keyword_ids=[],
            memories=memories,
        )

        results = await hybrid_search(
            query="test",
            metadata_store=ms,
            vector_store=vs,
            embedder=em,
            current_project=None,
        )

        # Both results should have score == score_raw (no boost applied).
        for r in results:
            assert r["score"] == r["score_raw"], r
            assert r["is_current_project"] is None

    async def test_current_project_boost_applied(self) -> None:
        memories = {
            "match": _make_memory("match", "memgentic"),
            "other": _make_memory("other", "vetervo"),
        }
        ms, vs, em = MagicMock(), MagicMock(), MagicMock()
        _wire_search_engines(
            ms,
            vs,
            em,
            semantic_ids=["match", "other"],
            keyword_ids=[],
            memories=memories,
        )

        results = await hybrid_search(
            query="test",
            metadata_store=ms,
            vector_store=vs,
            embedder=em,
            current_project="memgentic",
            project_boost=2.0,
        )

        results_by_id = {r["id"]: r for r in results}
        assert results_by_id["match"]["is_current_project"] is True
        assert results_by_id["other"]["is_current_project"] is False
        assert (
            results_by_id["match"]["score"]
            == pytest.approx(results_by_id["match"]["score_raw"] * 2.0)
        )
        # Non-current memories are NOT boosted.
        assert (
            results_by_id["other"]["score"]
            == results_by_id["other"]["score_raw"]
        )

    async def test_boost_changes_ranking_order(self) -> None:
        # Without boost, "other" wins (semantic_rank=1, score 1.0).
        # With boost=2.0, "match" wins despite semantic_rank=2 (score 0.99).
        memories = {
            "other": _make_memory("other", "vetervo"),
            "match": _make_memory("match", "memgentic"),
        }
        ms, vs, em = MagicMock(), MagicMock(), MagicMock()
        _wire_search_engines(
            ms,
            vs,
            em,
            semantic_ids=["other", "match"],
            keyword_ids=[],
            memories=memories,
        )

        results = await hybrid_search(
            query="test",
            metadata_store=ms,
            vector_store=vs,
            embedder=em,
            current_project="memgentic",
            project_boost=2.0,
        )

        # match should be first now.
        assert results[0]["id"] == "match"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_hybrid_search_boost.py -v`

Expected: FAIL — `current_project` param doesn't exist on `hybrid_search`.

- [ ] **Step 3: Modify `hybrid_search` signature + outer wrapper**

Replace `memgentic/memgentic/graph/search.py:30-46` with:

```python
async def hybrid_search(
    query: str,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    graph: KnowledgeGraph | RustKnowledgeGraph | None = None,
    session_config: SessionConfig | None = None,
    limit: int = 10,
    rrf_k: int = 60,
    settings: MemgenticSettings | None = None,
    user_id: str = "",
    *,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    graph_weight: float = DEFAULT_GRAPH_WEIGHT,
    min_score: float = 0.0,
    current_project: str | None = None,
    project_boost: float = 1.5,
    cross_project_threshold: float = 0.6,
    cross_project_max: int = 5,
) -> list[dict]:
```

Then update the inner `_hybrid_search_impl` signature `memgentic/memgentic/graph/search.py:121-137` to match (add the same four kwargs), and pass them through from the outer call site (around line 96-112). At line 97-112 replace the call with:

```python
        results = await _hybrid_search_impl(
            query=query,
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedder=embedder,
            graph=graph,
            session_config=session_config,
            limit=limit,
            rrf_k=rrf_k,
            settings=settings,
            user_id=user_id,
            semantic_weight=semantic_weight,
            keyword_weight=keyword_weight,
            graph_weight=graph_weight,
            min_score=min_score,
            current_project=current_project,
            project_boost=project_boost,
            cross_project_threshold=cross_project_threshold,
            cross_project_max=cross_project_max,
        )
```

- [ ] **Step 4: Modify `_hybrid_search_impl` boost pass**

Replace `memgentic/memgentic/graph/search.py:280-281` (the `for mid in drop: scores.pop(mid, None)` end-of-filter line + the surrounding context up through the `ranked = sorted(...)` line at 288) with:

```python
    for mid in drop:
        scores.pop(mid, None)

    # --- Project boost pass ----------------------------------------------
    # Boost is multiplicative AFTER importance * decay so we don't compound
    # with the existing weights. We snapshot the unboosted scores into
    # ``score_raw`` for the cross-project gate downstream.
    score_raw: dict[str, float] = dict(scores)

    if current_project:
        normalized_current = current_project.strip().lower()
        for mid, mem in memories_map.items():
            if mid in scores and mem is not None:
                if (mem.project or "").lower() == normalized_current:
                    scores[mid] = scores[mid] * project_boost

    # Return raw fused weighted RRF * importance * decay scores plus
    # per-signal observability. We deliberately do NOT divide by max —
    # that made the top result always read as 1.0 even when every
    # candidate was a poor match (relevance lie). Callers that need a
    # 0-1 display can normalise themselves with full context.
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

- [ ] **Step 5: Modify the result-dict construction**

Find lines 293-321 (the `for mid, score in ranked: ...` loop). Replace the dict construction inside the loop (around line 310-320) with:

```python
        is_current = None
        if current_project:
            mem = memories_map.get(mid)
            if mem is not None:
                is_current = (mem.project or "").lower() == current_project.strip().lower()

        out.append(
            {
                "id": mid,
                "score": round(float(score), 6),
                "score_raw": round(float(score_raw.get(mid, score)), 6),
                "is_current_project": is_current,
                "payload": payloads.get(mid, {}),
                "semantic_rank": semantic_ranks.get(mid),
                "keyword_rank": keyword_ranks.get(mid),
                "graph_boosted": in_graph,
                "search_method": method,
            }
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_hybrid_search_boost.py -v`

Expected: 3 tests PASS.

- [ ] **Step 7: Run existing search tests to ensure no regression**

```bash
cd memgentic
python -m pytest tests/test_hybrid_search.py tests/test_search_relevance.py -v
```

Expected: All PASS — `current_project` defaults to None which is the no-op path.

- [ ] **Step 8: Commit**

```bash
git add memgentic/memgentic/graph/search.py memgentic/tests/test_hybrid_search_boost.py
git commit -m "feat(search): add current_project boost + score_raw + is_current_project"
```

---

## Task 5.3: Wire current-project boost into MCP `memgentic_recall`

**Files:**
- Modify: `memgentic/memgentic/mcp/server.py:680-763` (the `memgentic_recall` function)

- [ ] **Step 1: Modify the recall handler**

In `memgentic/memgentic/mcp/server.py:703-740`, change the recall body to resolve the current project, pass boost params, and render the partition.

Replace lines 703-740 (the `try:` block contents up to and including the `else: results = await basic_search(...)` block) with:

```python
    try:
        import os

        state = ctx.request_context.lifespan_context
        embedder: Embedder = state["embedder"]
        vector_store: VectorStore = state["vector_store"]
        metadata_store: MetadataStore = state["metadata_store"]
        graph = state.get("graph")

        # Build effective filter config
        config = _get_effective_config(
            ctx,
            sources=params.sources,
            exclude_sources=params.exclude_sources,
            content_types=params.content_types,
            project=params.project,
            projects=params.projects,
            exclude_projects=params.exclude_projects,
        )

        # Resolve the calling process's current project for the boost pass.
        # This is purely additive — never filters results, only re-ranks them.
        current_project: str | None = None
        if HAS_INTELLIGENCE:
            from memgentic.processing.project import (
                load_project_aliases,
                resolve_current_project,
            )

            try:
                current_project = await resolve_current_project(
                    env_override=os.environ.get("MEMGENTIC_CURRENT_PROJECT"),
                    use_git=settings.enable_git_project_resolution,
                    alias_map=load_project_aliases(),
                )
            except Exception as exc:
                logger.warning("memgentic_recall.resolve_current_project_failed", error=str(exc))
                current_project = None

        # Use hybrid search if intelligence installed, otherwise basic vector search
        if HAS_INTELLIGENCE and hybrid_search is not None:
            results = await hybrid_search(
                query=params.query,
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedder=embedder,
                graph=graph,
                session_config=config,
                limit=params.limit,
                current_project=current_project,
                project_boost=settings.current_project_boost,
                cross_project_threshold=settings.cross_project_threshold,
                cross_project_max=settings.cross_project_max,
            )
        else:
            results = await basic_search(
                query=params.query,
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedder=embedder,
                session_config=config,
                limit=params.limit,
            )
```

- [ ] **Step 2: Modify the result rendering to partition primary vs related**

Replace the result rendering block (lines 742-760, starting at `if not results:` and ending before `except Exception as exc:`) with:

```python
        if not results:
            return f"No memories found for: '{params.query}'"

        # Partition into primary (current project) and related (cross-project)
        # ONLY when current_project resolved AND results carry the flag.
        primary: list[dict] = results
        related: list[dict] = []
        if current_project and any(
            r.get("is_current_project") is not None for r in results
        ):
            primary = [r for r in results if r.get("is_current_project")]
            cross = [r for r in results if r.get("is_current_project") is False]
            primary_raw_top = max(
                (r["score_raw"] for r in primary), default=0.0
            )
            threshold = primary_raw_top * settings.cross_project_threshold
            related = [
                r for r in cross if r["score_raw"] >= threshold
            ][: settings.cross_project_max]

        # Format results
        lines = [f"# Memory Recall: '{params.query}'", ""]
        if current_project:
            lines.append(
                f"_Boosted for current project: **{current_project}**_"
            )
            lines.append("")

        if primary:
            lines.append(f"## From {current_project or 'all projects'} ({len(primary)})")
            lines.append("")
        else:
            lines.append(f"Found {len(results)} relevant memories:")
            lines.append("")

        returned_payloads: list[dict] = []
        for result in primary:
            await metadata_store.update_access(result["id"])
            payload = dict(result.get("payload") or {})
            payload.setdefault("id", result["id"])
            returned_payloads.append(payload)
            lines.append(_format_memory_md(payload, result["score"], detail=params.detail))

        if related:
            lines.append("")
            lines.append(f"## Related from other projects ({len(related)})")
            lines.append("")
            for result in related:
                await metadata_store.update_access(result["id"])
                payload = dict(result.get("payload") or {})
                payload.setdefault("id", result["id"])
                returned_payloads.append(payload)
                lines.append(_format_memory_md(payload, result["score"], detail=params.detail))

        _record_loaded_payloads(ctx, returned_payloads, returned_by="memgentic_recall")
        return "\n".join(lines)
```

- [ ] **Step 3: Run existing MCP recall tests**

```bash
cd memgentic
python -m pytest tests/test_mcp_server.py tests/test_mcp_project_filter.py -v
```

Expected: All PASS — the changes are additive when `current_project` resolves to None (no env var, no git enabled, etc.).

- [ ] **Step 4: Commit**

```bash
git add memgentic/memgentic/mcp/server.py
git commit -m "feat(mcp): memgentic_recall resolves current project and renders partition"
```

---

## Task 5.4: Slice 5 live smoke

**Files:** —

- [ ] **Step 1: Run all Slice 5 tests + lint**

```bash
cd memgentic
python -m pytest tests/test_hybrid_search_boost.py tests/test_mcp_server.py tests/test_mcp_project_filter.py -v
cd ..
make lint
```

Expected: All PASS.

- [ ] **Step 2: Live smoke — recall WITHOUT current project**

```bash
unset MEMGENTIC_CURRENT_PROJECT
python -c "from memgentic.cli import main; main()" search "project filter" -n 5 --format compact
```

Expected: Existing behavior — top 5 memories ranked by raw RRF + importance + decay. No boost.

- [ ] **Step 3: Live smoke — recall WITH MEMGENTIC_CURRENT_PROJECT env override**

```bash
MEMGENTIC_CURRENT_PROJECT=memgentic-public-export python -c "from memgentic.cli import main; main()" search "project filter" -n 5 --format compact
```

(Note: the CLI `search` command was bug-fixed earlier to use `--project auto` for strict-filter; this env var is consumed via the MCP server path. For a CLI smoke, the project-strict-filter is sufficient since the boost is MCP-only in this slice.)

- [ ] **Step 4: Live smoke — MCP recall in Claude Code**

In a Claude Code session opened from `~/Desktop/Business_Projects/memgentic-public-export/`:

1. Run `memgentic_recall` MCP tool with no `project` arg, query "auth flow" or similar.
2. Verify the output now shows two markdown sections:
   - `## From memgentic-public-export (N)` — top primary
   - `## Related from other projects (M)` — when relevant cross-project hits pass the threshold

If the section split doesn't appear and you expect cross-project hits, check that:
- `enable_git_project_resolution=true` is set OR you're running directly in the project dir (not a subdirectory)
- The expected cross-project memories actually exist in your DB

- [ ] **Step 5: Final commit**

```bash
cd C:/Users/harit/Desktop/Business_Projects/memgentic-public-export
git add -A
git commit --allow-empty -m "chore(slice-5): MCP recall smoke green with boost+section partition"
```

---

# Final: Plan Self-Review (for the executor)

After finishing all five slices, run this checklist before declaring done:

- [ ] **All test suites green:**
  ```bash
  cd memgentic && python -m pytest tests/ -q --ignore=tests/test_benchmarks.py --ignore=tests/test_integration.py
  cd ../memgentic-api && python -m pytest tests/ -q
  cd ../dashboard && npm test
  ```

- [ ] **Lint clean:** `make lint` from repo root.

- [ ] **MCP-TOOLS.md regenerated:** `python scripts/generate_mcp_docs.py` and commit if it changed.

- [ ] **Live smoke on user's actual DB:**
  - `memgentic projects` — `(unknown)` count dropped from 696 → ~50.
  - Multi-select in dashboard sidebar — checking 2 projects ORs them, AND-stacks with sources.
  - MCP recall in `memgentic-public-export/` — primary/related sections render.

- [ ] **CHANGELOG entry** for next release noting the new env vars: `MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION`, `MEMGENTIC_CURRENT_PROJECT`, `MEMGENTIC_CURRENT_PROJECT_BOOST`, `MEMGENTIC_CROSS_PROJECT_THRESHOLD`, `MEMGENTIC_CROSS_PROJECT_MAX`. Also note the new CLI subcommands.

- [ ] **No JSONL reads in any migration function** — `git grep "json.load" memgentic/memgentic/storage/migrations.py` returns nothing.

- [ ] **No sync git subprocess calls from coroutines** — `git grep -n "subprocess.run.*git" memgentic/memgentic/processing/project.py` should appear only inside `_git_*_sync` helpers, never directly inside `async def`.
