# Cross-Tool Continuation

Memgentic's sharpest product wedge is not generic AI memory. It is cross-tool
continuation: a user can stop in Claude Code, open Codex or Gemini CLI later,
and continue from the latest captured work without restating the project state.

## Product Promise

When a supported AI tool starts, it should be able to ask Memgentic:

> What was I just working on, across all AI tools, and what context do I need to
> continue safely?

The answer must be source-backed. Memgentic should show which tool, session,
file, timestamp, and memory rows produced the continuation context.

## Current Vertical Slice

The first implementation is intentionally schema-free and MCP-first:

- `memgentic_handoff` groups recent active memories by original source session.
- The newest source session is listed first.
- Each session bundle includes platform, session ID, title, source file, last
  captured timestamp, topics/entities, and the latest memory/exchange snippets.
- The MCP `continue` prompt asks the client to call `memgentic_handoff` at
  startup and continue from the latest session unless the user says otherwise.
- `memgentic_context` shows which memories Memgentic has already returned to
  the current MCP session. This gives the agent continuity between memory calls
  and avoids repeated recall calls for context it already loaded.
- `memgentic_inventory` exposes the exact persistent memory inventory: counts,
  source/type/profile breakdowns, and a paginated manifest of memory IDs with
  source metadata.

This works with the existing `memories` table because every memory already
stores source provenance: `platform`, `session_id`, `session_title`,
`original_timestamp`, and `file_path`.

## Important Limits

The current handoff is a continuation brief, not a guaranteed full transcript.
Exact last-message fidelity depends on capture mode:

- `raw` and `dual` capture profiles preserve more verbatim exchange context.
- Hook-based captures can ingest `last_n_messages` from tools that expose them.
- Enriched-only memories may summarize or distill the conversation.

The handoff output should therefore preserve uncertainty and cite sources rather
than pretending it has a perfect transcript. The context ledger is also scoped
to the active MCP server process/session; it does not prove what the model has
kept in its hidden attention, only what Memgentic returned to that session.
