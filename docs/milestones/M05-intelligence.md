# M5: Intelligence Layer

> LLM-powered processing for smarter, more useful memories.

**Prerequisites:** M2 (Production Core)
**Estimated complexity:** High
**Can run in parallel with:** M3 (REST API), M4 (Multi-Source)
**Exit criteria:** LLM processing pipeline working, knowledge graph populated, hybrid search returning better results.

---

## LangChain Ecosystem Strategy

### What We Use and Why

| Package | Version | Role in Memgentic | Why |
|---------|---------|--------------|-----|
| `langchain-core` | >=1.2 (latest 1.2.22) | LLM abstraction layer | Lightweight core — `ChatModel`, `with_structured_output()`, prompt templates. MIT licensed, minimal deps. |
| `langchain-google-genai` | >=4.0 (latest 4.2.1) | Gemini provider | Gemini 2.0 Flash Lite for cheap processing ($0.075/1M tokens) |
| `langchain-anthropic` | >=1.0 (latest 1.4.0) | Claude provider | Premium processing or fallback. Easy swap via same `ChatModel` interface. |
| `langgraph` | >=1.1 (latest 1.1.3) | Pipeline orchestration | StateGraph for the intelligence pipeline. Gives us: state management, error recovery, branching, future human-in-the-loop. |
| `google-genai` | >=1.50 (latest 1.68.0) | Direct API access | For embedding calls and simple generation where LangChain abstraction is unnecessary |

### What We Don't Use

