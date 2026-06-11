# Memgentic MCP Tools

This file is **auto-generated** by ``scripts/generate_mcp_docs.py``. Do not
edit it by hand — CI rejects hand-edits via a drift check. To change a
tool's section, update its docstring, annotations, or Pydantic input model
in ``memgentic/memgentic/mcp/`` and rerun the generator.

Every tool is namespaced ``memgentic_*`` and exposed over the ``mcp[cli]``
transport configured by ``memgentic serve``.

Total tools: **36**

## `memgentic_briefing`

**Cross-Agent Briefing** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Render a Recall Tiers briefing (default: T0 + T1 under ~900 tokens).

Backward-compatible:
- No args → T0+T1 wake-up bundle
- ``tier="T2"`` + ``collection``/``topic`` → Orbit tier
- ``tier="T3"`` + ``query`` → Deep Recall (hybrid search)
- ``tier="T4"`` + ``entity`` → Atlas (KG traversal; stubbed when empty)
- ``since_hours=N`` with no ``tier`` → legacy summary (deprecated)

Returns assembled briefing text.

**Input schema:**

```json
{
  "$defs": {
    "BriefingInput": {
      "description": "Input for cross-agent briefing (Recall Tiers).\n\nBackward-compatible: with no arguments, the tool returns the\ndefault T0+T1 wake-up bundle. Passing ``since_hours`` (legacy)\nwithout a ``tier`` keeps the pre-Recall-Tiers time-window summary\nworking for agents with pinned prompts. When ``tier`` is supplied,\nRecall Tiers is used and ``since_hours`` is ignored.",
      "properties": {
        "collection": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Scope T1/T2 to a collection name.",
          "title": "Collection"
        },
        "entity": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Entity to traverse for T4 Atlas.",
          "title": "Entity"
        },
        "max_tokens": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Clamp a tier's token budget below the tier ceiling.",
          "title": "Max Tokens"
        },
        "model_context": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Override detected model context (tokens).",
          "title": "Model Context"
        },
        "query": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Query text for T3 Deep Recall.",
          "title": "Query"
        },
        "since_hours": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "[Deprecated] Legacy time-window briefing. If set and ``tier`` is omitted, the pre-Recall-Tiers summary is returned. Range 1-720 hours.",
          "title": "Since Hours"
        },
        "tier": {
          "anyOf": [
            {
              "enum": [
                "T0",
                "T1",
                "T2",
                "T3",
                "T4",
                "default"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Recall Tier to render. 'default' (or omitted) returns T0+T1. Explicit values render that tier alone.",
          "title": "Tier"
        },
        "topic": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Scope T2 to a topic tag.",
          "title": "Topic"
        }
      },
      "title": "BriefingInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/BriefingInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_briefingArguments",
  "type": "object"
}
```

## `memgentic_capture_profile`

**Get or Set Capture Profile** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get or set the default capture profile.

Profiles:
    - raw: verbatim chunks, no LLM enrichment
    - enriched: current default (topics/entities/LLM importance)
    - dual: both rows stored and paired via dual_sibling_id (2x storage)

Args:
    params: action ('get' or 'set') and, when setting, the new profile.

Returns:
    Markdown describing the current (and previous, when set) profile.

**Input schema:**

```json
{
  "$defs": {
    "CaptureProfileInput": {
      "additionalProperties": false,
      "description": "Input for ``memgentic_capture_profile`` (get/set the default profile).",
      "properties": {
        "action": {
          "description": "Whether to read the current default ('get') or change it ('set').",
          "enum": [
            "get",
            "set"
          ],
          "title": "Action",
          "type": "string"
        },
        "profile": {
          "anyOf": [
            {
              "enum": [
                "raw",
                "enriched",
                "dual"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Required when action='set'. New default profile to persist.",
          "title": "Profile"
        }
      },
      "required": [
        "action"
      ],
      "title": "CaptureProfileInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/CaptureProfileInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_capture_profile_toolArguments",
  "type": "object"
}
```

## `memgentic_configure_session`

**Configure Session Filters** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Set session-level default filters for memory recall.

All subsequent `memgentic_recall` calls in this session will use these
defaults unless explicitly overridden per-call.

Args:
    params (ConfigureSessionInput): Session filters:
        - include_sources: Only these platforms (e.g., ['claude_code', 'gemini_cli'])
        - exclude_sources: Exclude these (e.g., ['codex_cli'])
        - content_types: Only these types (e.g., ['decision', 'code_snippet'])
        - min_confidence: Minimum confidence (0.0-1.0)

Returns:
    str: Confirmation of applied session configuration.

Examples:
    - include_sources=["claude_code", "gemini_cli"] → only these two
    - exclude_sources=["codex_cli"] → everything except Codex
    - content_types=["decision"] → only decisions

