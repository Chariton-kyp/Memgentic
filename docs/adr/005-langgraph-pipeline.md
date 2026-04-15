# ADR-005: LangGraph for Intelligence Pipeline

## Status

Accepted (2026-03-22)

## Context

Memgentic's intelligence pipeline performs optional LLM-powered processing on ingested conversations: classification (content type, confidence), entity/topic extraction, and summarization. Key challenges:

- The LLM is optional — the pipeline must work without an API key, skipping LLM steps gracefully.
- Processing steps have dependencies (classification before summarization) but some can run in parallel.
- Error handling must be granular — a failed summarization should not prevent classification results from being used.
- The pipeline should be composable and easy to extend with new processing nodes.

We considered plain async functions, a custom DAG runner, and LangGraph.

## Decision

Use **LangGraph** for the intelligence processing pipeline.

- **Conditional routing**: Nodes check whether the LLM client is available before execution. If no API key is configured, LLM nodes are skipped entirely — the pipeline degrades gracefully to heuristic-only processing.
- **State management**: LangGraph's typed state dict passes accumulated results (classified chunks, extracted entities, summary) between nodes without global mutable state.
- **Composable nodes**: Each processing step (classify, extract, summarize) is an independent node. New capabilities (e.g., sentiment analysis) can be added as nodes without restructuring the graph.
- **LangChain ecosystem**: Integrates natively with `langchain-google-genai` and `langchain-anthropic` for LLM provider switching.

## Consequences

- **Positive**: Clean conditional logic for optional LLM, easy to add processing steps, built-in state management, ecosystem compatibility.
- **Negative**: Adds `langgraph` and `langchain-core` as dependencies. Slight learning curve for graph-based pipeline thinking. Overhead for simple pipelines.
- **Mitigated**: LangGraph is lightweight (~50KB). The intelligence graph is only invoked when an LLM client is available. Dependencies are already required for LLM provider integration.
