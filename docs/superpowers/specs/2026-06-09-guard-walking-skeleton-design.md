# Memgentic Guard — Walking Skeleton Design

**Date:** 2026-06-09
**Status:** Approved design (post 6-agent adversarial review, verdict `go_with_must_fix`)
**Scope:** The smallest deterministic slice that runs on the founder's own repos and **trustworthily measures value-density** before any further Guard work. NOT full v0.1.

This design supersedes the informal skeleton sketch. It folds in the 4 high + 3 medium must-fix items from the design review (`woo962pdb`), each verified against the real repo / N1 data.

---

## 1. Goal & non-goals

**Goal:** prove the deterministic Guard engine catches a *real* project-specific violation on a rule-rich repo with **~zero false positives**, using a measurement that cannot fool itself.

**Non-goals (explicitly deferred):** `guard init` / freeform rule extraction (`sources.py`), LLM `guard suggest`, pre-commit installer, GitHub Action, MCP self-check, `confirm`/`ignore`/history, `decisions.lock` generation. Those are phase 2+.

## 2. Locked decisions

1. **Hero check = `import_direction`** (the #1 deterministic signal on the founder's repos per N1). `banned_dependency` also ships; `banned_import` ships only as the AST unit-test vehicle. **`httpx` is never a hero** — it is a core dependency of Memgentic (`pyproject.toml:41`) and cannot fire; it is a unit-test fixture only.
2. **Dogfood scope = founder repos + ≥1 external prose-thin repo** (mem0 / claude-mem). A green on the founder's repos is "valuable to me," NOT "wedge validated" — N1 already showed it does not generalize. The external repo keeps the claim honest.
3. **`sources.py` is OUT of this slice.** The gate's rules come from a hand-authored `decisions.yaml`. Any miss is then unambiguously an engine bug, never a parser artifact.

## 3. Architecture (must match existing conventions)

There is **no `dream/` package** to mirror — `dream` is `processing/dream.py` + an **inline** `@main.group("dream")` in `cli.py:1094`. Follow that exactly:

- Register `@main.group("guard")` + command functions **inline in `memgentic/memgentic/cli.py`**; heavy logic lives in a `guard/` subpackage **lazily imported inside the function bodies**. Do NOT create a competing Click group in `guard/cli.py`.
- Data models go in the **central `memgentic/models.py`** (next to the `Dream*` models, as `pydantic BaseModel` + `ConfigDict(str_strip_whitespace=True)`), NOT a feature-local `models.py`.

```
memgentic/memgentic/guard/
  __init__.py
  diff.py          # git → DiffFile[]  (Windows/Greek-hardened, defensive)
  blobs.py         # reconstruct full new-side file content for AST
  engine.py        # rules × diff → Violation[]
  formatters.py    # Rich + --format json
  checks/
    __init__.py
    import_direction.py   # HERO — scope_package × forbidden_target_prefixes
    dependencies.py       # banned_dependency — manifest parse
    imports.py            # flat banned_import — AST unit-test vehicle, NOT hero
# models added to memgentic/models.py (central)
# guard group added inline to memgentic/cli.py
```

## 4. Data models (in central `models.py`)

```python
class GuardRuleType(StrEnum):
    IMPORT_DIRECTION = "import_direction"
    BANNED_DEPENDENCY = "banned_dependency"
    BANNED_IMPORT = "banned_import"

class GuardRule(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str
    type: GuardRuleType
    # scope: WHERE the rule applies (glob over repo-relative paths). Required for
    # import_direction — "memgentic_api is illegal only in files under memgentic/**".
    scope: str = "**"
    # for import_direction: forbidden module prefixes; for banned_import: modules;
    # for banned_dependency: package names.
    targets: list[str]
    message: str
    source: str        # e.g. "decisions.yaml" or "CLAUDE.md:NN"
    severity: Literal["error", "warn"] = "error"

class Violation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    rule_id: str
    message: str
    file: str
    line: int | None = None
    snippet: str | None = None
```

## 5. `decisions.yaml` (hand-authored ground truth for the gate)

```yaml
rules:
  - id: core-import-direction
    type: import_direction
    scope: "memgentic/**"
    targets: ["memgentic_api", "memgentic_native", "dashboard"]
    message: "Core must never import from api/native/dashboard (dependency direction)."
    source: "CLAUDE.md"
  - id: no-langchain-in-core
    type: banned_dependency
    scope: "memgentic/pyproject.toml"
    targets: ["langchain-core", "langchain-anthropic", "langgraph"]
    message: "LLM stack belongs in the [intelligence] extra, not core dependencies."
    source: "CLAUDE.md"
```
(`hyphen→underscore` mapping applied when matching dep names to import modules; non-module targets like `dashboard` are matched as import prefixes only.)

## 6. The AST approach (must-fix #3 — do NOT parse hunk fragments)

Added hunks are partial, dedented, unbalanced fragments; `ast.parse` raises `SyntaxError` on most real diffs (an indented `    import x`, or the tail of a multi-line `from … import (`). Both naive recoveries corrupt the measurement (swallow→catches nothing→false-low; regex fallback→FPs leak→fails zero-FP).

**Correct flow:**
1. `diff.py` computes, per changed file, the **added-line set** strictly from `@@` headers.
2. `blobs.py` reconstructs the **full new-side file** (`git show :path` for staged, `git cat-file -p <sha>:path` for `--base`).
3. `ast.parse` the *complete, valid* file; walk `Import`/`ImportFrom`; resolve each to its **top-level module** (so aliased / submodule / `from x import y` all match).
4. Keep only nodes whose `lineno…end_lineno` intersects the added-line set.
5. If the reconstructed file is itself syntactically invalid → degrade to **non-crash, non-false-positive** (skip the file, log debug).

## 7. Windows / Greek hardening (must-fix #5) & defensive diff (must-fix #7)

- git as list-argv with `encoding="utf-8", errors="replace"` (founder on win32; repos contain em-dashes + Greek → `cp1252` `UnicodeDecodeError` silently shrinks the corpus).
- `-c core.quotepath=false`; resolve root via `git rev-parse --show-toplevel`; strip trailing `\r` from added lines; use **three-dot** `main...HEAD` (merge-base) for `--base`, not two-dot.
- Parse path from `diff --git` / `+++ b/`; handle `/dev/null` (new/deleted); detect & skip `Binary files … differ`; route by extension (`.py`→imports/import_direction; `pyproject.toml`/`package.json`/`requirements.txt`→deps; else ignore).
- Test-file detection by **path segment / regex** (`tests/`, `test_*.py`, `*_test.py`), NOT substring `"test"` (which false-excludes `latest.py`, `contest.py`).

## 8. CLI surface

```
memgentic guard                 # diff main...HEAD, check, print, exit 0/1/2
memgentic guard --staged
memgentic guard --base <ref>
memgentic guard --format json
memgentic guard rules           # show the loaded decisions.yaml rules
```
Exit codes: `0` clean · `1` error-severity violations · `2` config/runtime error (not a git repo, missing git, unreadable decisions.yaml). `--quiet-passing` deferred to phase 2 (skeleton always prints a one-line summary).

## 9. TDD plan (fixtures MUST live under `tests/`)

`testpaths=["tests"]` → loose top-level fixture dirs are **not collected**. Put fixtures under `tests/fixtures/guard/` and tests as `tests/test_guard*.py`.

Fixtures: `import_direction/` (added `import memgentic_api` under `memgentic/` → 1; same import under `tests/` or `dashboard/` → 0) · `banned_dep/` (added `langchain-core` to core deps → 1) · `false_positive_guard/` (banned module in comment / docstring / string-literal / test file / `try-except ImportError` / **indented-function-body import** / **multi-line from-import middle line added** / **syntactically-invalid reconstructed file** → all 0) · `diff_edge_cases/` (rename `-M` / new `/dev/null` / deleted / binary / non-py → skip/route, never throw) · `greek_emdash/` (Greek + em-dash content survives) · `clean/` (0).

Write the `false_positive_guard` indented-import + multiline cases FIRST — they are exactly what breaks a naive AST design while the original fixtures pass green.

## 10. Validation protocol — the redesigned gate (must-fix #1)

**DROP** any numeric "value-density over organic history" threshold — N1 explicitly refuted it, and a disciplined repo's merged history is clean by construction (verified: zero added `import memgentic_api` in core history). Replaying clean history catches ~0 → would read as a **false NO-GO**.

Two independent measurements:
- **(A) False-positive correctness** — run on the full clean merged history of Memgentic + 2 allvolution repos **+ ≥1 external prose-thin repo** (mem0 / claude-mem). **PASS = ~0 false positives** (FP-rate `<20%` is the only gated number, per stress-test §4-R4). Zero catches on clean history is **EXPECTED, not a kill signal.**
- **(B) Recall** — hand-authored seeded-violation branches, **one per rule type** (e.g. seed `import memgentic_api` under `memgentic/`; seed `langchain-core` into core `[project]` deps). **PASS = engine fires on each.**

Author-agnostic — drop the unmeasurable "identify AI-generated commits" step. Historical catches (if any) are reported **directional-only**.

**Kill condition:** (A) leaks false positives that AST-scoping can't close, OR (B) the engine cannot reliably fire on seeded violations. Then stop and rethink before phase 2. A clean (A) + passing (B) = proceed to phase 2 (full offline v0.1).

## 11. Open follow-ups (not blocking the skeleton)

- Number of seeded branches: ≥1 per rule type (3 total) for a real recall denominator.
- `sources.py` revival decision happens in phase 2, not here.