**Input schema:**

```json
{
  "$defs": {
    "ConfigureSessionInput": {
      "additionalProperties": false,
      "description": "Input for setting session-level source filters.",
      "properties": {
        "content_types": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Only include these content types",
          "title": "Content Types"
        },
        "exclude_projects": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Exclude memories from these project keys.",
          "title": "Exclude Projects"
        },
        "exclude_sources": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Exclude these platforms from all recall calls",
          "title": "Exclude Sources"
        },
        "include_projects": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Only include memories from these project keys (lowercase). Pass ['auto'] to resolve from the MCP subprocess cwd.",
          "title": "Include Projects"
        },
        "include_sources": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Only include these platforms in all recall calls (None = all)",
          "title": "Include Sources"
        },
        "min_confidence": {
          "default": 0.0,
          "description": "Minimum confidence threshold (0.0-1.0)",
          "maximum": 1.0,
          "minimum": 0.0,
          "title": "Min Confidence",
          "type": "number"
        }
      },
      "title": "ConfigureSessionInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/ConfigureSessionInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_configure_sessionArguments",
  "type": "object"
}
```

## `memgentic_context`

**Loaded Memory Context** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Show or clear memories returned to the current MCP session.

This answers a different question than inventory: not "what exists in the
database?", but "what memory has Memgentic already handed to this agent
during this active context?" It gives agents continuity between memory
calls and reduces repeated recall requests.

**Input schema:**

```json
{
  "$defs": {
    "ContextInput": {
      "additionalProperties": false,
      "description": "Input for inspecting the current MCP session's loaded memory context.",
      "properties": {
        "action": {
          "default": "show",
          "description": "Show or clear the memories already returned to this MCP session.",
          "enum": [
            "show",
            "clear"
          ],
          "title": "Action",
          "type": "string"
        },
        "limit": {
          "default": 50,
          "maximum": 200,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        }
      },
      "title": "ContextInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/ContextInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_contextArguments",
  "type": "object"
}
```

## `memgentic_dedupe_check`

**Near-Duplicate Check** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Scan existing memories for near-duplicates of candidate content.

Intended to run *before* a write so callers can skip or merge instead of
creating duplicates. Reuses the same embedder + vector backend as recall,
so the similarity score matches what semantic search would surface.

Returns:
    ``{is_duplicate, threshold, matches: [{id, similarity,
    content_preview, source}]}``. ``is_duplicate`` is True when the top
    match's similarity is at or above ``threshold``.

**Input schema:**

