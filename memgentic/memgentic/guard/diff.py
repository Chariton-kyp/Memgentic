from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# Capture the b-side path from "diff --git a/... b/...".
# Note: cannot disambiguate paths containing " b/" (a known git diff-header
# ambiguity); acceptable for this slice.
_DIFF_GIT = re.compile(r"^diff --git a/.+ b/(.+)$")


@dataclass
class DiffFile:
    path: str
    added_lines: dict[int, str] = field(default_factory=dict)
    is_binary: bool = False
    is_deleted: bool = False


def _git(repo: Path, args: list[str]) -> str:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args[:2])} failed (rc={out.returncode}): {out.stderr.strip()}"
        )
    return out.stdout


def get_diff(repo: Path, *, base: str | None = None, staged: bool = False) -> str:
    if staged:
        return _git(repo, ["diff", "--staged", "--no-color", "-U0", "--find-renames"])
    explicit_base = base is not None
    ref = base or "main"
    try:
        return _git(repo, ["diff", f"{ref}...HEAD", "--no-color", "-U0", "--find-renames"])
    except RuntimeError as exc:
        msg = str(exc)
        _bad = ("unknown revision", "ambiguous argument", "bad revision")
        if not explicit_base and any(phrase in msg for phrase in _bad):
            raise RuntimeError(
                f"base ref '{ref}' not found — pass --base <your-default-branch>"
                " (e.g. --base master)"
            ) from exc
        raise


def parse_diff(text: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    cur: DiffFile | None = None
    pending_path: str = ""  # b-side path captured from "diff --git" header
    new_lineno = 0

    # split("\n") (not splitlines) so form-feed/NEL/etc. inside source lines
    # cannot split a line mid-content and desync the @@ line arithmetic.
    # rstrip("\r") below is then the sole CRLF handler.
    for raw in text.split("\n"):
        line = raw.rstrip("\r")

        if line.startswith("diff --git "):
            cur = None
            # Capture the b-side path as fallback for binary files (no +++ line)
            m = _DIFF_GIT.match(line)
            pending_path = m.group(1) if m else ""
            continue

        if line.startswith("Binary files "):
            # Binary diffs have no +++ line; use the pending_path captured above
            path = pending_path or ""
            if path:
                cur = DiffFile(path=path, is_binary=True)
                files.append(cur)
            continue

        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                # Deleted file — still track it
                path = pending_path
                is_deleted = True
            else:
                path = target[2:] if target.startswith("b/") else target
                is_deleted = False
            cur = DiffFile(path=path, is_deleted=is_deleted)
            files.append(cur)
            continue

        if line.startswith("--- "):
            # Skip --- lines; path is captured from +++
            continue

        m = _HUNK.match(line)
        if m:
            new_lineno = int(m.group(1))
            continue

        if cur is None or cur.is_binary:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            cur.added_lines[new_lineno] = line[1:].lstrip("﻿")
            new_lineno += 1
        elif line.startswith(" "):
            new_lineno += 1

    return [f for f in files if f.path]
