"""UserPromptSubmit hook — lightweight memory availability nudge.

Does NOT perform search (that would add 2-5s latency per prompt).
Instead, outputs a minimal systemMessage reminding Claude that
memory tools are available. Actual search happens via MCP tools
or SKILL.md subagent when Claude decides it needs context.

This matches the memsearch pattern: nudge, don't search.
"""

from __future__ import annotations


def main() -> None:
    # Intentionally empty — no per-prompt overhead.
    # Memory retrieval is pull-based via MCP tools and SKILL.md.
    # The SessionStart hook already provides initial context.
    pass


if __name__ == "__main__":
    main()
