# Guard Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, LLM-free `memgentic guard` slice that checks a git diff against hand-authored rules (import-direction, banned-dependency, banned-import) with ~zero false positives, so we can trustworthily measure value-density on real repos.

**Architecture:** A `guard/` subpackage holds pure logic (diff parsing, full-blob AST reconstruction, three checks, engine, formatters). Checks take an injectable `blob_getter` so they unit-test with in-memory source — no git needed. The CLI registers an inline `@main.group("guard")` in `cli.py` mirroring the existing `dream` group. Rules load from a hand-authored `decisions.yaml`; `sources.py` (prose extraction) is deferred.

**Tech Stack:** Python 3.12, stdlib `ast`/`subprocess`/`fnmatch`, Click, Rich, PyYAML — all existing core deps. pytest (flat `tests/`, `asyncio_mode=auto`). Built on branch `feat/guard-skeleton`.

**Spec:** `docs/superpowers/specs/2026-06-09-guard-walking-skeleton-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `memgentic/memgentic/models.py` (modify) | Add `GuardRuleType`, `GuardRule`, `Violation` next to `Dream*` models |
| `memgentic/memgentic/guard/__init__.py` (create) | Package marker + public exports |
| `memgentic/memgentic/guard/diff.py` (create) | `DiffFile` dataclass; `get_diff()` (Windows-hardened git); `parse_diff()` |
| `memgentic/memgentic/guard/blobs.py` (create) | `make_blob_getter()` — full new-side file via `git show <ref>:<path>` |
| `memgentic/memgentic/guard/checks/import_direction.py` (create) | HERO check: scope glob × forbidden module prefixes (AST) |
| `memgentic/memgentic/guard/checks/dependencies.py` (create) | `banned_dependency` — manifest added-line parse |
| `memgentic/memgentic/guard/checks/imports.py` (create) | flat `banned_import` (AST) — unit-test vehicle |
| `memgentic/memgentic/guard/engine.py` (create) | `load_rules()`, dispatch by type, `run_checks()`, `run()` |
| `memgentic/memgentic/guard/formatters.py` (create) | `format_text()` (Rich), `format_json()` |
| `memgentic/memgentic/cli.py` (modify) | Inline `@main.group("guard")` + `guard` / `guard rules` commands |
| `tests/test_guard_*.py` (create) | One test module per component |
| `tests/fixtures/guard/decisions.yaml` (create) | Ground-truth rules for tests + dogfood |

**Shared interfaces (keep names consistent across tasks):**
- `DiffFile(path: str, added_lines: dict[int, str], is_binary: bool, is_deleted: bool)`
- `BlobGetter = Callable[[str], str | None]` — repo-relative path → full new-side source, or `None`
- Every check module exposes `check(rule: GuardRule, diff_files: list[DiffFile], blob_getter: BlobGetter) -> list[Violation]`

---

## Task 1: Data models

**Files:**
- Modify: `memgentic/memgentic/models.py` (add near the `Dream*` models)
- Test: `tests/test_guard_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_models.py
from memgentic.models import GuardRule, GuardRuleType, Violation


def test_guard_rule_defaults_and_strip():
    r = GuardRule(
        id="core-import-direction",
        type="import_direction",
        targets=["memgentic_api"],
        message="  core must not import api  ",
    )
    assert r.type is GuardRuleType.IMPORT_DIRECTION
    assert r.scope == "**"
    assert r.severity == "error"
    assert r.message == "core must not import api"  # str_strip_whitespace


def test_violation_optional_fields():
    v = Violation(rule_id="r1", message="bad", file="a.py")
    assert v.line is None and v.snippet is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'GuardRule'`

- [ ] **Step 3: Add the models**

In `memgentic/memgentic/models.py`, confirm `from enum import StrEnum` and `from pydantic import BaseModel, ConfigDict` are imported (add if missing), then append:

```python
class GuardRuleType(StrEnum):
    IMPORT_DIRECTION = "import_direction"
    BANNED_DEPENDENCY = "banned_dependency"
    BANNED_IMPORT = "banned_import"


