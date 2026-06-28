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
import os
import sys


def _resolve_project() -> str | None:
    """Resolve the current project for this session (best-effort, never raises)."""
    try:
        from memgentic.processing.project import resolve_current_project

        return resolve_current_project(env=os.environ, cwd=os.getcwd())
    except Exception:
        return None


def main() -> None:
    try:
        project = _resolve_project()
        # Best-effort: export the resolved project so a co-launched MCP
        # subprocess that inherits this environment scopes recall to it. Cross-
        # process propagation is not guaranteed (the MCP server is usually
        # spawned separately and also resolves the project from its own cwd),
        # so this is an optimisation, not the primary mechanism.
        if project:
            os.environ.setdefault("MEMGENTIC_PROJECT", project)

        briefing = asyncio.run(asyncio.wait_for(_get_briefing(project), timeout=3.0))
        if briefing:
            header = (
                f"## Memgentic Memory Context (project: {project})"
                if project
                else "## Memgentic Memory Context"
            )
            output = {
                "hookSpecificOutput": {
                    "additionalContext": (
                        header
                        + "\n\n"
                        + briefing
                        + "\n\nUse memgentic_recall(query) for detailed memory search."
                    )
                }
            }
            json.dump(output, sys.stdout)
    except Exception:
        pass  # Silent failure — no output means no injection


async def _get_briefing(project: str | None = None) -> str:
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
            project=project if settings.recall_scope == "project" else None,
        )
    finally:
        await metadata_store.close()


if __name__ == "__main__":
    main()
