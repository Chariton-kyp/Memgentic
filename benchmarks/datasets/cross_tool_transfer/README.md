# Cross-Tool Transfer dataset

This directory holds the **Memgentic-original** Cross-Tool Transfer
benchmark — the only dataset in `benchmarks/datasets/` that is not
pulled from an upstream academic release.

## Premise

Capture a conversation in tool A (e.g. Claude Code), then issue a
follow-up question from tool B (e.g. ChatGPT). Can Memgentic retrieve
the correct tool-A memory even though the question originates in a
different tool?

This is the scenario MemPalace and other single-tool memory layers
literally cannot run. The benchmark establishes the first public
number for cross-tool memory transfer.

## Reproducibility note

The full dataset is **100 hand-curated multi-turn conversations across
4 tools** (Claude Code, ChatGPT, Gemini CLI, Aider) per the Phase 2
plan. Curation is an ongoing effort; the maintainers will commit the
100-row JSONL to this directory once it's ready.

Today this directory ships only the **tiny fixture** `example.jsonl`
(5 rows) so:

* the runner's CLI is exercisable end-to-end (`python -m
  benchmarks.runners.cross_tool_transfer_bench --help` and
  `--dataset example.jsonl`);
* unit tests have something deterministic to load.

Once the full 100-row dataset lands, this README will note the exact
revision (SHA-256 of the JSONL) the baseline numbers were taken against.

## Format v1 (JSONL)

Each line is one JSON object. Two record shapes are recognised:

### Conversation turn

```json
{
  "role": "turn",
  "tool": "claude_code",
  "turn": 1,
  "content": "We decided to run Qdrant in local file mode for dev.",
  "session_id": "ctt-session-001"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | `"turn"` | optional | Defaults to `"turn"` when `ground_truth_memory_ids` is empty |
| `tool` | string | yes | Platform identifier (`claude_code`, `chatgpt`, `gemini_cli`, `aider`, …). See `_CROSS_TOOL_PLATFORMS` in `benchmarks/lib/corpus_loader.py` for the full mapping |
| `turn` | int | yes | 1-indexed turn number within the session |
| `content` | string | yes | Utterance text — captured verbatim as a `ConversationChunk` |
| `session_id` | string | yes | Conversation identifier; turns with the same `session_id` merge into one session |

### Query

```json
{
  "role": "query",
  "tool": "chatgpt",
  "content": "Remind me which vector DB mode we picked for dev.",
  "ground_truth_memory_ids": ["ctt-session-001"],
  "target_tool": "claude_code",
  "category": "factual_recall"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `role` | `"query"` | optional | Defaults to `"query"` when `ground_truth_memory_ids` is non-empty |
| `tool` | string | yes | Tool issuing the question (source tool) |
| `content` | string | yes | The question text |
| `ground_truth_memory_ids` | list[string] | yes | Session identifiers the retriever should hit. Precision@k uses this set |
| `target_tool` | string | no | The tool where the answer originally lived (for breakdown analytics) |
| `category` | string | no | Query taxonomy tag (e.g. `factual_recall`, `temporal`, `preference`) |

### Role inference

If `role` is absent: a record is treated as a **query** when it carries
a non-empty `ground_truth_memory_ids` list, otherwise as a **turn**.
This keeps tiny fixtures readable — every line can be explicit *or*
elided, at the curator's preference.

### Fields we do not yet use

The plan §7 mentions `source_tool` / `target_tool` breakdowns in the
final report. The loader preserves both via `BenchmarkQuery.metadata`
so a v2 scorer can slice by those dimensions without a schema bump.