class GuardRule(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str
    type: GuardRuleType
    scope: str = "**"
    targets: list[str]
    message: str
    source: str = "decisions.yaml"
    severity: Literal["error", "warn"] = "error"


class Violation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    rule_id: str
    message: str
    file: str
    line: int | None = None
    snippet: str | None = None
```

Ensure `from typing import Literal` is present at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/models.py tests/test_guard_models.py
git commit -m "feat(guard): add GuardRule/Violation models"
```

---

## Task 2: Diff parser (`diff.py`)

**Files:**
- Create: `memgentic/memgentic/guard/__init__.py` (empty)
- Create: `memgentic/memgentic/guard/diff.py`
- Test: `tests/test_guard_diff.py`

- [ ] **Step 1: Write the failing test** (parsing is pure — no git needed)

```python
# tests/test_guard_diff.py
from memgentic.guard.diff import parse_diff

SAMPLE = """diff --git a/memgentic/x.py b/memgentic/x.py
index 111..222 100644
--- a/memgentic/x.py
+++ b/memgentic/x.py
@@ -1,2 +1,3 @@
 import os
+import memgentic_api
 import sys
diff --git a/data.bin b/data.bin
index 333..444 100644
Binary files a/data.bin and b/data.bin differ
diff --git a/old.py b/new.py
similarity index 100%
rename from old.py
rename to new.py
"""


def test_parse_added_line_numbers_and_routing():
    files = {f.path: f for f in parse_diff(SAMPLE)}
    x = files["memgentic/x.py"]
    # 'import memgentic_api' is the 2nd new-side line
    assert x.added_lines == {2: "import memgentic_api"}
    assert files["data.bin"].is_binary is True
    assert files["new.py"].path == "new.py"  # rename → new path


def test_crlf_stripped():
    diff = "diff --git a/p.py b/p.py\n--- a/p.py\n+++ b/p.py\n@@ -0,0 +1 @@\n+import x\r\n"
    f = parse_diff(diff)[0]
    assert f.added_lines == {1: "import x"}  # trailing \r removed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_diff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memgentic.guard'`

- [ ] **Step 3: Implement `diff.py`**

```python
# memgentic/memgentic/guard/diff.py
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass
class DiffFile:
    path: str
    added_lines: dict[int, str] = field(default_factory=dict)
    is_binary: bool = False
    is_deleted: bool = False


def _git(repo: Path, args: list[str]) -> str:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    return out.stdout


def get_diff(repo: Path, *, base: str | None = None, staged: bool = False) -> str:
    if staged:
        return _git(repo, ["diff", "--staged", "--no-color", "-U0", "--find-renames"])
    ref = base or "main"
    # three-dot = merge-base, excludes unrelated main changes
    return _git(repo, ["diff", f"{ref}...HEAD", "--no-color", "-U0", "--find-renames"])


def parse_diff(text: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    cur: DiffFile | None = None
    new_lineno = 0
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("diff --git "):
            cur = None
            continue
        if line.startswith("Binary files "):
            if cur is None:
                cur = DiffFile(path="")
                files.append(cur)
            cur.is_binary = True
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = "" if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            cur = DiffFile(path=path)
            files.append(cur)
            continue
        if line.startswith("--- ") and line[4:].strip() == "/dev/null":
            continue  # new file; +++ sets the path next
        m = _HUNK.match(line)
        if m:
            new_lineno = int(m.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            cur.added_lines[new_lineno] = line[1:]
            new_lineno += 1
        elif line.startswith(" "):
            new_lineno += 1
        # '-' lines do not advance the new-side counter
    return [f for f in files if f.path]
```

Note: rename detection — with `-U0` and `--find-renames`, a pure rename emits no `+++`/hunk, so it produces no `DiffFile` (correct: nothing to check). The test's rename block has no hunk, so `new.py` only appears if content changed; adjust the test if a pure rename is used. (Engine task covers real renames via integration.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_diff.py -v`
Expected: PASS. If the rename assertion fails because a pure rename emits no `+++`, change that assertion to `assert "new.py" not in files`.

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/guard/__init__.py memgentic/memgentic/guard/diff.py tests/test_guard_diff.py
git commit -m "feat(guard): windows-hardened git diff + defensive parser"
```

---

## Task 3: Import-direction check (HERO)

**Files:**
- Create: `memgentic/memgentic/guard/checks/__init__.py` (empty)
- Create: `memgentic/memgentic/guard/checks/import_direction.py`
- Test: `tests/test_guard_import_direction.py`

- [ ] **Step 1: Write the failing test** (in-memory blob_getter — no git)

```python
# tests/test_guard_import_direction.py
from memgentic.guard.checks.import_direction import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(
    id="core-import-direction", type="import_direction", scope="memgentic/**",
    targets=["memgentic_api", "dashboard"], message="core must not import api/dashboard",
)


def _getter(blobs):
    return lambda path: blobs.get(path)


def test_fires_on_forbidden_import_in_scope():
    df = DiffFile(path="memgentic/x.py", added_lines={2: "import memgentic_api"})
    blobs = {"memgentic/x.py": "import os\nimport memgentic_api\n"}
    out = check(RULE, [df], _getter(blobs))
    assert len(out) == 1
    assert out[0].file == "memgentic/x.py" and out[0].line == 2


def test_silent_when_out_of_scope():
    df = DiffFile(path="tests/x.py", added_lines={1: "import memgentic_api"})
    blobs = {"tests/x.py": "import memgentic_api\n"}
    assert check(RULE, [df], _getter(blobs)) == []


def test_silent_when_import_not_in_added_lines():
    # forbidden import exists but on an unchanged line
    df = DiffFile(path="memgentic/x.py", added_lines={3: "x = 1"})
    blobs = {"memgentic/x.py": "import memgentic_api\n\nx = 1\n"}
    assert check(RULE, [df], _getter(blobs)) == []


def test_submodule_and_from_import_match():
    df = DiffFile(path="memgentic/y.py", added_lines={1: "from memgentic_api.routes import r"})
    blobs = {"memgentic/y.py": "from memgentic_api.routes import r\n"}
    assert len(check(RULE, [df], _getter(blobs))) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_import_direction.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the check**

```python
# memgentic/memgentic/guard/checks/import_direction.py
from __future__ import annotations

import ast
from collections.abc import Callable

from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], "str | None"]


def _in_scope(path: str, scope: str) -> bool:
    if scope in ("**", "*", ""):
        return True
    prefix = scope.split("**")[0].rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _top_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module.split(".")[0]]
    return []


def _forbidden(mod: str, targets: list[str]) -> bool:
    return any(mod == t or mod == t.replace("-", "_") for t in targets)


def check(rule: GuardRule, diff_files: list[DiffFile], blob_getter: BlobGetter) -> list[Violation]:
    out: list[Violation] = []
    for df in diff_files:
        if df.is_binary or not df.path.endswith(".py") or not _in_scope(df.path, rule.scope):
            continue
        blob = blob_getter(df.path)
        if not blob:
            continue
        try:
            tree = ast.parse(blob)
        except SyntaxError:
            continue  # degrade: never crash, never false-positive
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if node.lineno not in df.added_lines:
                continue
            if any(_forbidden(m, rule.targets) for m in _top_modules(node)):
                out.append(Violation(
                    rule_id=rule.id, message=rule.message, file=df.path,
                    line=node.lineno, snippet=df.added_lines.get(node.lineno),
                ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_import_direction.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/guard/checks/__init__.py memgentic/memgentic/guard/checks/import_direction.py tests/test_guard_import_direction.py
git commit -m "feat(guard): import-direction check (hero, AST + scope)"
```

---

## Task 4: Banned-import check + false-positive guard fixtures

**Files:**
- Create: `memgentic/memgentic/guard/checks/imports.py`
- Test: `tests/test_guard_imports.py`

This is the AST unit-test vehicle. The FP fixtures here are the most important tests in the slice — they are exactly what breaks a naive AST design.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_imports.py
from memgentic.guard.checks.imports import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(id="ban-httpx", type="banned_import", targets=["httpx"], message="no httpx")


def _g(blobs):
    return lambda p: blobs.get(p)


def test_fires_on_real_import():
    df = DiffFile(path="a.py", added_lines={1: "import httpx"})
    assert len(check(RULE, [df], _g({"a.py": "import httpx\n"}))) == 1


def test_indented_function_body_import_fires():
    src = "def f():\n    import httpx\n    return 1\n"
    df = DiffFile(path="a.py", added_lines={2: "    import httpx"})
    assert len(check(RULE, [df], _g({"a.py": src}))) == 1


def test_no_fp_in_comment_string_or_test_file():
    src = "# import httpx\nx = 'import httpx'\n"
    df = DiffFile(path="a.py", added_lines={1: "# import httpx", 2: "x = 'import httpx'"})
    assert check(RULE, [df], _g({"a.py": src})) == []
    # test files excluded by path
    dft = DiffFile(path="tests/test_a.py", added_lines={1: "import httpx"})
    assert check(RULE, [dft], _g({"tests/test_a.py": "import httpx\n"})) == []


def test_no_fp_in_optional_import_guard():
    src = "try:\n    import httpx\nexcept ImportError:\n    httpx = None\n"
    df = DiffFile(path="a.py", added_lines={2: "    import httpx"})
    assert check(RULE, [df], _g({"a.py": src})) == []


def test_syntactically_invalid_blob_degrades():
    df = DiffFile(path="a.py", added_lines={1: "import httpx"})
    assert check(RULE, [df], _g({"a.py": "def (:\n"})) == []  # no crash, no FP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_imports.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# memgentic/memgentic/guard/checks/imports.py
from __future__ import annotations

import ast
import re
from collections.abc import Callable

from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], "str | None"]
_TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE.search(path))


