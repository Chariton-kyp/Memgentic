#!/usr/bin/env python3
"""Pre-commit shim: run ``memgentic guard --staged`` when guard is available.

Why a shim instead of a direct ``entry`` command:

* The same ``.pre-commit-config.yaml`` runs locally (where the ``memgentic``
  package is installed) and in CI's "Run pre-commit on changed files" job
  (where it may NOT be installed). If guard isn't importable we must exit 0 so
  the hook never blocks unrelated work — guard is advisory tooling, not a
  required build dependency.
* Keeping the logic in a file (rather than a brittle ``python -c`` one-liner in
  YAML) makes it readable and unit-testable.

Behaviour:
* ``memgentic`` not importable  -> exit 0 (skip silently; CI-safe).
* not inside a git work tree     -> exit 0 (nothing to check).
* otherwise                      -> exit with ``memgentic guard --staged``'s
  own exit code (1 = violations found, which blocks the commit and prints them).

This module is intentionally dependency-free (stdlib only).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys


def main() -> int:
    # Skip silently when the package isn't installed (e.g. CI pre-commit job).
    if importlib.util.find_spec("memgentic") is None:
        return 0

    # Skip when not in a git work tree (defensive; pre-commit always runs in one).
    try:
        in_tree = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        # git not on PATH — nothing we can check.
        return 0
    if in_tree.returncode != 0 or in_tree.stdout.strip() != "true":
        return 0

    # Delegate to the real guard CLI on the staged diff. Its exit code is the
    # contract: 0 = clean, 1 = violations (blocks the commit), 2 = guard error.
    return subprocess.call([sys.executable, "-m", "memgentic.cli", "guard", "--staged"])


if __name__ == "__main__":
    raise SystemExit(main())
