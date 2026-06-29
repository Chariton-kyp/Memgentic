#!/usr/bin/env python3
"""Backfill release tags the manifest declares but git is missing.

``main`` can end up version-bumped but UNTAGGED two ways: (1)
``linked-version-align.yml`` bumps a quiet component's version *files*
without release-please releasing it, or (2) release-please aborts release
creation on merge entirely ("untagged, merged release PRs outstanding")
and creates zero tags. Either way the manifest runs ahead of reality, and
on its next run release-please re-scans the lagging component from
``bootstrap-sha``, re-counts an already-shipped breaking change, and
proposes a bogus major bump (this is what pushed ``memgentic-api`` to a
phantom 2.0.0 in 2026-06).

This script reads ``.release-please-manifest.json``, derives each
component's expected git tag (mirroring the tag rules in
``.release-please-config.json``), and prints — one per line on stdout —
the tags that do not yet exist on ``origin``. The calling workflow
(``reconcile-release-tags.yml``, which runs on every push to main
independently of release-please's outcome) creates and pushes them at the
commit that last changed the manifest (the release commit), firing the
matching ``release*.yml`` publish workflow (PyPI + GitHub Release).

Mirrors ``scripts/align_linked_versions.py``: pure detection, no git
side effects beyond the read-only ``ls-remote`` probe — the workflow owns
tag creation. Human-readable progress goes to stderr; stdout carries only
the machine-readable list of missing tags.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".release-please-manifest.json"

# manifest key -> tag template. Mirrors the tag rules in
# .release-please-config.json:
#   memgentic        include-component-in-tag: false  ->  v{ver}
#   memgentic-api    component "api"                  ->  api-v{ver}
#   memgentic-native component "native"               ->  native-v{ver}
TAG_TEMPLATES: dict[str, str] = {
    "memgentic": "v{}",
    "memgentic-api": "api-v{}",
    "memgentic-native": "native-v{}",
}


def expected_tags(manifest: dict[str, str]) -> dict[str, str]:
    """Map each known component to the tag its manifest version implies."""
    tags: dict[str, str] = {}
    for component, template in TAG_TEMPLATES.items():
        version = manifest.get(component)
        if version:
            tags[component] = template.format(version)
        else:
            print(f"  warn: {component} absent from manifest", file=sys.stderr)
    return tags


def tag_exists_on_remote(tag: str) -> bool:
    """True if ``refs/tags/{tag}`` already exists on ``origin``."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    missing: list[str] = []
    for component, tag in expected_tags(manifest).items():
        if tag_exists_on_remote(tag):
            print(f"  ok: {tag} already released", file=sys.stderr)
        else:
            print(f"  MISSING: {tag} (component {component})", file=sys.stderr)
            missing.append(tag)

    # stdout = machine-readable: one missing tag per line for the workflow.
    for tag in missing:
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
