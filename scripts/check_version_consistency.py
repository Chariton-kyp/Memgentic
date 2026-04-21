#!/usr/bin/env python3
"""Verify all Memgentic package versions agree.

Run in CI on every PR to block merges that would drift the three
packages apart. Run locally via ``make check-versions``.

Exits 0 if all versions match; exits 1 with a diff table otherwise.
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_core_version() -> str:
    text = (ROOT / "memgentic" / "memgentic" / "__version__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if match is None:
        raise RuntimeError("Could not parse __version__ from memgentic/memgentic/__version__.py")
    return match.group(1)


def read_api_pyproject_version() -> str:
    data = tomllib.loads((ROOT / "memgentic-api" / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def read_api_init_version() -> str:
    text = (ROOT / "memgentic-api" / "memgentic_api" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if match is None:
        raise RuntimeError(
            "Could not parse __version__ from memgentic-api/memgentic_api/__init__.py"
        )
    return match.group(1)


def read_native_cargo_version() -> str:
    data = tomllib.loads((ROOT / "memgentic-native" / "Cargo.toml").read_text(encoding="utf-8"))
    return data["package"]["version"]


def read_native_pyproject_version() -> str:
    data = tomllib.loads((ROOT / "memgentic-native" / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


SOURCES: list[tuple[str, Callable[[], str]]] = [
    ("memgentic/memgentic/__version__.py", read_core_version),
    ("memgentic-api/pyproject.toml", read_api_pyproject_version),
    ("memgentic-api/memgentic_api/__init__.py", read_api_init_version),
    ("memgentic-native/Cargo.toml", read_native_cargo_version),
    ("memgentic-native/pyproject.toml", read_native_pyproject_version),
]


def main() -> int:
    results: list[tuple[str, str]] = []
    errors: list[str] = []
    for label, reader in SOURCES:
        try:
            results.append((label, reader()))
        except Exception as exc:
            errors.append(f"  {label}: ERROR — {exc}")

    if errors:
        print("Could not read one or more version sources:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 2

    versions = {version for _, version in results}
    if len(versions) == 1:
        (version,) = versions
        print(f"OK — all {len(results)} version sources report {version}")
        return 0

    width = max(len(label) for label, _ in results)
    print("VERSION MISMATCH across Memgentic packages:", file=sys.stderr)
    print("-" * (width + 12), file=sys.stderr)
    for label, version in results:
        print(f"  {label:<{width}}  {version}", file=sys.stderr)
    print("-" * (width + 12), file=sys.stderr)
    print(
        "Memgentic uses linked versioning — all 3 packages MUST report the "
        "same version. Let release-please (see "
        "docs/architecture/release-automation.md) manage bumps; do not "
        "hand-edit these files.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
