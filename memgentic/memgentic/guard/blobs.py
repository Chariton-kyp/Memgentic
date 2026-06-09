from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def make_blob_getter(repo: Path, ref: str) -> Callable[[str], str | None]:
    """Return a getter that yields the full new-side content of a path at `ref`."""
    def get(path: str) -> str | None:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{path}"],
            capture_output=True, encoding="utf-8", errors="replace", check=False, timeout=30,
        )
        return out.stdout if out.returncode == 0 else None
    return get
