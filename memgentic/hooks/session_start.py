"""SessionStart hook — inject compact memory briefing into Claude's context.

Runs once when a new Claude Code session starts. Queries SQLite directly
for recent memories and outputs JSON with additionalContext for silent
injection. No Ollama/embedding dependency — just a database read.

Output format: Claude Code hookSpecificOutput.additionalContext (silent).
Timeout: if anything fails, outputs nothing (safe degradation).
"""

from __future__ import annotations

import asyncio
import json
import sys


def main() -> None:
    try:
        briefing = asyncio.run(asyncio.wait_for(_get_briefing(), timeout=3.0))
        if briefing:
            output = {
                "hookSpecificOutput": {
                    "additionalContext": (
                        "## Memgentic Memory Context\n\n"
                        + briefing
                        + "\n\nUse memgentic_recall(query) for detailed memory search."
                    )
                }
            }
            json.dump(output, sys.stdout)
    except Exception:
        pass  # Silent failure — no output means no injection


async def _get_briefing() -> str:
    from memgentic.config import settings
    from memgentic.processing.context_generator import generate_briefing
    from memgentic.storage.metadata import MetadataStore

    metadata_store = MetadataStore(settings.sqlite_path)
    await metadata_store.initialize()
    try:
        return await generate_briefing(
            metadata_store,
            hours=settings.hook_briefing_hours,
            limit=settings.hook_briefing_limit,
        )
    finally:
        await metadata_store.close()


if __name__ == "__main__":
    main()
