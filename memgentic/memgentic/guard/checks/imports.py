from __future__ import annotations

import fnmatch
from collections.abc import Callable

from memgentic.guard.checks._ast_imports import (
    collect_import_records,
    first_added_line,
    is_test_file,
)
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], str | None]


def _in_scope(path: str, scope: str) -> bool:
    if scope in ("**", "*", ""):
        return True
    return fnmatch.fnmatch(path, scope)


def check(
    rule: GuardRule,
    diff_files: list[DiffFile],
    blob_getter: BlobGetter,
    *,
    base_blob_getter: BlobGetter | None = None,
) -> list[Violation]:
    out: list[Violation] = []
    for df in diff_files:
        # test files may legitimately import banned dev-only packages
        if (
            df.is_binary
            or df.is_deleted
            or not df.path.endswith(".py")
            or is_test_file(df.path)
            or not _in_scope(df.path, rule.scope)
        ):
            continue
        blob = blob_getter(df.path)
        if not blob:
            continue
        records = collect_import_records(blob)
        if records is None:
            continue

        # Build the set of top-level modules already present in the base blob so
        # that a pure reorder or cosmetic change does not re-flag a pre-existing
        # banned import.
        base_top_modules: set[str] = set()
        if base_blob_getter is not None:
            base_blob = base_blob_getter(df.path)
            if base_blob:
                base_records = collect_import_records(base_blob)
                if base_records is not None:
                    for br in base_records:
                        base_top_modules.update(br.top_modules)

        for rec in records:
            if rec.in_type_checking or rec.under_import_error_guard:
                continue
            line = first_added_line(rec, df.added_lines)
            if line is None:
                continue
            for m in rec.top_modules:
                if m not in rule.targets:
                    continue
                # Skip if this banned module was already present in the base
                if m in base_top_modules:
                    continue
                out.append(Violation(rule_id=rule.id, message=rule.message,
                                     file=df.path, line=line, snippet=df.added_lines.get(line)))
                break  # one violation per record
    return out
