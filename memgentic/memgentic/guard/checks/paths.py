"""forbidden_path check — fires when a diff touches a path matching any target glob.

Semantics:
  * "Touches" means the file appears in the diff at all — additions,
    modifications, AND deletions (``is_deleted=True`` still fires; these rules
    mean "never commit OR modify").
  * Binary files fire too (a committed ``.env`` can be binary-ish).
  * Targets are fnmatch globs. Note fnmatch's ``*`` crosses ``/``, so
    ``dir/**`` style targets match descendants. A leading ``**/`` is also
    matched against the path with that prefix stripped, so ``**/.env`` catches
    both a root-level ``.env`` and ``dir/sub/.env`` (mirroring gitignore's
    "match at any depth, including the top" semantics) while still NOT matching
    ``.env.example`` — the basename differs.
  * ``rule.scope`` gates which files are considered (default ``**`` = all).
  * Base-side suppression does NOT apply — touching a forbidden path is always
    reportable. ``base_blob_getter`` is accepted for interface consistency and
    ignored.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable

from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], str | None]


def _in_scope(path: str, scope: str) -> bool:
    if scope in ("**", "*", ""):
        return True
    return fnmatch.fnmatch(path, scope)


def _path_matches(path: str, target: str) -> bool:
    if fnmatch.fnmatch(path, target):
        return True
    # A leading ``**/`` should also match at the top level (gitignore-style),
    # e.g. ``**/.env`` catches a root ``.env``. Stripping the prefix keeps the
    # basename intact, so ``.env.example`` still won't match ``**/.env``.
    if target.startswith("**/"):
        return fnmatch.fnmatch(path, target[3:])
    return False


def check(
    rule: GuardRule,
    diff_files: list[DiffFile],
    blob_getter: BlobGetter,
    *,
    base_blob_getter: BlobGetter | None = None,
) -> list[Violation]:
    # base_blob_getter is intentionally ignored: touching a forbidden path is
    # always reportable, even if the path already existed on the base side.
    out: list[Violation] = []
    for df in diff_files:
        if not _in_scope(df.path, rule.scope):
            continue
        if any(_path_matches(df.path, target) for target in rule.targets):
            out.append(
                Violation(
                    rule_id=rule.id,
                    message=rule.message,
                    file=df.path,
                    line=None,
                    snippet=None,
                    severity=rule.severity,
                )
            )
    return out
