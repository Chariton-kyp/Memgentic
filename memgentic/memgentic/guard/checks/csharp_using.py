"""Extract C# ``using``-directive namespaces from a source line.

Used by the banned_import check to flag forbidden namespaces in ``.cs`` files.

Matches (returns the namespace on the RIGHT side):
  * ``using X.Y.Z;``
  * ``using static X.Y.Z;``
  * ``global using X.Y.Z;`` / ``global using static X.Y.Z;``
  * alias ``using A = X.Y.Z;``  → returns ``X.Y.Z``

Deliberately does NOT match (to avoid false positives):
  * ``using var x = ...;``            (using statement, C#)
  * ``using (var x = ...)``           (using statement with parens)
  * ``using FileStream fs = ...;``    (C#8 using declaration: type + variable)
  * commented lines (``//``, ``/*``, ``*`` prefixes)
  * string contents (a line whose first non-space char is ``"``)

The regexes are anchored at the start of the (stripped) line so a ``using``
appearing later in a line of code is not picked up.
"""

from __future__ import annotations

import re

# A C# namespace: dotted identifiers. Identifiers may contain unicode letters,
# but ASCII word chars cover the practical cases for ban targets.
_NS = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"

# Plain / static directive: `using [static] <ns>;`
# `static` is optional. The namespace is captured. A trailing `;` is required
# so a using *declaration* (`using FileStream fs = ...;`) — which has a second
# identifier before any `;` — cannot match this pattern.
_DIRECTIVE = re.compile(rf"^using\s+(?:static\s+)?({_NS})\s*;")

# Alias directive: `using <alias> = <ns>;` — capture the RIGHT side.
_ALIAS = re.compile(rf"^using\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*({_NS})\s*;")


def extract_using_namespaces(line: str) -> list[str]:
    """Return the namespace(s) referenced by a using *directive* on this line.

    Returns an empty list for non-directive lines (using statements/declarations,
    comments, strings, ordinary code).
    """
    stripped = line.strip()
    if not stripped:
        return []
    # Skip comments and string-literal lines early.
    if stripped.startswith(("//", "/*", "*", '"')):
        return []

    # Strip an optional leading `global ` modifier (global using).
    body = stripped
    if body.startswith("global "):
        body = body[len("global ") :].lstrip()

    # Alias form first (it also starts with `using ` but has `=`).
    m = _ALIAS.match(body)
    if m:
        return [m.group(1)]

    m = _DIRECTIVE.match(body)
    if m:
        return [m.group(1)]

    return []