| Package | Why Not |
|---------|---------|
| `langchain` (full package) | Heavy — pulls in dozens of unused dependencies (chains, agents, retrievers we don't need). We use `langchain-core` + providers directly. |
| `deepagents` (0.4.12) | Built on LangGraph for autonomous coding/research agents. Memgentic is a **memory system**, not an autonomous agent. DeepAgents would only be relevant for M11 Phase 11.8 (AI Knowledge Synthesis) if we build an agent that autonomously explores and synthesizes from the memory store. Revisit then. |

### Architecture: LangGraph Processing Pipeline

```
Conversation Chunks (from adapter)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph StateGraph                    │
│                                                       │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ Classify  │──▶│ Extract  │──▶│  Summarize   │    │
│  │ (LLM)    │   │ (LLM)    │   │  (LLM)       │    │
│  └──────────┘   └──────────┘   └──────┬───────┘    │
│                                         │            │
│  ┌──────────────────────────────────────┘            │
│  │                                                    │
│  ▼                                                    │
│  ┌──────────────┐   ┌─────────────────┐             │
│  │ Contradiction │──▶│ Store + Graph   │             │
│  │ Check (LLM)  │   │ (SQLite+Qdrant  │             │
│  │              │   │  +NetworkX)     │             │
│  └──────────────┘   └─────────────────┘             │
│                                                       │
│  State: IntelligenceState (TypedDict)                │
│  - chunks, classified_chunks, entities, topics       │
│  - summary, contradictions, errors                    │
│                                                       │
│  Fallback: If no API key → skip LLM nodes,           │
│  use heuristic classify + keyword extract             │
└─────────────────────────────────────────────────────┘
```

Each node in the graph:
- Receives the full pipeline state
- Can access the LLM client (Gemini or Claude via langchain-core)
- Uses `with_structured_output()` for type-safe extraction
- Errors are caught and recorded in state (pipeline doesn't crash)
- LangGraph handles state threading between nodes automatically

---

## Phase 5.1: LangChain-Core + LangGraph Intelligence Foundation

**Goal:** Set up the LLM processing infrastructure using langchain-core for provider abstraction and LangGraph for pipeline orchestration.

### Rationale

- `langchain-core` (already in deps from M1) gives provider-agnostic LLM interfaces
- `langchain-google-genai` connects to Gemini Flash Lite (cheap: $0.075/1M tokens)
- `langchain-anthropic` connects to Claude (premium fallback)
- `langgraph` orchestrates the processing pipeline as a stateful graph with error recovery
- `google-genai` is available for direct API calls where LangChain abstraction isn't needed

### Tasks

1. **Create `memgentic/memgentic/processing/llm.py`:**
   ```python
   """LLM client for intelligence features — multi-provider via LangChain-core."""

   from langchain_core.language_models import BaseChatModel
   from langchain_google_genai import ChatGoogleGenerativeAI
   from langchain_anthropic import ChatAnthropic
   from pydantic import BaseModel

   class LLMClient:
       def __init__(self, settings):
           self._settings = settings
           self._model = self._create_model()

       def _create_model(self) -> BaseChatModel:
           """Create LLM based on config — Gemini (default) or Claude."""
           if self._settings.google_api_key:
               return ChatGoogleGenerativeAI(
                   model=self._settings.summarization_model,
                   google_api_key=self._settings.google_api_key,
               )
           # Fallback: could add Claude or other providers
           raise ValueError("No LLM API key configured")

       async def generate_structured(
           self, prompt: str, response_schema: type[BaseModel]
       ) -> BaseModel:
           """Generate structured output using LangChain's with_structured_output."""
           structured_model = self._model.with_structured_output(response_schema)
           return await structured_model.ainvoke(prompt)
   ```

2. **Create the LangGraph intelligence pipeline skeleton:**
   ```python
   # memgentic/memgentic/processing/intelligence.py
   from langgraph.graph import StateGraph, START, END

   class IntelligenceState(TypedDict):
       chunks: list[ConversationChunk]
       classified_chunks: list[ConversationChunk]
       entities: list[str]
       topics: list[str]
       summary: str
       contradictions: list[dict]

   def build_intelligence_graph(llm_client: LLMClient) -> CompiledGraph:
       graph = StateGraph(IntelligenceState)
       graph.add_node("classify", classify_node)
       graph.add_node("extract", extract_node)
       graph.add_node("summarize", summarize_node)
       graph.add_node("check_contradictions", contradiction_node)
       graph.add_edge(START, "classify")
       graph.add_edge("classify", "extract")
       graph.add_edge("extract", "summarize")
       graph.add_edge("summarize", "check_contradictions")
       graph.add_edge("check_contradictions", END)
       return graph.compile()
   ```

3. **Make LLM features optional:**
   - If no API key configured, fall back to heuristic methods
   - Log a warning that intelligence features are degraded
   - The pipeline gracefully skips LLM nodes when unavailable

### Files to Create
- `memgentic/memgentic/processing/llm.py`
- `memgentic/memgentic/processing/intelligence.py`

### Acceptance Criteria
- [ ] LLMClient works with Gemini via langchain-google-genai
- [ ] LangGraph pipeline skeleton compiles and runs
- [ ] Structured output works via with_structured_output
- [ ] Graceful fallback when no API key

---

## Phase 5.2: LLM-Powered Summarization

**Goal:** Intelligent per-conversation summaries that capture key knowledge.

### Tasks

1. **Create summarization pipeline in `processing/intelligence.py`:**
   ```python
   class ConversationSummarizer:
       """Generate intelligent summaries from conversation chunks."""

       async def summarize(self, chunks: list[ConversationChunk]) -> str:
           """Summarize a conversation into key knowledge points."""
           prompt = f"""
           Summarize this AI conversation into key knowledge points.
           Focus on: decisions made, code patterns discussed, facts learned,
           preferences stated, and action items identified.

           Conversation:
           {self._format_chunks(chunks)}

           Provide a concise summary (3-5 bullet points) of the most
           important knowledge from this conversation.
           """
           # Use LLMClient for generation
   ```

2. **Integrate into IngestionPipeline:**
   - After chunking, generate a summary for conversations with >2 exchanges
   - Store summary as a `CONVERSATION_SUMMARY` memory
   - Replace the current naive summary (first 5 exchanges preview)

3. **Add configurable summarization:**
   - `MEMGENTIC_ENABLE_LLM_PROCESSING=true/false` in config
   - When disabled, use existing heuristic approach

### Files to Create
- `memgentic/memgentic/processing/intelligence.py`

### Files to Modify
- `memgentic/memgentic/processing/pipeline.py` — integrate summarization
- `memgentic/memgentic/config.py` — add enable_llm_processing flag

### Acceptance Criteria
- [ ] Conversations get intelligent summaries
- [ ] Summaries capture decisions, code, facts, preferences
- [ ] Works without API key (falls back to heuristic)

---

## Phase 5.3: LLM Entity & Topic Extraction

**Goal:** Extract structured entities and topics from conversations using LLM.

### Tasks

1. **Define extraction schema:**
   ```python
   class ExtractionResult(BaseModel):
       topics: list[str]       # e.g., ["fastapi", "authentication", "JWT"]
       entities: list[str]     # e.g., ["React", "PostgreSQL", "John"]
       technologies: list[str] # e.g., ["Python 3.12", "Docker", "Qdrant"]
       projects: list[str]     # e.g., ["Memgentic", "EllinAI", "Deep-Agents"]
       people: list[str]       # e.g., ["Chariton"]
   ```

2. **Create extraction function in `intelligence.py`:**
   - Use structured output to get consistent results
   - Batch process: extract from conversation summary, not individual chunks
   - Merge with heuristic extraction for better coverage

3. **Update pipeline to use LLM extraction when available**

### Acceptance Criteria
- [ ] Entities extracted accurately from conversations
- [ ] Topics are semantic, not just keyword matches
- [ ] Extraction runs only on summaries (cost-efficient)

---

## Phase 5.4: LLM Content Classification

**Goal:** Accurate content type classification using LLM.

### Tasks

1. **Define classification schema:**
   ```python
   class ClassificationResult(BaseModel):
       content_type: ContentType
       confidence: float
       reasoning: str
   ```

2. **Replace heuristic `_classify_content` with LLM classification:**
   - Classify each chunk using the LLM
   - Use few-shot examples in the prompt for accuracy
   - Fall back to heuristic if LLM unavailable

3. **Batch classification for efficiency:**
   - Classify all chunks in a conversation in one LLM call
   - Use structured output with array

### Acceptance Criteria
- [ ] Classification accuracy >90% on test set
- [ ] Falls back to heuristic when LLM unavailable
- [ ] Cost-efficient (batched calls)

---

## Phase 5.5: Knowledge Graph

**Goal:** NetworkX-based knowledge graph of entities and their relationships.

### Tasks

1. **Add `networkx>=3.4` back to dependencies**

2. **Create `memgentic/memgentic/graph/knowledge.py`:**
   ```python
   class KnowledgeGraph:
       """Entity-relationship graph built from memory metadata."""

       def __init__(self, graph_path: Path):
           self._path = graph_path
           self._graph = nx.DiGraph()

       async def add_memory(self, memory: Memory):
           """Add entities and relationships from a memory to the graph."""
           for entity in memory.entities:
               self._graph.add_node(entity, type="entity")
           for topic in memory.topics:
               self._graph.add_node(topic, type="topic")
           # Create edges between entities that co-occur in a memory
           for e1, e2 in combinations(memory.entities, 2):
               self._add_or_strengthen_edge(e1, e2, memory.id)

       async def query_neighbors(self, entity: str, depth: int = 2) -> dict:
           """Get entities related to the given entity."""

       async def get_subgraph(self, entities: list[str]) -> dict:
           """Get the subgraph connecting the given entities."""

       async def save(self):
           """Serialize graph to JSON."""

       async def load(self):
           """Load graph from JSON."""
   ```

3. **Integrate graph into pipeline:**
   - Update graph after each memory ingestion
   - Persist graph to `~/.mneme/data/graph.json`

4. **Add MCP tool `mneme_graph`:**
   ```python
   @mcp.tool(name="mneme_graph")
   async def mneme_graph(entity: str, depth: int = 2) -> str:
       """Explore the knowledge graph around an entity."""
   ```

5. **Add CLI command:**
   ```bash
   mneme graph "Python"  # Show related entities
   ```

### Files to Create
- `memgentic/memgentic/graph/__init__.py`
- `memgentic/memgentic/graph/knowledge.py`
- `memgentic/tests/test_knowledge_graph.py`

### Acceptance Criteria
- [ ] Graph builds from memories automatically
- [ ] Can query neighbors and subgraphs
- [ ] MCP tool and CLI command work
- [ ] Graph persists across restarts

---

## Phase 5.6: Hybrid Search

**Goal:** Combine semantic + keyword + graph search for better retrieval.

### Tasks

1. **Create hybrid search function:**
   ```python
   async def hybrid_search(
       query: str,
       semantic_results: list[dict],
       keyword_results: list[Memory],
       graph_results: list[str],
       weights: tuple[float, float, float] = (0.6, 0.2, 0.2),
   ) -> list[dict]:
       """Merge results from all three search engines with weighted scoring."""
   ```

2. **Integrate into `mneme_recall` MCP tool:**
   - Run all three searches in parallel
   - Merge and re-rank results
   - Return top-k with combined scores

3. **Update search CLI command to use hybrid search**

### Acceptance Criteria
- [ ] Hybrid search combines all three engines
- [ ] Results are demonstrably better than semantic-only
- [ ] Performance acceptable (<2s for typical queries)

---

## Phase 5.7: Contradiction Detection

**Goal:** Detect conflicting facts across different sources or time periods.

### Tasks

1. **When storing a new memory, check for contradictions:**
   - Semantic search for similar existing memories
   - If similarity > 0.85 but content differs meaningfully, flag
   - Use LLM to determine if genuinely contradictory

2. **Resolution strategy:**
   - Newer memory wins (temporal resolution)
   - Mark old memory as `superseded`
   - Link via `supersedes` field

3. **Add MCP notification:**
   - When contradiction detected, include in `mneme_remember` response
   - "Note: This contradicts a previous memory from ChatGPT (2 weeks ago)"

### Acceptance Criteria
- [ ] Contradictions detected on new memory ingestion
- [ ] Older memory marked as superseded
- [ ] User notified of contradictions

---

## Phase 5.8: Cross-Conversation Linking

**Goal:** Connect related discussions across different tools and sessions.

### Tasks

1. **After ingesting a conversation:**
   - Semantic search for related memories from OTHER sessions
   - If similarity > 0.7, create a link in the knowledge graph
   - Track "conversation threads" that span multiple sessions/tools

2. **Add to memory response:**
   - "Related conversations" section showing linked sessions

### Acceptance Criteria
- [ ] Related conversations linked automatically
- [ ] Links visible in MCP recall results
- [ ] Graph shows cross-conversation connections

---

## Phase 5.9: Memory Importance Decay (TTL)

**Goal:** Older, less-accessed memories gradually score lower in search results.

### Tasks

1. **Add `importance_score` field to Memory model:**
   - Starts at 1.0 on creation
   - Decays based on age and access frequency
   - Formula: `importance = base_score * recency_factor * access_factor`
   - `recency_factor = exp(-age_days / half_life)` (configurable half_life, default 90 days)
   - `access_factor = 1 + log(1 + access_count) * 0.1`

2. **Apply importance weighting in search:**
   - Multiply semantic similarity score by importance_score
   - Re-rank results after weighting

3. **Add `MEMGENTIC_MEMORY_HALF_LIFE_DAYS` config** (default 90)

4. **Add `memgentic prune --older-than 365d`** CLI command to archive old, low-importance memories

### Acceptance Criteria
- [ ] Importance score computed for all memories
- [ ] Search results weighted by importance
- [ ] Configurable decay rate
- [ ] Prune command works
