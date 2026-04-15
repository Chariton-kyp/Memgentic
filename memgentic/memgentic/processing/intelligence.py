"""LangGraph intelligence pipeline — classify, extract, summarize conversations."""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from memgentic.processing.llm import LLMClient

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Structured output schemas for LLM calls
# ---------------------------------------------------------------------------


class ClassificationResult(BaseModel):
    """LLM classification of a conversation chunk."""

    content_type: Literal[
        "fact",
        "decision",
        "code_snippet",
        "preference",
        "learning",
        "action_item",
        "conversation_summary",
        "raw_exchange",
    ] = Field(description="The content type of this text")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0", ge=0, le=1)


class ExtractionResult(BaseModel):
    """LLM-extracted entities and topics."""

    topics: list[str] = Field(default_factory=list, description="Technical topics")
    entities: list[str] = Field(default_factory=list, description="Named entities")


class SummaryResult(BaseModel):
    """LLM conversation summary."""

    summary: str = Field(description="Concise summary of the conversation")


class DistillationResult(BaseModel):
    """Atomic facts distilled from a conversation chunk."""

    facts: list[str] = Field(default_factory=list, description="Atomic facts extracted")
    is_valuable: bool = Field(
        default=True, description="Whether this contains knowledge worth remembering"
    )
    value_score: float = Field(default=0.5, ge=0, le=1)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


class IntelligenceState(TypedDict, total=False):
    """State threaded through the LangGraph pipeline."""

    chunks: list[dict]  # Serialized ConversationChunks
    llm_client: Any  # LLMClient (not serializable, so Any)
    # Outputs filled by nodes
    classified_chunks: list[dict]
    all_topics: list[str]
    all_entities: list[str]
    summary: str
    distilled_facts: list[str]
    errors: list[str]


# ---------------------------------------------------------------------------
# Heuristic fallbacks (same logic as existing adapters)
# ---------------------------------------------------------------------------

_CONTENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "decision": [
        "decided",
        "decision",
        "let's go with",
        "we'll use",
        "chose",
        "went with",
        "opted for",
        "agreed on",
        "resolved",
        "finalized",
        "settled on",
        "approved",
        "picked",
        "selected",
        "conclusion",
        "we should use",
    ],
    "code_snippet": [
        "```",
        "def ",
        "class ",
        "function ",
        "import ",
        "const ",
        "let ",
        "var ",
        "return ",
        "=>",
        "async ",
        "fn ",
        "pub ",
        "struct ",
        "#include",
        "package ",
        "from ",
        "export ",
        "require(",
        ".py",
        ".js",
        ".ts",
        "void ",
        "int ",
    ],
    "action_item": [
        "todo",
        "action item",
        "next step",
        "should do",
        "follow up",
        "need to",
        "must do",
        "reminder",
        "don't forget",
        "remember to",
        "assigned to",
        "deadline",
        "by end of",
        "will do",
        "task:",
        "fix:",
        "implement",
    ],
    "preference": [
        "prefer",
        "i like",
        "always use",
        "my preference",
        "rather",
        "instead of",
        "fan of",
        "go-to",
        "default to",
        "tend to",
        "convention",
        "style guide",
        "best practice",
        "i usually",
        "my approach",
    ],
    "learning": [
        "learned",
        "til ",
        "turns out",
        "i discovered",
        "realized",
        "found out",
        "noted that",
        "gotcha",
        "pitfall",
        "caveat",
        "trick is",
        "key insight",
        "important to note",
        "didn't know",
        "aha moment",
    ],
    "fact": [
        "is a ",
        "works by",
        "supports",
        "requires",
        "depends on",
        "compatible with",
        "version",
        "specification",
        "protocol",
        "is built on",
        "was created",
        "is used for",
        "provides",
        "enables",
        "is designed",
    ],
    "conversation_summary": [
        "in summary",
        "to summarize",
        "overall",
        "wrapping up",
        "recap",
        "key takeaways",
        "main points",
        "to conclude",
        "in conclusion",
    ],
}


def _heuristic_classify(text: str) -> tuple[str, float]:
    """Classify text by scoring all content types and picking the highest."""
    lower = text.lower()
    best_type = "raw_exchange"
    best_score = 0

    for ct, keywords in _CONTENT_TYPE_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in lower)
        if matches > 0:
            score = matches
            if score > best_score:
                best_score = score
                best_type = ct

    if best_score == 0:
        return "raw_exchange", 0.5
    confidence = 0.85 if best_score >= 2 else 0.7
    return best_type, confidence


