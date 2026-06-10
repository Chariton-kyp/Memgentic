from __future__ import annotations

import ast
import re
from dataclasses import dataclass

_TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")


def is_test_file(path: str) -> bool:
    return bool(_TEST_FILE.search(path))


@dataclass
class ImportRecord:
    top_modules: list[str]
    lineno: int
    end_lineno: int
    in_type_checking: bool
    under_import_error_guard: bool


def _is_type_checking_test(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _type_checking_lines(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and _is_type_checking_test(n.test):
            # Only walk the if-body, NOT the else-branch (orelse).
            # An import in the else-branch is a real runtime dependency.
            for stmt in n.body:
                for c in ast.walk(stmt):
                    if isinstance(c, (ast.Import, ast.ImportFrom)):
                        out.add(c.lineno)
    return out


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    out: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[child] = parent
    return out


_IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})


def _is_import_error_type(t: ast.expr | None) -> bool:
    if isinstance(t, ast.Name):
        return t.id in _IMPORT_ERRORS
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in _IMPORT_ERRORS for e in t.elts)
    return False


def _under_import_error_guard(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.Try) and any(_is_import_error_type(h.type) for h in cur.handlers):
            return True
        cur = parents.get(cur)
    return False


def collect_import_records(blob: str) -> list[ImportRecord] | None:
    """Parse the full blob and return import records, or None if unparseable."""
    # Strip UTF-8 BOM if present; ast.parse raises SyntaxError on it in some versions
    if blob.startswith("﻿"):
        blob = blob[1:]
    try:
        tree = ast.parse(blob)
    except SyntaxError:
        return None
    tc = _type_checking_lines(tree)
    parents = _parents(tree)
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        else:
            continue
        records.append(
            ImportRecord(
                top_modules=mods,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", None) or node.lineno,
                in_type_checking=node.lineno in tc,
                under_import_error_guard=_under_import_error_guard(node, parents),
            )
        )
    return records


def first_added_line(rec: ImportRecord, added_lines: dict[int, str]) -> int | None:
    added = [ln for ln in range(rec.lineno, rec.end_lineno + 1) if ln in added_lines]
    return min(added) if added else None
