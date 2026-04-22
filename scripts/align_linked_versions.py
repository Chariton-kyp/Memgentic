#!/usr/bin/env python3
"""Align ``memgentic-native`` (and any future lagging component) to the
linked-group version inside a release-please PR.

release-please's ``linked-versions`` plugin only lifts a component whose
directory had a releaseable commit in the window. If one package was
quiet, it stays behind while the others bump, and the next publish
cycle skips the quiet one. This script detects that drift, updates the
lagging component's version files, and emits ``changed=true`` on
``$GITHUB_OUTPUT`` so the CI job that invokes it can commit + push.

Called by ``.github/workflows/linked-version-align.yml``. No side effects
beyond file edits; the workflow handles the commit.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".release-please-manifest.json"

# Each component: the files whose version string must match the manifest.
COMPONENT_FILES: dict[str, list[tuple[Path, str]]] = {
    "memgentic": [
        (ROOT / "memgentic/memgentic/__version__.py",
         r'__version__\s*=\s*"([^"]+)"'),
    ],
    "memgentic-api": [
        (ROOT / "memgentic-api/memgentic_api/__init__.py",
         r'__version__\s*=\s*"([^"]+)"'),
    ],
    "memgentic-native": [
        (ROOT / "memgentic-native/pyproject.toml",
         r'^version\s*=\s*"([^"]+)"'),
        (ROOT / "memgentic-native/Cargo.toml",
         r'^version\s*=\s*"([^"]+)"'),
        (ROOT / "memgentic-native/Cargo.lock",
         r'^name = "memgentic-native"\nversion = "([^"]+)"'),
    ],
}


def set_github_output(key: str, value: str) -> None:
    """Write ``key=value`` to ``$GITHUB_OUTPUT`` if running on Actions."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def bump_file(path: Path, pattern: str, new_version: str) -> bool:
    """Replace the captured version in ``path`` if present. Returns True on edit."""
    if not path.exists():
        print(f"  skip (missing): {path.relative_to(ROOT)}")
        return False
    text = path.read_text(encoding="utf-8")
    flags = re.MULTILINE | (re.DOTALL if "\n" in pattern else 0)
    match = re.search(pattern, text, flags)
    if not match:
        print(f"  skip (no match): {path.relative_to(ROOT)}")
        return False
    current = match.group(1)
    if current == new_version:
        return False
    new_text = text.replace(match.group(0), match.group(0).replace(current, new_version))
    path.write_text(new_text, encoding="utf-8")
    print(f"  bumped {path.relative_to(ROOT)}: {current} -> {new_version}")
    return True


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    versions = set(manifest.values())

    if len(versions) == 1:
        target = next(iter(versions))
        print(f"All components already aligned at {target}. Nothing to do.")
        set_github_output("changed", "false")
        return 0

    target = max(versions, key=_version_key)
    print(f"Linked-version drift detected. Target: {target}")
    print(f"Manifest before: {manifest}")

    manifest_changed = False
    files_changed = False
    for component, files in COMPONENT_FILES.items():
        current = manifest.get(component)
        if current == target:
            continue
        print(f"Aligning {component}: {current} -> {target}")
        for path, pattern in files:
            files_changed |= bump_file(path, pattern, target)
        manifest[component] = target
        manifest_changed = True

    if manifest_changed:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Manifest after: {manifest}")
        set_github_output("changed", "true")
    elif files_changed:
        # Shouldn't happen — files can't be out-of-sync with the manifest
        # unless someone hand-edited something. Commit the file fix anyway.
        set_github_output("changed", "true")
    else:
        print("Nothing to commit.")
        set_github_output("changed", "false")

    return 0


def _version_key(v: str) -> tuple[int, ...]:
    """Crude semver sort: ``1.2.10`` > ``1.2.9``. Pre-release suffixes ignored."""
    core = v.split("-", 1)[0]
    return tuple(int(x) for x in core.split(".") if x.isdigit())


if __name__ == "__main__":
    sys.exit(main())