def _under_import_error_guard(node: ast.AST, parents: dict) -> bool:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")
            for h in cur.handlers
        ):
            return True
        cur = parents.get(cur)
    return False


def check(rule: GuardRule, diff_files: list[DiffFile], blob_getter: BlobGetter) -> list[Violation]:
    out: list[Violation] = []
    for df in diff_files:
        if df.is_binary or not df.path.endswith(".py") or _is_test_file(df.path):
            continue
        blob = blob_getter(df.path)
        if not blob:
            continue
        try:
            tree = ast.parse(blob)
        except SyntaxError:
            continue
        parents: dict = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if node.lineno not in df.added_lines or _under_import_error_guard(node, parents):
                continue
            mods = ([a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import)
                    else [node.module.split(".")[0]] if node.module else [])
            if any(m in rule.targets for m in mods):
                out.append(Violation(rule_id=rule.id, message=rule.message, file=df.path,
                                     line=node.lineno, snippet=df.added_lines.get(node.lineno)))
    return out
```

Because we AST-parse the *full reconstructed blob* (not the diff fragment), comments and string literals never appear as `Import` nodes — the comment/string FP cases pass for free. The `import httpx` on line 1 of the comment test is `# import httpx`, which is a comment in the blob, so no node exists at line 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_imports.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/guard/checks/imports.py tests/test_guard_imports.py
git commit -m "feat(guard): banned-import check with AST false-positive guards"
```

---

## Task 5: Banned-dependency check

**Files:**
- Create: `memgentic/memgentic/guard/checks/dependencies.py`
- Test: `tests/test_guard_dependencies.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_dependencies.py
from memgentic.guard.checks.dependencies import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(id="no-langchain-core", type="banned_dependency",
                 scope="memgentic/pyproject.toml", targets=["langchain-core"],
                 message="LLM stack belongs in [intelligence]")