```json
{
  "$defs": {
    "DedupeCheckInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_dedupe_check`.",
      "properties": {
        "content": {
          "description": "Candidate content to check for near-duplicates before a write.",
          "maxLength": 10000,
          "minLength": 3,
          "title": "Content",
          "type": "string"
        },
        "limit": {
          "default": 5,
          "description": "Maximum number of near-duplicate matches to return.",
          "maximum": 50,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "scope": {
          "default": "all",
          "description": "Search scope. 'all' spans every memory; 'session' and 'collection' reserve surface for future filtering (currently behave as 'all').",
          "enum": [
            "all",
            "session",
            "collection"
          ],
          "title": "Scope",
          "type": "string"
        },
        "threshold": {
          "default": 0.9,
          "description": "Cosine-similarity cutoff. Matches with score \u2265 threshold count as duplicates. Vector backend returns similarity (higher = closer).",
          "maximum": 1.0,
          "minimum": 0.0,
          "title": "Threshold",
          "type": "number"
        }
      },
      "required": [
        "content"
      ],
      "title": "DedupeCheckInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/DedupeCheckInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_dedupe_checkArguments",
  "type": "object"
}
```

## `memgentic_dream_apply`

**Apply Dream Patches** — `readOnlyHint=False` — `destructiveHint=True` — `idempotentHint=True` — `openWorldHint=False`

Execute a dream's proposed patches against the live memory store.

**Input schema:**

```json
{
  "$defs": {
    "DreamApplyInput": {
      "properties": {
        "dream_id": {
          "description": "The id of a completed dream.",
          "title": "Dream Id",
          "type": "string"
        },
        "only_non_destructive": {
          "default": false,
          "description": "Apply only normalize_date / insert_insight / update_field.",
          "title": "Only Non Destructive",
          "type": "boolean"
        }
      },
      "required": [
        "dream_id"
      ],
      "title": "DreamApplyInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/DreamApplyInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_dream_applyArguments",
  "type": "object"
}
```

## `memgentic_dream_list`

**List Dream Runs** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

List recent dream runs, optionally filtered by project or status.

**Input schema:**

```json
{
  "$defs": {
    "DreamListInput": {
      "properties": {
        "limit": {
          "default": 20,
          "maximum": 200,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by project.",
          "title": "Project"
        },
        "status": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by lifecycle status.",
          "title": "Status"
        }
      },
      "title": "DreamListInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/DreamListInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_dream_listArguments",
  "type": "object"
}
```

## `memgentic_dream_run`

**Run Auto-Dream** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=False` — `openWorldHint=False`

Run an auto-dream consolidation cycle.

Reads recent session transcripts plus the live memory store, and proposes
a list of patches (merge/supersede/archive_stale/normalize_date/
insert_insight/update_field). Live memories are NOT mutated — patches are
persisted with status ``proposed`` and reviewable via
``memgentic_dream_status``.

When ``auto_apply=True``, non-destructive patches are applied immediately;
destructive patches always require explicit ``memgentic_dream_apply``.

**Input schema:**

```json
{
  "$defs": {
    "DreamRunInput": {
      "properties": {
        "auto_apply": {
          "default": false,
          "description": "Auto-apply NON-destructive patches (normalize_date, insert_insight, update_field). Destructive patches always require explicit memgentic_dream_apply.",
          "title": "Auto Apply",
          "type": "boolean"
        },
        "consolidate_model": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Override Phase 3 (Consolidate) model for this run only. Same routing rules as signal_model. Recommended local choice: 'qwen3.6:35b-a3b' (MoE, 5/5 JSON-schema reliability).",
          "title": "Consolidate Model"
        },
        "instructions": {
          "default": "",
          "description": "Optional LLM guidance \u2014 supplies extra context to the Consolidate phase.",
          "maxLength": 4096,
          "title": "Instructions",
          "type": "string"
        },
        "limit_sessions": {
          "anyOf": [
            {
              "maximum": 100,
              "minimum": 1,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Max recent sessions to ingest (default: dream_default_session_limit setting).",
          "title": "Limit Sessions"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Project scope. Defaults to the cwd-derived project key. Pass an empty string to dream over ALL projects (not recommended).",
          "title": "Project"
        },
        "signal_model": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Override Phase 2 (Gather Signal) model for this run only. Routing follows the same prefix table as the env var: 'claude-*' -> Anthropic, 'gemini-*' -> Google, 'gpt-*' -> OpenAI-compat, anything else -> Ollama tag (e.g. 'qwen3.6:35b-a3b', 'gemma4:e4b').",
          "title": "Signal Model"
        }
      },
      "title": "DreamRunInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/DreamRunInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_dream_runArguments",
  "type": "object"
}
```

## `memgentic_dream_status`

**Dream Status** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Inspect a dream run and its proposed patches.

**Input schema:**

```json
{
  "$defs": {
    "DreamStatusInput": {
      "properties": {
        "dream_id": {
          "description": "The id returned by memgentic_dream_run.",
          "title": "Dream Id",
          "type": "string"
        }
      },
      "required": [
        "dream_id"
      ],
      "title": "DreamStatusInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/DreamStatusInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_dream_statusArguments",
  "type": "object"
}
```

## `memgentic_expand`

**Expand Memory** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get full content and metadata for a specific memory by ID.

Use after memgentic_recall with detail='index' to drill into specific results.

**Input schema:**

```json
{
  "$defs": {
    "ExpandInput": {
      "additionalProperties": false,
      "description": "Input for expanding a memory by ID.",
      "properties": {
        "memory_id": {
          "description": "Memory ID returned by a previous memgentic_recall call",
          "minLength": 1,
          "title": "Memory Id",
          "type": "string"
        }
      },
      "required": [
        "memory_id"
      ],
      "title": "ExpandInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/ExpandInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_expandArguments",
  "type": "object"
}
```

## `memgentic_export`

`readOnlyHint=True`

Export memories as JSON. Optionally filter by platform.

**Input schema:**

```json
{
  "$defs": {
    "ExportInput": {
      "description": "Input for exporting memories.",
      "properties": {
        "limit": {
          "default": 100,
          "description": "Max memories to export",
          "maximum": 1000,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by platform (optional)",
          "title": "Source"
        }
      },
      "title": "ExportInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/ExportInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_exportArguments",
  "type": "object"
}
```

## `memgentic_forget`

`readOnlyHint=False` — `destructiveHint=True` — `idempotentHint=True`

Archive (soft-delete) a memory by ID. The memory is not permanently deleted.

**Input schema:**

```json
{
  "$defs": {
    "ForgetInput": {
      "description": "Input for archiving a memory.",
      "properties": {
        "memory_id": {
          "description": "ID of the memory to archive/forget",
          "title": "Memory Id",
          "type": "string"
        }
      },
      "required": [
        "memory_id"
      ],
      "title": "ForgetInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/ForgetInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_forgetArguments",
  "type": "object"
}
```

## `memgentic_graph_add`

**Graph Add** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Add a user-accepted triple to the Chronograph.

**Input schema:**

```json
{
  "$defs": {
    "GraphAddInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_graph_add`.",
      "properties": {
        "confidence": {
          "default": 1.0,
          "maximum": 1.0,
          "minimum": 0.0,
          "title": "Confidence",
          "type": "number"
        },
        "object": {
          "minLength": 1,
          "title": "Object",
          "type": "string"
        },
        "predicate": {
          "minLength": 1,
          "title": "Predicate",
          "type": "string"
        },
        "source_memory_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Source Memory Id"
        },
        "subject": {
          "minLength": 1,
          "title": "Subject",
          "type": "string"
        },
        "valid_from": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "ISO date when the fact began",
          "title": "Valid From"
        }
      },
      "required": [
        "subject",
        "predicate",
        "object"
      ],
      "title": "GraphAddInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/GraphAddInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_graph_add_toolArguments",
  "type": "object"
}
```

## `memgentic_graph_invalidate`

**Graph Invalidate** — `readOnlyHint=False` — `destructiveHint=True` — `idempotentHint=True` — `openWorldHint=False`

Close the validity window for a matching open triple.

**Input schema:**

```json
{
  "$defs": {
    "GraphInvalidateInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_graph_invalidate`.",
      "properties": {
        "ended": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Optional ISO date when the fact stopped being true. Defaults to today.",
          "title": "Ended"
        },
        "object": {
          "minLength": 1,
          "title": "Object",
          "type": "string"
        },
        "predicate": {
          "minLength": 1,
          "title": "Predicate",
          "type": "string"
        },
        "subject": {
          "minLength": 1,
          "title": "Subject",
          "type": "string"
        }
      },
      "required": [
        "subject",
        "predicate",
        "object"
      ],
      "title": "GraphInvalidateInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/GraphInvalidateInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_graph_invalidate_toolArguments",
  "type": "object"
}
```

## `memgentic_graph_query`

**Graph Query** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return currently-valid (or historical) triples touching an entity.

**Input schema:**

```json
{
  "$defs": {
    "GraphQueryInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_graph_query`.",
      "properties": {
        "as_of": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Optional ISO 8601 date (YYYY-MM-DD). Defaults to today.",
          "title": "As Of"
        },
        "direction": {
          "default": "both",
          "enum": [
            "subject",
            "object",
            "both"
          ],
          "title": "Direction",
          "type": "string"
        },
        "entity": {
          "description": "Entity name to query (matches subject and/or object).",
          "minLength": 1,
          "title": "Entity",
          "type": "string"
        },
        "status": {
          "default": "accepted",
          "description": "Triple status filter. 'accepted' (default) hides proposed rows until a user validates them via the dashboard.",
          "enum": [
            "proposed",
            "accepted",
            "rejected",
            "edited",
            "any"
          ],
          "title": "Status",
          "type": "string"
        }
      },
      "required": [
        "entity"
      ],
      "title": "GraphQueryInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/GraphQueryInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_graph_query_toolArguments",
  "type": "object"
}
```

## `memgentic_graph_stats`

**Graph Stats** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return counts for the Chronograph (entities / triples / status).

_No input parameters._

## `memgentic_graph_timeline`

**Graph Timeline** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return triples in chronological order for an entity (or all).

**Input schema:**

```json
{
  "$defs": {
    "GraphTimelineInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_graph_timeline`.",
      "properties": {
        "entity": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter to triples about this entity",
          "title": "Entity"
        },
        "limit": {
          "default": 100,
          "maximum": 500,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "status": {
          "default": "accepted",
          "enum": [
            "proposed",
            "accepted",
            "rejected",
            "edited",
            "any"
          ],
          "title": "Status",
          "type": "string"
        }
      },
      "title": "GraphTimelineInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/GraphTimelineInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_graph_timeline_toolArguments",
  "type": "object"
}
```

## `memgentic_guard_check`

**Guard Self-Check** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Self-check the current diff against the repo's architectural rules.

Lets a coding agent verify its own changes against ``decisions.yaml``
BEFORE declaring a task done — the same deterministic checks the
``memgentic guard`` CLI and the pre-commit hook run. Use it as the final
step of any code change: a non-empty ``violations`` list means the diff
breaks a documented rule and must be fixed before completing the task.

The rules are loaded from ``rules_path`` if given, otherwise from
``<repo>/decisions.yaml``. With ``staged=True`` it inspects the git index
(what's about to be committed); otherwise it diffs the working branch
against ``base`` (defaults to 'main').

Returns:
    ``{passed, violation_count, violations: [{rule_id, message, file,
    line, snippet}], repo, rules_path}``. When no rules file exists,
    returns ``{passed: True, violation_count: 0, violations: [],
    message: "..."}`` rather than an error — a repo without rules simply
    has nothing to enforce.

**Input schema:**

```json
{
  "$defs": {
    "GuardCheckInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_guard_check`.",
      "properties": {
        "base": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Base ref to diff the working branch against (e.g. 'origin/main'). Defaults to 'main' when unset. Ignored when staged=True.",
          "title": "Base"
        },
        "repo": {
          "default": ".",
          "description": "Path to the git repository to check (defaults to the cwd).",
          "title": "Repo",
          "type": "string"
        },
        "rules_path": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Explicit path to a decisions.yaml. Defaults to <repo>/decisions.yaml.",
          "title": "Rules Path"
        },
        "staged": {
          "default": false,
          "description": "Check the staged diff (git index) instead of branch-vs-base.",
          "title": "Staged",
          "type": "boolean"
        }
      },
      "title": "GuardCheckInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/GuardCheckInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_guard_checkArguments",
  "type": "object"
}
```

## `memgentic_handoff`

**Cross-Tool Handoff** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get a source-backed continuation brief from the latest AI-tool sessions.

This is the cross-tool resume surface: Codex, Claude Code, Gemini CLI, and
other MCP clients can call it at startup to understand what the user was
just doing in another tool and continue without making them restate the
project state.

**Input schema:**

```json
{
  "$defs": {
    "HandoffInput": {
      "additionalProperties": false,
      "description": "Input for cross-tool continuation handoff.",
      "properties": {
        "current_source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "The tool asking for the handoff, e.g. 'codex_cli' or 'claude_code'.",
          "title": "Current Source"
        },
        "include_current_source": {
          "default": true,
          "description": "Whether to include sessions from the current source tool.",
          "title": "Include Current Source",
          "type": "boolean"
        },
        "limit_sessions": {
          "default": 3,
          "description": "How many recent source sessions to include.",
          "maximum": 10,
          "minimum": 1,
          "title": "Limit Sessions",
          "type": "integer"
        },
        "memories_per_session": {
          "default": 5,
          "description": "How many recent memories/exchanges to show per source session.",
          "maximum": 10,
          "minimum": 1,
          "title": "Memories Per Session",
          "type": "integer"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter handoff bundles to a single project. Pass 'auto' to scope to the MCP subprocess cwd.",
          "title": "Project"
        },
        "since_hours": {
          "default": 72,
          "description": "Lookback window for candidate source sessions.",
          "maximum": 720,
          "minimum": 1,
          "title": "Since Hours",
          "type": "integer"
        },
        "source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Only show sessions from this source platform.",
          "title": "Source"
        }
      },
      "title": "HandoffInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/HandoffInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_handoffArguments",
  "type": "object"
}
```

## `memgentic_inventory`

**Memory Inventory** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return exact inventory for what is stored in Memgentic.

Use ``detail='summary'`` for counts and a small sample, or
``detail='manifest'`` for a paginated list of exact memory IDs and source
metadata. This is designed to make memory transparent and auditable.

**Input schema:**

```json
{
  "$defs": {
    "InventoryInput": {
      "additionalProperties": false,
      "description": "Input for exact memory-store inventory.",
      "properties": {
        "content_type": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by memory content type.",
          "title": "Content Type"
        },
        "detail": {
          "default": "summary",
          "description": "'summary' returns counts and samples; 'manifest' returns exact memory IDs.",
          "enum": [
            "summary",
            "manifest"
          ],
          "title": "Detail",
          "type": "string"
        },
        "limit": {
          "default": 50,
          "maximum": 200,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "offset": {
          "default": 0,
          "minimum": 0,
          "title": "Offset",
          "type": "integer"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter inventory by project key. Pass 'auto' for current cwd.",
          "title": "Project"
        },
        "source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by platform.",
          "title": "Source"
        }
      },
      "title": "InventoryInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/InventoryInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_inventoryArguments",
  "type": "object"
}
```

## `memgentic_overview`

**Memory Overview** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return a one-shot overview of the memory store.

Aggregates counts per source, the largest topics, storage footprint, and
the active capture profile. Intended as a cheap, single-call replacement
for combining ``memgentic_stats`` + ``memgentic_sources`` + watcher
status on the client side.

Returns:
    ``{total_memories, collections, sources, top_topics, storage_mb,
    capture_profile_default, watchers_active}``.

**Input schema:**

```json
{
  "$defs": {
    "OverviewInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_overview` (all fields optional).",
      "properties": {
        "top_topics_limit": {
          "default": 10,
          "description": "Number of top topics to return, ranked by memory count.",
          "maximum": 100,
          "minimum": 1,
          "title": "Top Topics Limit",
          "type": "integer"
        }
      },
      "title": "OverviewInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/OverviewInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_overviewArguments",
  "type": "object"
}
```

## `memgentic_persona_get`

**Get Persona** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Return the current persona card as JSON.

Falls back to a safe default when ``~/.memgentic/persona.yaml`` is
missing. The T0 Recall Tier calls this at session start.

Returns:
    str: JSON representation of ``{identity, people, projects, preferences, metadata}``.

_No input parameters._

## `memgentic_persona_update`

**Update Persona** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Update a single field on the persona via a dotted path.

Validates the full persona after the write; invalid updates are
rejected without touching disk.

Args:
    params (PersonaUpdateInput):
        - field (str): dotted path, e.g. 'identity.name'
        - value: new value (scalar or list of strings)

Returns:
    str: JSON of the updated persona, or an error message.

**Input schema:**

```json
{
  "$defs": {
    "PersonaUpdateInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_persona_update`.",
      "properties": {
        "field": {
          "description": "Dotted path, e.g. 'identity.name' or 'metadata.workspace_inherit'",
          "minLength": 1,
          "title": "Field",
          "type": "string"
        },
        "value": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "integer"
            },
            {
              "type": "number"
            },
            {
              "type": "boolean"
            },
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "description": "New value. Scalars and string lists are accepted.",
          "title": "Value"
        }
      },
      "required": [
        "field",
        "value"
      ],
      "title": "PersonaUpdateInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/PersonaUpdateInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_persona_updateArguments",
  "type": "object"
}
```

## `memgentic_pin`

**Pin/Unpin Memory** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Pin or unpin a memory for quick access.

Pinned memories appear in the pinned list and are easier to find.

Args:
    params (PinInput): Parameters:
        - memory_id (str): ID of the memory
        - unpin (bool): If true, unpin instead of pin (default false)

Returns:
    str: Confirmation message.

**Input schema:**

```json
{
  "$defs": {
    "PinInput": {
      "additionalProperties": false,
      "description": "Input for pinning/unpinning a memory.",
      "properties": {
        "memory_id": {
          "description": "ID of the memory to pin or unpin",
          "title": "Memory Id",
          "type": "string"
        },
        "unpin": {
          "default": false,
          "description": "If true, unpin instead of pin",
          "title": "Unpin",
          "type": "boolean"
        }
      },
      "required": [
        "memory_id"
      ],
      "title": "PinInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/PinInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_pinArguments",
  "type": "object"
}
```

## `memgentic_projects`

**List Memory Projects** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

List the projects that contributed memories and how many from each.

A "project" is the friendly key derived from the originating working
directory of each AI tool (Claude Code's ``cwd``, Codex's
``session_meta``, etc.). Memories captured outside any known project —
for instance manual ``memgentic_remember`` calls — are reported under
the ``"(unknown)"`` bucket.

_No input parameters._

## `memgentic_recall`

**Recall from Memory** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Search your AI memory using semantic similarity.

Finds relevant memories across all your AI conversations, with optional
source-level filtering. Respects session configuration set via
memgentic_configure_session.

Args:
    params (RecallInput): Search parameters:
        - query (str): What to search for
        - sources (list[str]): Only these platforms (overrides session config)
        - exclude_sources (list[str]): Exclude these platforms
        - content_types (list[str]): Filter by type (decision, code_snippet, etc.)
        - limit (int): Max results (default 10)

Returns:
    str: Markdown-formatted list of relevant memories with source metadata.

Examples:
    - "React performance optimization" → finds related discussions
    - query="FastAPI architecture", sources=["claude_code"] → only Claude Code
    - query="what did we decide", content_types=["decision"] → decisions only

**Input schema:**

```json
{
  "$defs": {
    "RecallInput": {
      "additionalProperties": false,
      "description": "Input for semantic memory recall with source filtering.",
      "properties": {
        "content_types": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by content type: decision, code_snippet, fact, preference, learning, action_item, conversation_summary",
          "title": "Content Types"
        },
        "detail": {
          "default": "preview",
          "description": "Detail level: 'index' (~50 tok/result, ID+type+date+50char), 'preview' (~200 tok/result, 300char content, default), 'full' (~500+ tok/result, complete content + metadata)",
          "enum": [
            "index",
            "preview",
            "full"
          ],
          "title": "Detail",
          "type": "string"
        },
        "exclude_projects": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Exclude memories from these projects.",
          "title": "Exclude Projects"
        },
        "exclude_sources": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Exclude memories from these platforms (e.g., ['codex_cli'])",
          "title": "Exclude Sources"
        },
        "limit": {
          "default": 10,
          "description": "Maximum number of results (1-50)",
          "maximum": 50,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Friendly project key (e.g. 'memgentic-public-export'). Pass 'auto' to use the current working directory of the MCP subprocess. None = use session defaults.",
          "title": "Project"
        },
        "projects": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Multiple project keys. Pass alongside or instead of `project` to recall across several projects at once.",
          "title": "Projects"
        },
        "query": {
          "description": "What to search for in memory (semantic search)",
          "maxLength": 1000,
          "minLength": 2,
          "title": "Query",
          "type": "string"
        },
        "sources": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Only include memories from these platforms (e.g., ['claude_code', 'chatgpt']). None = use session defaults.",
          "title": "Sources"
        }
      },
      "required": [
        "query"
      ],
      "title": "RecallInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/RecallInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_recallArguments",
  "type": "object"
}
```

## `memgentic_recent`

**Recent Memories** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get the most recent memories, optionally filtered by source or type.

Args:
    params (RecentInput): Parameters:
        - limit (int): How many recent memories (default 10)
        - source (str): Filter by platform (e.g., 'claude_code')
        - content_type (str): Filter by type (e.g., 'decision')

Returns:
    str: Markdown list of recent memories.

**Input schema:**

```json
{
  "$defs": {
    "RecentInput": {
      "additionalProperties": false,
      "description": "Input for retrieving recent memories.",
      "properties": {
        "content_type": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by content type",
          "title": "Content Type"
        },
        "limit": {
          "default": 10,
          "description": "Number of recent memories",
          "maximum": 50,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "project": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by project key. Pass 'auto' to use the MCP subprocess cwd.",
          "title": "Project"
        },
        "source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Filter by platform",
          "title": "Source"
        }
      },
      "title": "RecentInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/RecentInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_recentArguments",
  "type": "object"
}
```

## `memgentic_refresh`

**Refresh Cached Settings** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Re-hydrate runtime-mutable settings after an external write.

Dashboard/CLI changes to ``runtime_settings`` (default capture profile,
etc.) aren't seen by a running MCP server because the values are read
once at startup. This tool bumps the cache by re-reading them — no store
reopen, so it's safe to call while other tools are in flight.

Returns:
    ``{refreshed: True, db_path, reopened_at}`` on success.

_No input parameters._

## `memgentic_remember`

**Remember Something** — `readOnlyHint=False` — `destructiveHint=False` — `idempotentHint=False` — `openWorldHint=False`

Store a new memory in Memgentic.

Saves a piece of knowledge with full source metadata so it can be
recalled later from any AI tool.

Args:
    params (RememberInput): Memory to store:
        - content (str): The knowledge to remember
        - content_type (str): Type (fact, decision, code_snippet, etc.)
        - topics (list[str]): Tags for this memory
        - entities (list[str]): People/projects mentioned
        - source (str): Source platform

Returns:
    str: Confirmation with memory ID.

**Input schema:**

```json
{
  "$defs": {
    "RememberInput": {
      "additionalProperties": false,
      "description": "Input for storing a new memory.",
      "properties": {
        "capture_profile": {
          "anyOf": [
            {
              "enum": [
                "raw",
                "enriched",
                "dual"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Optional capture profile override: 'raw' stores verbatim (no LLM), 'enriched' runs the full intelligence pipeline (default), 'dual' writes both rows paired via dual_sibling_id.",
          "title": "Capture Profile"
        },
        "content": {
          "description": "The knowledge/fact/decision to remember",
          "maxLength": 10000,
          "minLength": 3,
          "title": "Content",
          "type": "string"
        },
        "content_type": {
          "default": "fact",
          "description": "Type: fact, decision, code_snippet, preference, learning, action_item",
          "title": "Content Type",
          "type": "string"
        },
        "entities": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "People/projects/technologies mentioned",
          "title": "Entities"
        },
        "source": {
          "default": "unknown",
          "description": "Source platform (e.g., 'claude_code', 'chatgpt'). Auto-detected.",
          "title": "Source",
          "type": "string"
        },
        "topics": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Tags/topics for this memory (e.g., ['python', 'architecture'])",
          "title": "Topics"
        }
      },
      "required": [
        "content"
      ],
      "title": "RememberInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/RememberInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_rememberArguments",
  "type": "object"
}
```

## `memgentic_search`

**Keyword Search Memory** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Full-text keyword search across all memories.

Unlike `memgentic_recall` (semantic), this does exact keyword matching
using SQLite FTS5. Useful for finding specific terms or code.

Args:
    params (SearchInput): Search parameters:
        - query (str): Keywords to search for
        - limit (int): Max results

Returns:
    str: Markdown-formatted matching memories.

**Input schema:**

```json
{
  "$defs": {
    "SearchInput": {
      "additionalProperties": false,
      "description": "Input for full-text keyword search.",
      "properties": {
        "limit": {
          "default": 10,
          "maximum": 50,
          "minimum": 1,
          "title": "Limit",
          "type": "integer"
        },
        "query": {
          "description": "Keywords to search for",
          "minLength": 2,
          "title": "Query",
          "type": "string"
        }
      },
      "required": [
        "query"
      ],
      "title": "SearchInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/SearchInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_searchArguments",
  "type": "object"
}
```

## `memgentic_skill`

**Get Skill** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get a specific skill's full content by name.

Returns the complete SKILL.md content and lists any supporting files.

Args:
    params (SkillInput): Parameters:
        - name (str): Name of the skill to retrieve

Returns:
    str: Full skill content in markdown format.

**Input schema:**

```json
{
  "$defs": {
    "SkillInput": {
      "additionalProperties": false,
      "description": "Input for retrieving a single skill by name.",
      "properties": {
        "name": {
          "description": "Name of the skill to retrieve",
          "minLength": 1,
          "title": "Name",
          "type": "string"
        }
      },
      "required": [
        "name"
      ],
      "title": "SkillInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/SkillInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_skill_toolArguments",
  "type": "object"
}
```

## `memgentic_skills`

**List Skills** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

List all available skills with their names and descriptions.

Returns a compact list of skill names and descriptions for discovery.

Returns:
    str: Markdown list of available skills.

_No input parameters._

## `memgentic_sources`

**List Memory Sources** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

List all source platforms and their memory counts.

Shows which AI tools have contributed memories and how many from each.

Returns:
    str: Markdown table of sources and counts.

_No input parameters._

## `memgentic_stats`

**Memory Statistics** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Get comprehensive memory statistics.

Returns:
    str: Stats including total memories, per-source counts,
         vector store info, and current session config.

_No input parameters._

## `memgentic_tier_recall`

**Recall Tier** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Render a single Recall Tier explicitly (T0-T4).

Cleaner entry-point than ``memgentic_briefing`` when the agent
already knows which tier it wants. Same context + scoping knobs.

**Input schema:**

```json
{
  "$defs": {
    "TierRecallInput": {
      "description": "Input for ``memgentic_tier_recall`` \u2014 explicit Recall Tier call.",
      "properties": {
        "collection": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Collection"
        },
        "entity": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Entity"
        },
        "max_tokens": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Max Tokens"
        },
        "model_context": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Model Context"
        },
        "query": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Query"
        },
        "tier": {
          "description": "Which tier to render.",
          "enum": [
            "T0",
            "T1",
            "T2",
            "T3",
            "T4"
          ],
          "title": "Tier",
          "type": "string"
        },
        "topic": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Topic"
        }
      },
      "required": [
        "tier"
      ],
      "title": "TierRecallInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/TierRecallInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_tier_recallArguments",
  "type": "object"
}
```

## `memgentic_watchers_status`

**Watchers Status** — `readOnlyHint=True` — `destructiveHint=False` — `idempotentHint=True` — `openWorldHint=False`

Report cross-tool watcher state (capture mechanism + recent activity).

Mirrors the REST ``GET /api/v1/watchers`` surface so agents don't need
an HTTP round-trip to decide which tool's capture is still live.

Returns:
    ``{watchers: [{tool, mechanism, installed, enabled, installed_at,
    last_error, last_error_at, captured_count_today, captured_count_total,
    last_captured_at}]}``. ``captured_count_today`` is the number of
    memories ingested since UTC midnight for that tool (parsed from
    watcher_logs). ``captured_count_total`` is the lifetime total.
    When ``include_disabled=False`` (default True), only installed *and*
    enabled rows are returned — both gates match the field name.

**Input schema:**

```json
{
  "$defs": {
    "WatchersStatusInput": {
      "additionalProperties": false,
      "description": "Input for :func:`memgentic_watchers_status`.",
      "properties": {
        "include_disabled": {
          "default": true,
          "description": "If False, only currently-installed + enabled watchers are returned.",
          "title": "Include Disabled",
          "type": "boolean"
        }
      },
      "title": "WatchersStatusInput",
      "type": "object"
    }
  },
  "properties": {
    "params": {
      "$ref": "#/$defs/WatchersStatusInput"
    }
  },
  "required": [
    "params"
  ],
  "title": "memgentic_watchers_statusArguments",
  "type": "object"
}
```
