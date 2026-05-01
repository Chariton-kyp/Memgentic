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

## Next Product Steps

1. Add a session ledger table for explicit source sessions, last message time,
   open/closed state, current branch/repo, and active task.
2. Make SessionStart hooks call `memgentic_handoff` automatically for Claude
   Code, Codex, and Gemini CLI.
3. Add a dashboard "Continue" page showing recent cross-tool sessions and one
   click copy/open prompts.
4. Add a dashboard "Memory Inventory" page showing exactly what is stored,
   loaded into the current context, trusted, stale, or pending review.
5. Store structured `next_actions`, `blocked_on`, `files_touched`, and
   `decisions` fields for high-quality resume cards.
6. Add memory review states (`proposed`, `accepted`, `rejected`, `stale`) so
   team continuation uses trusted context only by default.

## Commercial Differentiator

Most memory products sell "long-term agent memory." Memgentic should sell:

> Shared project memory for AI coding teams. Continue work across Claude Code,
> Codex, Cursor, Gemini CLI, ChatGPT, and MCP agents with local-first,
> source-backed handoffs.

That is more concrete, easier to demo, and easier to monetize than a generic
vector-memory backend.
