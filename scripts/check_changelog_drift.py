#!/usr/bin/env python3
"""Verify CHANGELOG.md top entry matches .release-please-manifest.json.

release-please writes both files in the same Release PR. If main carries
a CHANGELOG whose top entry disagrees with the manifest, something
hand-edited one of them and the next automated release will mis-bump.

Exits 0 if they agree; exits 1 with a diff.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_manifest_version() -> str:
    data = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    # All three entries must agree by design (linked versions). Take the
    # core package as the canonical one and cross-check.
    core = data.get("memgentic")
    if core is None:
        raise RuntimeError("manifest is missing the 'memgentic' package entry")
    for name, version in data.items():
        if version != core:
            raise RuntimeError(
                f"linked-versions manifest is internally inconsistent: "
                f"memgentic={core} but {name}={version}"
            )
    return core


def read_changelog_top_version() -> str | None:
    path = ROOT / "CHANGELOG.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # Skip any leading `## [Unreleased]` placeholder that predates the
    # first release-please cycle — it's not a version and carries no drift.
    for match in re.finditer(r"^##\s+\[([^\]]+)\]", text, re.MULTILINE):
        token = match.group(1).strip()
        if token.lower() == "unreleased":
            continue
        return token
    return None


def main() -> int:
    manifest_version = read_manifest_version()
    changelog_version = read_changelog_top_version()

    if changelog_version is None:
        print(
            "INFO — CHANGELOG.md is absent or has no '## [x.y.z]' heading yet. "
            "Expected on first release-please run; no drift to check.",
            file=sys.stderr,
        )
        return 0

    if manifest_version == changelog_version:
        print(f"OK — CHANGELOG top entry and manifest both report {manifest_version}")
        return 0

    print("CHANGELOG DRIFT:", file=sys.stderr)
    print(f"  .release-please-manifest.json  {manifest_version}", file=sys.stderr)
    print(f"  CHANGELOG.md (top entry)       {changelog_version}", file=sys.stderr)
    print(
        "These must agree. release-please updates both in lockstep — one of "
        "them was hand-edited. Let release-please reconcile by not merging "
        "any non-release-please PR that touches these files directly.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
