from __future__ import annotations

import io
import json
from typing import IO

from rich.console import Console
from rich.text import Text

from memgentic.models import Violation

# Glyphs the pretty (Unicode) renderer uses, paired with ASCII fallbacks for
# legacy consoles (e.g. Greek Windows cp1253) that cannot encode them. Writing
# ✓/✗/⚠ to a strict cp1253 stream raises UnicodeEncodeError and crashes the
# guard — the pre-commit hook path is especially exposed because hooks run in
# whatever console the user has, often without a UTF-8 reconfigure.
_GLYPHS = {
    "ok": ("✓", "[OK]"),
    "error": ("✗", "[X]"),
    "warn": ("⚠", "[WARN]"),
    "dash": ("—", "-"),
}

# The probe string used to decide whether a stream can carry the pretty glyphs.
_PROBE = "".join(uni for uni, _ascii in _GLYPHS.values())


def stream_supports_unicode(stream: IO[str] | object | None) -> bool:
    """Return True only if ``stream`` can encode the guard's Unicode glyphs.

    Robust against streams with no ``encoding`` attribute (treated as unsafe)
    and against odd encodings. Used by the CLI / pre-commit hook to pick the
    ASCII fallback when stdout is a legacy codepage, so guard never crashes
    with UnicodeEncodeError on a Greek/Turkish/etc. Windows console.
    """
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    try:
        _PROBE.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def format_json(violations: list[Violation]) -> str:
    return json.dumps(
        {
            "violation_count": len(violations),
            "violations": [v.model_dump() for v in violations],
        },
        indent=2,
        ensure_ascii=False,
    )


def format_text(violations: list[Violation], *, ascii_only: bool = False) -> str:
    """Render violations as human-readable text.

    When ``ascii_only`` is True, the symbol glyphs (✓ ✗ ⚠ —) are replaced with
    ASCII markers ([OK] [X] [WARN] -) so the output is safe to write to a
    legacy-codepage console without raising UnicodeEncodeError. Callers that
    know stdout is UTF-8 leave it False for the prettier glyph output.
    """

    def g(name: str) -> str:
        uni, asc = _GLYPHS[name]
        return asc if ascii_only else uni

    console = Console(file=io.StringIO(), record=True, width=100)
    if not violations:
        console.print(Text(f"{g('ok')} 0 violations {g('dash')} rules passed", style="green"))
        return console.export_text()
    errors = sum(1 for v in violations if v.severity == "error")
    warns = len(violations) - errors
    for v in violations:
        if v.severity == "warn":
            console.print(Text(f"{g('warn')} {v.message}", style="bold yellow"))
        else:
            console.print(Text(f"{g('error')} {v.message}", style="bold red"))
        loc = f"  {v.file}" + (f":{v.line}" if v.line is not None else "")
        console.print(loc, markup=False)
        if v.snippet:
            console.print(f"    {v.snippet.strip()}", markup=False)
    summary = f"\n{errors} error(s), {warns} warning(s)"
    console.print(Text(summary, style="bold"))
    return console.export_text()