_TECH_KEYWORDS = {
    "python",
    "javascript",
    "typescript",
    "react",
    "nextjs",
    "fastapi",
    "docker",
    "kubernetes",
    "postgres",
    "redis",
    "git",
    "api",
    "rest",
    "graphql",
    "css",
    "html",
    "node",
    "rust",
    "go",
    "java",
    "aws",
    "gcp",
    "azure",
    "terraform",
    "testing",
    "machine learning",
    "ai",
    "llm",
    "embedding",
    "rag",
    "mcp",
    "langchain",
    "langgraph",
    "ollama",
    "openai",
    "anthropic",
    "gemini",
    "qdrant",
    "sqlite",
    "numpy",
    "pandas",
    "django",
    "flask",
    "express",
    "vue",
    "angular",
    "svelte",
    "webpack",
    "vite",
    "nginx",
    "linux",
    "macos",
    "windows",
    "sql",
    "mongodb",
    "firebase",
    "supabase",
    "vercel",
    "netlify",
    "cloudflare",
    "github",
    "gitlab",
    "pytest",
    "jest",
    "playwright",
    "cypress",
    "tailwind",
    "shadcn",
    "pydantic",
    "sqlalchemy",
    "prisma",
    "drizzle",
    "trpc",
    "grpc",
    "websocket",
    "oauth",
    "jwt",
    "s3",
    "lambda",
    "pulumi",
    "celery",
    "rabbitmq",
    "kafka",
    "elasticsearch",
    "chromadb",
    "pinecone",
    "weaviate",
    "streamlit",
    "gradio",
    "huggingface",
    "pytorch",
    "tensorflow",
    "scipy",
    "matplotlib",
    "selenium",
    "scrapy",
    "uvicorn",
    "gunicorn",
    "deno",
    "bun",
}


