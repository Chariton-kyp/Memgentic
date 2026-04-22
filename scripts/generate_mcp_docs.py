#!/usr/bin/env python3
"""Regenerate ``docs/MCP-TOOLS.md`` from the live MCP tool registry.

Runs ``FastMCP.list_tools()`` so the output always reflects the exact
surface clients see — docstrings, annotations, input schemas. The same
script is used by CI in ``--check`` mode to block PRs that forget to
commit the regenerated markdown.

Usage::

    python scripts/generate_mcp_docs.py          # write docs/MCP-TOOLS.md
    python scripts/generate_mcp_docs.py --check  # exit 1 if it would change
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = ROOT / "docs" / "MCP-TOOLS.md"

HEADER = """# Memgentic MCP Tools

This file is **auto-generated** by ``scripts/generate_mcp_docs.py``. Do not
edit it by hand — CI rejects hand-edits via a drift check. To change a
tool's section, update its docstring, annotations, or Pydantic input model
in ``memgentic/memgentic/mcp/`` and rerun the generator.

Every tool is namespaced ``memgentic_*`` and exposed over the ``mcp[cli]``
transport configured by ``memgentic serve``.

"""


async def _collect_tools() -> list[dict]:
    # Import lazily — keeps `--check` fast failure readable when the package
    # can't import at all.
    sys.path.insert(0, str(ROOT / "memgentic"))
    from memgentic.mcp.server import mcp  # noqa: E402

    tools = await mcp.list_tools()
    rows: list[dict] = []
    for tool in tools:
        rows.append(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "annotations": _annotations_to_dict(tool.annotations),
                "input_schema": getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or {},
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _annotations_to_dict(annotations) -> dict:
    if annotations is None:
        return {}
    if isinstance(annotations, dict):
        return dict(annotations)
    # pydantic-backed annotations (FastMCP ≥ 1.26) — pick the fields we use.
    return {
        key: getattr(annotations, key)
        for key in ("title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
        if hasattr(annotations, key) and getattr(annotations, key) is not None
    }


def _format_tool(tool: dict) -> str:
    lines: list[str] = []
    lines.append(f"## `{tool['name']}`")
    lines.append("")
    ann = tool["annotations"]
    if ann:
        traits = []
        if ann.get("title"):
            traits.append(f"**{ann['title']}**")
        for flag in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            if flag in ann:
                traits.append(f"`{flag}={ann[flag]}`")
        if traits:
            lines.append(" — ".join(traits))
            lines.append("")
    if tool["description"]:
        lines.append(tool["description"])
        lines.append("")
    schema = tool["input_schema"] or {}
    if schema.get("properties"):
        lines.append("**Input schema:**")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(schema, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    else:
        lines.append("_No input parameters._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render(tools: list[dict]) -> str:
    body = "\n".join(_format_tool(t) for t in tools)
    summary = f"Total tools: **{len(tools)}**\n\n"
    return HEADER + summary + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the on-disk file differs from freshly generated output.",
    )
    args = parser.parse_args()

    tools = asyncio.run(_collect_tools())
    generated = render(tools)

    if args.check:
        if not DOC_PATH.exists():
            sys.stderr.write(f"{DOC_PATH} does not exist; run without --check to create.\n")
            return 1
        on_disk = DOC_PATH.read_text(encoding="utf-8")
        if on_disk != generated:
            sys.stderr.write(
                f"{DOC_PATH} is stale. Regenerate with:\n    python scripts/generate_mcp_docs.py\n"
            )
            return 1
        print(f"{DOC_PATH} is up to date.")
        return 0

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(generated, encoding="utf-8")
    print(f"Wrote {DOC_PATH} ({len(tools)} tools).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
