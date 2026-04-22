# Memgentic MCP Tools

This file is **auto-generated** by ``scripts/generate_mcp_docs.py``. Do not
edit it by hand — CI rejects hand-edits via a drift check. To change a
tool's section, update its docstring, annotations, or Pydantic input model
in ``memgentic/memgentic/mcp/`` and rerun the generator.

Every tool is namespaced ``memgentic_*`` and exposed over the ``mcp[cli]``
transport configured by ``memgentic serve``.

Total tools: **27**

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
    last_error, last_error_at, captured_count, last_captured_at}]}``.
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
