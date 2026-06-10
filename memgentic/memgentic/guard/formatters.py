from __future__ import annotations

import io
import json

from rich.console import Console
from rich.text import Text

from memgentic.models import Violation


def format_json(violations: list[Violation]) -> str:
    return json.dumps(
        {
            "violation_count": len(violations),
            "violations": [v.model_dump() for v in violations],
        },
        indent=2,
        ensure_ascii=False,
    )


def format_text(violations: list[Violation]) -> str:
    console = Console(file=io.StringIO(), record=True, width=100)
    if not violations:
        console.print(Text("✓ 0 violations — rules passed", style="green"))
        return console.export_text()
    for v in violations:
        console.print(Text(f"✗ {v.message}", style="bold red"))
        loc = f"  {v.file}" + (f":{v.line}" if v.line is not None else "")
        console.print(loc, markup=False)
        if v.snippet:
            console.print(f"    {v.snippet.strip()}", markup=False)
    console.print(Text(f"\n{len(violations)} violation(s)", style="bold"))
    return console.export_text()