def _extract_named_entities(text: str) -> list[str]:
    """Extract named entities using regex heuristics (no NLP library needed)."""
    entities: list[str] = []

    # URLs — extract domain names
    for match in re.finditer(r'https?://([^\s<>"\'/?#]+)', text):
        domain = match.group(1)
        if "." in domain:
            entities.append(domain)

    # File paths with extensions
    for match in re.finditer(
        r"\b[\w/\\.-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|sql|sh|go|rs|java|css|html)\b",
        text,
    ):
        entities.append(match.group(0))

    # CamelCase identifiers (FastAPI, LangChain, NextJs, etc.)
    for match in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text):
        entities.append(match.group(0))

    # Capitalized multi-word phrases (proper nouns/project names)
    for match in re.finditer(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b", text):
        entities.append(match.group(0))

    # @-scoped packages (npm-style)
    for match in re.finditer(r"@[\w-]+/[\w-]+", text):
        entities.append(match.group(0))

    # Version strings (Python 3.12, Node 20, v2.0.1)
    for match in re.finditer(r"\b[A-Za-z]+\s+\d+(?:\.\d+)+\b", text):
        entities.append(match.group(0))
    for match in re.finditer(r"\bv\d+(?:\.\d+)+\b", text):
        entities.append(match.group(0))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in entities:
        lower = e.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(e)

    return unique[:15]


def _heuristic_extract(text: str) -> tuple[list[str], list[str]]:
    lower = text.lower()
    topics = [kw for kw in _TECH_KEYWORDS if kw in lower]
    entities = _extract_named_entities(text)
    return topics[:10], entities


# ---------------------------------------------------------------------------
# Pipeline nodes
# ---------------------------------------------------------------------------


async def classify_node(state: IntelligenceState) -> dict:
    """Classify each chunk using LLM or heuristic fallback."""
    llm: LLMClient = state.get("llm_client")  # type: ignore[assignment]
    chunks = list(state.get("chunks", []))
    errors: list[str] = list(state.get("errors", []))

    classify_prompt = (
        "Classify this AI conversation excerpt into exactly one category.\n\n"
        "Categories:\n"
        "- decision: Choices about approach, tools, or architecture\n"
        "- code_snippet: Code blocks, function definitions, configuration\n"
        "- fact: Statements of truth about tools, APIs, or concepts\n"
        "- preference: Personal likes, conventions, or style choices\n"
        "- learning: New discoveries or insights (TIL, realized, turns out)\n"
        "- action_item: Tasks, TODOs, or follow-ups to complete\n"
        "- raw_exchange: General conversation without specific knowledge\n\n"
        "Examples:\n"
        'Text: "We decided to use PostgreSQL instead of MongoDB"\n'
        '-> {"content_type": "decision", "confidence": 0.95}\n\n'
        'Text: "def calculate(items): return sum(i.value for i in items)"\n'
        '-> {"content_type": "code_snippet", "confidence": 0.95}\n\n'
        'Text: "I learned that FastAPI handles async routes natively"\n'
        '-> {"content_type": "learning", "confidence": 0.9}\n\n'
        'Text: "SQLite FTS5 supports BM25 ranking out of the box"\n'
        '-> {"content_type": "fact", "confidence": 0.9}\n\n'
        'Text: "I always prefer dark mode in my editors"\n'
        '-> {"content_type": "preference", "confidence": 0.9}\n\n'
        'Text: "TODO: fix the auth bug in login.py by Friday"\n'
        '-> {"content_type": "action_item", "confidence": 0.95}\n\n'
        'Text: "Hello, how can I help you today?"\n'
        '-> {"content_type": "raw_exchange", "confidence": 0.85}\n\n'
        "Now classify this text:\n"
    )

    for chunk in chunks:
        if llm.available:
            try:
                result = await llm.generate_structured(
                    classify_prompt + chunk["content"][:500],
                    ClassificationResult,
                )
                if isinstance(result, ClassificationResult):
                    chunk["content_type"] = result.content_type
                    chunk["confidence"] = result.confidence
                    continue
            except Exception as e:
                errors.append(f"classify: {e}")

        # Heuristic fallback
        ct, conf = _heuristic_classify(chunk.get("content", ""))
        chunk["content_type"] = ct
        chunk["confidence"] = conf
        logger.debug("intelligence.classify.heuristic", content_type=ct, confidence=conf)

    return {"classified_chunks": chunks, "errors": errors}


async def extract_node(state: IntelligenceState) -> dict:
    """Extract entities and topics using LLM or heuristic."""
    llm: LLMClient = state.get("llm_client")  # type: ignore[assignment]
    classified = state.get("classified_chunks", state.get("chunks", []))
    errors: list[str] = list(state.get("errors", []))

    combined = "\n\n".join(c.get("content", "")[:300] for c in classified[:5])
    all_topics: list[str] = []
    all_entities: list[str] = []

    extract_prompt = (
        "Extract technical topics and named entities from this AI conversation.\n\n"
        "Example:\n"
        'Text: "We migrated from PostgreSQL 14 to 18 and added Qdrant for vector search"\n'
        '-> {"topics": ["postgresql", "qdrant", "vector search"], '
        '"entities": ["PostgreSQL 14", "PostgreSQL 18", "Qdrant"]}\n\n'
        "Now extract from this text:\n"
    )

    if llm.available:
        try:
            result = await llm.generate_structured(
                extract_prompt + combined,
                ExtractionResult,
            )
            if isinstance(result, ExtractionResult):
                all_topics = result.topics
                all_entities = result.entities
        except Exception as e:
            errors.append(f"extract: {e}")

    # Merge with heuristic topics and entities
    h_topics, h_entities = _heuristic_extract(combined)
    for t in h_topics:
        if t not in all_topics:
            all_topics.append(t)
    for e in h_entities:
        if e not in all_entities:
            all_entities.append(e)

    # Log what was extracted
    logger.info(
        "intelligence.extract",
        topics_count=len(all_topics),
        entities_count=len(all_entities),
        llm_used=llm.available,
    )

    return {
        "all_topics": all_topics[:15],
        "all_entities": all_entities[:15],
        "errors": errors,
    }


_DISTILL_FACT_KEYWORDS = {
    "decided",
    "chose",
    "picked",
    "will use",
    "going with",
    "agreed on",
    "learned",
    "discovered",
    "found that",
    "realized",
    "turns out",
    "prefer",
    "convention",
    "always",
    "never",
    "should",
    "must",
    "fixed",
    "bug was",
    "issue was",
    "root cause",
    "solution",
}


def _distill_heuristic(content: str, content_type: str) -> DistillationResult:
    """Extract facts using keyword-based heuristics."""
    sentences = re.split(r"[.!?]+\s+", content)
    facts: list[str] = []
    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 20 or len(s) > 300:
            continue
        lower = s.lower()
        if any(kw in lower for kw in _DISTILL_FACT_KEYWORDS):
            facts.append(s)

    facts = facts[:5]
    is_valuable = len(facts) > 0 or content_type in (
        "decision",
        "learning",
        "preference",
        "bug_fix",
    )
    value_score = min(0.3 + 0.15 * len(facts), 1.0)
    return DistillationResult(facts=facts, is_valuable=is_valuable, value_score=value_score)


async def _distill_with_llm(
    llm_client: LLMClient, content: str, content_type: str
) -> DistillationResult:
    """Use LLM to extract atomic facts."""
    prompt = (
        "Extract 1-5 atomic facts from this conversation that would be useful in a "
        "future conversation. Each fact should be a standalone statement with enough "
        "context to be understood alone.\n\n"
        f"Content type: {content_type}\n"
        f"Content:\n{content[:2000]}\n\n"
        'Return JSON: {"facts": ["fact1", "fact2"], "is_valuable": true, "value_score": 0.8}\n'
        "- facts: list of 1-5 atomic fact strings\n"
        "- is_valuable: false only if content is pure noise/pleasantry\n"
        "- value_score: 0.0 to 1.0 based on usefulness for future recall"
    )
    return await llm_client.generate_structured(prompt, DistillationResult)


async def distill_node(state: IntelligenceState) -> dict:
    """Distill atomic facts from each classified chunk.

    LLM path: ask the LLM for atomic facts + value assessment.
    Heuristic fallback: extract sentences containing decision/learning/preference keywords.
    """
    chunks = state.get("classified_chunks", state.get("chunks", []))
    errors: list[str] = list(state.get("errors", []))
    llm: LLMClient | None = state.get("llm_client")  # type: ignore[assignment]

    distilled: list[str] = []
    for chunk in chunks:
        content = chunk.get("content", "")
        if not content:
            continue
        ctype = chunk.get("content_type", "fact")
        result: DistillationResult | None = None
        if llm is not None and getattr(llm, "available", False):
            try:
                candidate = await _distill_with_llm(llm, content, ctype)
                if isinstance(candidate, DistillationResult):
                    result = candidate
            except Exception as e:
                errors.append(f"distill: {e}")
                result = None
        if result is None:
            result = _distill_heuristic(content, ctype)
        chunk["distillation"] = result.model_dump()
        distilled.extend(result.facts)

    return {
        "classified_chunks": chunks,
        "distilled_facts": distilled,
        "errors": errors,
    }


async def summarize_node(state: IntelligenceState) -> dict:
    """Summarize the conversation using LLM or heuristic."""
    llm: LLMClient = state.get("llm_client")  # type: ignore[assignment]
    chunks = state.get("classified_chunks", state.get("chunks", []))
    errors: list[str] = list(state.get("errors", []))

    if not chunks:
        return {"summary": "", "errors": errors}

    if len(chunks) < 2:
        return {"summary": chunks[0].get("content", "")[:200], "errors": errors}

    if llm.available:
        try:
            combined = "\n\n".join(c.get("content", "")[:500] for c in chunks[:8])
            result = await llm.generate_structured(
                "Summarize this AI conversation into key knowledge points "
                f"(3-5 bullet points):\n\n{combined}",
                SummaryResult,
            )
            if isinstance(result, SummaryResult):
                logger.info("intelligence.summarize.llm", summary_length=len(result.summary))
                return {"summary": result.summary, "errors": errors}
        except Exception as e:
            errors.append(f"summarize: {e}")

    # Heuristic: extractive summarization
    combined_text = " ".join(c.get("content", "") for c in chunks)
    sentences = re.split(r"(?<=[.!?])\s+", combined_text)
    # Filter out very short sentences
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]

    if len(sentences) < 2:
        # Too few sentences, fall back to preview
        previews = [
            c.get("content", "")[:150].strip() for c in chunks[:3] if c.get("content", "").strip()
        ]
        if previews:
            summary = "Key points: " + ". ".join(p.rstrip(".") for p in previews if p) + "."
        else:
            summary = f"Conversation with {len(chunks)} exchanges."
        logger.info(
            "intelligence.summarize.heuristic",
            sentence_count=len(sentences),
            summary_length=len(summary),
        )
        return {"summary": summary, "errors": errors}

    # Score sentences: position weight + keyword density
    scored: list[tuple[float, int, str]] = []
    topic_keywords = set(state.get("all_topics", []))
    for i, sent in enumerate(sentences[:20]):  # Cap at 20 sentences
        position_score = 1.0 / (1 + i * 0.1)  # Earlier = higher
        words = sent.lower().split()
        keyword_hits = sum(1 for w in words if w in topic_keywords) if topic_keywords else 0
        density_score = keyword_hits / max(len(words), 1)
        total_score = position_score + density_score * 2
        scored.append((total_score, i, sent))

    # Pick top 3-5 sentences, maintain original order
    scored.sort(reverse=True)
    top_n = min(5, max(3, len(scored) // 3))
    selected = sorted(scored[:top_n], key=lambda x: x[1])

    summary = "Key points: " + ". ".join(s[2].rstrip(".") for s in selected) + "."
    logger.info(
        "intelligence.summarize.heuristic",
        sentence_count=len(sentences),
        summary_length=len(summary),
    )
    return {"summary": summary, "errors": errors}


# ---------------------------------------------------------------------------
# Build the compiled graph
# ---------------------------------------------------------------------------


def build_intelligence_graph(enable_distillation: bool = True):
    """Build and compile the LangGraph intelligence pipeline.

    Returns a compiled graph that accepts IntelligenceState and runs:
    classify → (distill) → extract → summarize
    """
    graph = StateGraph(IntelligenceState)
    graph.add_node("classify", classify_node)
    graph.add_node("extract", extract_node)
    graph.add_node("summarize", summarize_node)
    graph.add_edge(START, "classify")
    if enable_distillation:
        graph.add_node("distill", distill_node)
        graph.add_edge("classify", "distill")
        graph.add_edge("distill", "extract")
    else:
        graph.add_edge("classify", "extract")
    graph.add_edge("extract", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()
