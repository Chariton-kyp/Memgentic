from __future__ import annotations

import fnmatch
from collections.abc import Callable

from memgentic.guard.checks._ast_imports import (
    collect_import_records,
    first_added_line,
    is_test_file,
)
from memgentic.guard.checks.csharp_using import extract_using_namespaces
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
        if df.is_binary or df.is_deleted or not _in_scope(df.path, rule.scope):
            continue
        if df.path.endswith(".cs"):
            out.extend(_check_csharp(rule, df, base_blob_getter))
        elif df.path.endswith(".py"):
            out.extend(_check_python(rule, df, blob_getter, base_blob_getter))
    return out


def _check_python(
    rule: GuardRule,
    df: DiffFile,
    blob_getter: BlobGetter,
    base_blob_getter: BlobGetter | None,
) -> list[Violation]:
    # test files may legitimately import banned dev-only packages
    if is_test_file(df.path):
        return []
    blob = blob_getter(df.path)
    if not blob:
        return []
    records = collect_import_records(blob)
    if records is None:
        return []

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

    out: list[Violation] = []
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
            out.append(
                Violation(
                    rule_id=rule.id,
                    message=rule.message,
                    file=df.path,
                    line=line,
                    snippet=df.added_lines.get(line),
                    severity=rule.severity,
                )
            )
            break  # one violation per record
    return out


def _ns_matches_target(namespace: str, target: str) -> bool:
    """C# namespace matches a target if it EQUALS target or starts with target+'.'.

    Case-sensitive (C# namespaces are). So `MediatR` catches `MediatR` and
    `MediatR.Extensions.X` but NOT `MediatRFoo`.
    """
    return namespace == target or namespace.startswith(target + ".")


def _check_csharp(
    rule: GuardRule,
    df: DiffFile,
    base_blob_getter: BlobGetter | None,
) -> list[Violation]:
    # NOTE: the Python is_test_file skip does NOT apply to .cs — C# rules (e.g.
    # the MediatR ban) apply in tests too; rule scope globs control coverage.

    # Base-side suppression: any using namespace already present on the base
    # side is pre-existing, not introduced, so skip it.
    base_namespaces: set[str] = set()
    if base_blob_getter is not None:
        base_blob = base_blob_getter(df.path)
        if base_blob:
            for base_line in base_blob.splitlines():
                base_namespaces.update(extract_using_namespaces(base_line))

    out: list[Violation] = []
    for lineno, text in sorted(df.added_lines.items()):
        for namespace in extract_using_namespaces(text):
            if namespace in base_namespaces:
                continue
            if any(_ns_matches_target(namespace, t) for t in rule.targets):
                out.append(
                    Violation(
                        rule_id=rule.id,
                        message=rule.message,
                        file=df.path,
                        line=lineno,
                        snippet=text.strip(),
                        severity=rule.severity,
                    )
                )
                break  # one violation per line
    return out