def test_fires_on_added_dependency_line():
    df = DiffFile(path="memgentic/pyproject.toml",
                  added_lines={42: '    "langchain-core>=1.2",'})
    assert len(check(RULE, [df], lambda p: None)) == 1


def test_no_fp_on_unrelated_added_line():
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={42: '    "rich>=14.0",'})
    assert check(RULE, [df], lambda p: None) == []


def test_only_in_scoped_manifest():
    df = DiffFile(path="other/pyproject.toml", added_lines={1: '    "langchain-core>=1",'})
    assert check(RULE, [df], lambda p: None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_dependencies.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement** (operates on added lines only — no blob needed)

```python
# memgentic/memgentic/guard/checks/dependencies.py
from __future__ import annotations

import re
from collections.abc import Callable

from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], "str | None"]
_MANIFESTS = ("pyproject.toml", "package.json", "requirements.txt")


def _in_scope(path: str, scope: str) -> bool:
    if scope in ("**", "*", ""):
        return path.endswith(_MANIFESTS)
    return path == scope


def check(rule: GuardRule, diff_files: list[DiffFile], blob_getter: BlobGetter) -> list[Violation]:
    out: list[Violation] = []
    patterns = [re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])") for t in rule.targets]
    for df in diff_files:
        if df.is_binary or not df.path.endswith(_MANIFESTS) or not _in_scope(df.path, rule.scope):
            continue
        for lineno, text in df.added_lines.items():
            if any(p.search(text) for p in patterns):
                out.append(Violation(rule_id=rule.id, message=rule.message, file=df.path,
                                     line=lineno, snippet=text.strip()))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_dependencies.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/guard/checks/dependencies.py tests/test_guard_dependencies.py
git commit -m "feat(guard): banned-dependency check (manifest scope)"
```

---

## Task 6: Engine — load rules, dispatch, git-backed blob getter

**Files:**
- Create: `memgentic/memgentic/guard/blobs.py`
- Create: `memgentic/memgentic/guard/engine.py`
- Create: `tests/fixtures/guard/decisions.yaml`
- Test: `tests/test_guard_engine.py` (integration — builds a throwaway git repo)

- [ ] **Step 1: Write the ground-truth fixture**

```yaml
# tests/fixtures/guard/decisions.yaml
rules:
  - id: core-import-direction
    type: import_direction
    scope: "memgentic/**"
    targets: ["memgentic_api", "memgentic_native", "dashboard"]
    message: "Core must never import from api/native/dashboard."
    source: "CLAUDE.md"
  - id: no-langchain-in-core
    type: banned_dependency
    scope: "memgentic/pyproject.toml"
    targets: ["langchain-core", "langgraph"]
    message: "LLM stack belongs in the [intelligence] extra."
    source: "CLAUDE.md"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_guard_engine.py
import subprocess
from pathlib import Path

import pytest

from memgentic.guard.engine import load_rules, run


def _run(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def seeded_repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "memgentic").mkdir(parents=True)
    _run_init = subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t")
    _run(repo, "config", "user.name", "t")
    (repo / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    _run(repo, "add", "-A"); _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    (repo / "memgentic" / "x.py").write_text("import os\nimport memgentic_api\n", encoding="utf-8")
    _run(repo, "add", "-A"); _run(repo, "commit", "-m", "violate")
    return repo


def test_load_rules(tmp_path):
    rules = load_rules(Path("tests/fixtures/guard/decisions.yaml"))
    assert {r.id for r in rules} == {"core-import-direction", "no-langchain-in-core"}


def test_engine_fires_on_seeded_import_direction(seeded_repo):
    rules = load_rules(Path("tests/fixtures/guard/decisions.yaml"))
    violations = run(seeded_repo, rules, base="main", staged=False)
    assert any(v.rule_id == "core-import-direction" and v.file == "memgentic/x.py"
               for v in violations)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memgentic.guard.engine'`

- [ ] **Step 4: Implement `blobs.py` and `engine.py`**

```python
# memgentic/memgentic/guard/blobs.py
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def make_blob_getter(repo: Path, ref: str) -> Callable[[str], "str | None"]:
    def get(path: str) -> str | None:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{path}"],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        return out.stdout if out.returncode == 0 else None
    return get
```

```python
# memgentic/memgentic/guard/engine.py
from __future__ import annotations

from pathlib import Path

import yaml

from memgentic.guard import blobs, diff
from memgentic.guard.checks import dependencies, import_direction, imports
from memgentic.models import GuardRule, GuardRuleType, Violation

_CHECKS = {
    GuardRuleType.IMPORT_DIRECTION: import_direction.check,
    GuardRuleType.BANNED_DEPENDENCY: dependencies.check,
    GuardRuleType.BANNED_IMPORT: imports.check,
}


def load_rules(path: Path) -> list[GuardRule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [GuardRule(**r) for r in data.get("rules", [])]


def run(repo: Path, rules: list[GuardRule], *, base: str | None, staged: bool) -> list[Violation]:
    text = diff.get_diff(repo, base=base, staged=staged)
    diff_files = diff.parse_diff(text)
    ref = ":0" if staged else "HEAD"
    getter = blobs.make_blob_getter(repo, ref)
    out: list[Violation] = []
    for rule in rules:
        out.extend(_CHECKS[rule.type](rule, diff_files, getter))
    return out
```

Note: `git show :0:path` reads the staged index; `git show HEAD:path` reads the HEAD (new) side of `main...HEAD`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd memgentic && python -m pytest tests/test_guard_engine.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add memgentic/memgentic/guard/blobs.py memgentic/memgentic/guard/engine.py tests/test_guard_engine.py tests/fixtures/guard/decisions.yaml
git commit -m "feat(guard): engine — load rules, git blob getter, dispatch"
```

---

## Task 7: Formatters

**Files:**
- Create: `memgentic/memgentic/guard/formatters.py`
- Test: `tests/test_guard_formatters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_formatters.py
import json

from memgentic.guard.formatters import format_json, format_text
from memgentic.models import Violation

V = [Violation(rule_id="r1", message="bad import", file="memgentic/x.py", line=2,
               snippet="import memgentic_api")]


def test_format_json_roundtrips():
    data = json.loads(format_json(V))
    assert data["violation_count"] == 1
    assert data["violations"][0]["file"] == "memgentic/x.py"


def test_format_text_mentions_file_and_message():
    text = format_text(V)
    assert "memgentic/x.py" in text and "bad import" in text


def test_format_text_clean():
    assert "0 violations" in format_text([]) or "passed" in format_text([]).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_formatters.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# memgentic/memgentic/guard/formatters.py
from __future__ import annotations

import json

from rich.console import Console
from rich.text import Text

from memgentic.models import Violation


def format_json(violations: list[Violation]) -> str:
    return json.dumps(
        {"violation_count": len(violations),
         "violations": [v.model_dump() for v in violations]},
        indent=2, ensure_ascii=False,
    )


def format_text(violations: list[Violation]) -> str:
    console = Console(record=True, width=100)
    if not violations:
        console.print(Text("✓ 0 violations — rules passed", style="green"))
        return console.export_text()
    for v in violations:
        console.print(Text(f"✗ {v.message}", style="bold red"))
        loc = f"  {v.file}" + (f":{v.line}" if v.line else "")
        console.print(loc)
        if v.snippet:
            console.print(f"    {v.snippet.strip()}")
    console.print(Text(f"\n{len(violations)} violation(s)", style="bold"))
    return console.export_text()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_formatters.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add memgentic/memgentic/guard/formatters.py tests/test_guard_formatters.py
git commit -m "feat(guard): rich + json formatters"
```

---

## Task 8: CLI wiring (inline group in `cli.py`)

**Files:**
- Modify: `memgentic/memgentic/cli.py` (add after the `dream` group block, ~line 1252)
- Test: `tests/test_guard_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_cli.py
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from memgentic.cli import main


def _run(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def clean_repo(tmp_path):
    repo = tmp_path / "r"
    (repo / "memgentic").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _run(repo, "config", "user.email", "t@t.t"); _run(repo, "config", "user.name", "t")
    (repo / "memgentic" / "x.py").write_text("import os\n", encoding="utf-8")
    (repo / "decisions.yaml").write_text(
        'rules:\n  - id: d\n    type: import_direction\n    scope: "memgentic/**"\n'
        '    targets: ["memgentic_api"]\n    message: "no api"\n', encoding="utf-8")
    _run(repo, "add", "-A"); _run(repo, "commit", "-m", "base")
    _run(repo, "checkout", "-b", "feat")
    return repo


def test_clean_branch_exit_0(clean_repo):
    _run(clean_repo, "commit", "--allow-empty", "-m", "noop")
    res = CliRunner().invoke(main, ["guard", "--repo", str(clean_repo), "--base", "main"])
    assert res.exit_code == 0


def test_violation_exit_1(clean_repo):
    (clean_repo / "memgentic" / "x.py").write_text("import os\nimport memgentic_api\n", encoding="utf-8")
    _run(clean_repo, "add", "-A"); _run(clean_repo, "commit", "-m", "bad")
    res = CliRunner().invoke(main, ["guard", "--repo", str(clean_repo), "--base", "main"])
    assert res.exit_code == 1
    assert "memgentic/x.py" in res.output


def test_not_a_repo_exit_2(tmp_path):
    res = CliRunner().invoke(main, ["guard", "--repo", str(tmp_path)])
    assert res.exit_code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd memgentic && python -m pytest tests/test_guard_cli.py -v`
Expected: FAIL — `Error: No such command 'guard'`

- [ ] **Step 3: Implement the inline group** in `memgentic/memgentic/cli.py`

Add after the `dream` group block (logic imported lazily inside the function, mirroring how other commands defer heavy imports):

```python
@main.group("guard")
def guard():
    """Agentic CI: check AI-written diffs against repo rules."""


@guard.command("run")
@click.option("--repo", default=".", help="Repository path")
@click.option("--base", default=None, help="Base ref (default: main)")
@click.option("--staged", is_flag=True, help="Check staged changes")
@click.option("--rules", "rules_path", default=None, help="Path to decisions.yaml")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def guard_run(ctx, repo, base, staged, rules_path, fmt):
    """Check the current diff against decisions.yaml."""
    from pathlib import Path

    from rich.console import Console

    from memgentic.guard import engine, formatters

    console = Console()
    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists():
        console.print(f"[red]Not a git repository:[/red] {repo_path}")
        ctx.exit(2)
    rp = Path(rules_path) if rules_path else repo_path / "decisions.yaml"
    if not rp.exists():
        console.print(f"[yellow]No rules found at {rp}. (run `guard init` — phase 2)[/yellow]")
        ctx.exit(0)
    try:
        rules = engine.load_rules(rp)
        violations = engine.run(repo_path, rules, base=base, staged=staged)
    except Exception as exc:  # config/runtime → exit 2
        console.print(f"[red]guard error:[/red] {exc}")
        ctx.exit(2)
    if fmt == "json":
        console.print(formatters.format_json(violations))
    else:
        console.print(formatters.format_text(violations))
    ctx.exit(1 if any(v for v in violations) else 0)


@guard.command("rules")
@click.option("--repo", default=".", help="Repository path")
@click.option("--rules", "rules_path", default=None, help="Path to decisions.yaml")
def guard_rules(repo, rules_path):
    """Show the loaded rules."""
    from pathlib import Path

    from rich.console import Console

    from memgentic.guard import engine

    console = Console()
    rp = Path(rules_path) if rules_path else Path(repo).resolve() / "decisions.yaml"
    if not rp.exists():
        console.print(f"[yellow]No rules at {rp}[/yellow]")
        return
    for r in engine.load_rules(rp):
        console.print(f"[bold]{r.id}[/bold] ({r.type}) scope={r.scope} targets={r.targets}")
```

Add a Click default-command shim so bare `guard` runs `guard run`: in the test we call `["guard", ...]` — Click groups require a subcommand. To allow bare `guard`, set `invoke_without_command=True` on the group and, when `ctx.invoked_subcommand is None`, forward to `guard_run`. Simplest: keep the tests calling `["guard", "run", ...]` OR add this to the group:

```python
@main.group("guard", invoke_without_command=True)
@click.pass_context
def guard(ctx):
    """Agentic CI: check AI-written diffs against repo rules."""
    if ctx.invoked_subcommand is None:
        ctx.forward(guard_run)
```

If `ctx.forward(guard_run)` complicates option passing, instead update the three tests to call `["guard", "run", ...]` and skip the shim. Pick one and keep tests consistent.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd memgentic && python -m pytest tests/test_guard_cli.py -v`
Expected: PASS (3 passed). Adjust the bare-vs-`run` invocation per the note so tests and CLI agree.

- [ ] **Step 5: Run the full guard suite + lint**

Run: `cd memgentic && python -m pytest tests/test_guard_*.py -v && ruff check memgentic/guard`
Expected: all guard tests PASS; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add memgentic/memgentic/cli.py tests/test_guard_cli.py
git commit -m "feat(guard): inline cli group (run, rules) with exit codes"
```

---

## Task 9: Dogfood validation protocol (manual measurement — the gate)

**Files:**
- Create: `memgentic-strategy/memgentic_guard_planning_package/n1_probe/dogfood.md` (a run log — gitignored working dir)

This task produces evidence, not code. It is the kill gate. **No numeric value-density-on-history threshold.**

- [ ] **Step 1: Seed recall branches (measurement B)**

In the Memgentic repo, create a throwaway branch per rule type and confirm each fires:

```bash
git checkout -b dogfood/seed-import-direction main
# add `import memgentic_api` to a file under memgentic/memgentic/
python -m memgentic.cli guard run --repo . --base main
# expect: exit 1, 1 violation (core-import-direction)
git checkout main && git branch -D dogfood/seed-import-direction
```
Repeat for `banned_dependency` (add `langchain-core` to core `[project] dependencies` in `memgentic/pyproject.toml`). **PASS = engine fires on each seeded violation.**

- [ ] **Step 2: False-positive correctness (measurement A)**

Run guard over real clean history of Memgentic + 2 allvolution repos + 1 external (mem0 or claude-mem), each with a hand-authored `decisions.yaml`:

```bash
for ref in $(git rev-list --max-count=20 main); do
  python -m memgentic.cli guard run --repo . --base "$ref~1" --rules decisions.yaml --format json
done
```
Record every violation. **PASS = ~0 false positives** (FP-rate < 20% is the only gated number). **Zero catches on clean history is EXPECTED — NOT a kill signal.**

- [ ] **Step 3: Record the verdict**

Write `dogfood.md`: per-repo FP count, recall pass/fail per rule type, and the GO/NO-GO. GO → proceed to phase 2 (full offline v0.1). NO-GO (FP leaks AST can't close, or recall fails) → stop and rethink.

- [ ] **Step 4: Commit the run log** (only if not gitignored; otherwise leave as working artifact)

```bash
# memgentic-strategy/ is gitignored — keep dogfood.md as a local working artifact
```

---

## Self-Review

- **Spec coverage:** §3 architecture → Tasks 2-8; §4 models → Task 1; §5 decisions.yaml → Task 6 fixture; §6 AST full-blob → Tasks 3/4/6 (blob getter); §7 Windows hardening → Task 2 (`_git` encoding) + Task 6 (`make_blob_getter` encoding); §9 fixtures → Tasks 3-6; §10 validation → Task 9. All covered.
- **Placeholders:** none — every step has runnable code/commands.
- **Type consistency:** `DiffFile`, `BlobGetter`, `check(rule, diff_files, blob_getter)`, `Violation(rule_id, message, file, line, snippet)`, `GuardRule(id, type, scope, targets, message, source, severity)`, `engine.run(repo, rules, *, base, staged)`, `engine.load_rules(path)` — consistent across Tasks 1-8.
- **Known open item:** the bare-`guard`-vs-`guard run` invocation (Task 8) has two acceptable resolutions; the executor picks one and aligns the tests. Flagged inline, not a blocker.
