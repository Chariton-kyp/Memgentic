"""Heuristic intelligence — keyword and regex-based classification, extraction, and summarization.

These functions provide basic intelligence without requiring an LLM or the intelligence extras.
They serve as fallbacks when intelligence extras are not installed.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger()

# Try to use the Rust-native implementation (5-50x faster).
try:
    from memgentic_native.textproc import (
        extract_named_entities as _native_extract_entities,
    )
    from memgentic_native.textproc import (
        heuristic_classify as _native_classify,
    )
    from memgentic_native.textproc import (
        heuristic_extract as _native_extract,
    )
    from memgentic_native.textproc import (
        is_noise as _native_is_noise,
    )

    _USE_NATIVE = True
except ImportError:
    _USE_NATIVE = False


# ---------------------------------------------------------------------------
# Noise detection
# ---------------------------------------------------------------------------

_NOISE_ACKNOWLEDGMENT_PATTERNS = [
    re.compile(
        r"^(sure|ok|okay|yes|no|got it|understood|i see|thanks|thank you)[\s,.!]*"
        r"(thanks|thank you|got it|understood|sure|ok|okay)?[\s,.!]*$",
        re.IGNORECASE,
    ),
    re.compile(r"^(let me|here'?s|i'?ll|i will|i'?m going to)\b", re.IGNORECASE),
    re.compile(r"^(looking at|reading|checking|searching|running|executing)\b", re.IGNORECASE),
    re.compile(
        r"^(the (?:file|code|output|result|error)) (?:shows|says|indicates|contains)\b",
        re.IGNORECASE,
    ),
]

_OUTPUT_LINE_INDICATORS = re.compile(
    r'^\s*(?:at |File "|Traceback|>>>|\$|>|#|[0-9]+:|\s*\w+\.(?:py|js|ts|go|rs):\d+)'
)


def is_noise(text: str) -> bool:
    """Return True if this text is noise (pleasantry, acknowledgment, or tool output dump).

    Uses Rust native implementation when available (5-10x faster).
    """
    if _USE_NATIVE:
        return _native_is_noise(text)
    if not text:
        return True

    stripped = text.strip()
    if len(stripped) < 8:
        return True

    # Short acknowledgments
    if len(stripped) < 100:
        for pattern in _NOISE_ACKNOWLEDGMENT_PATTERNS:
            if pattern.search(stripped):
                return True

    # Tool output dumps: low alphabetic ratio in long text
    if len(stripped) > 200:
        alpha_ratio = sum(c.isalpha() for c in stripped) / len(stripped)
        if alpha_ratio < 0.3:
            return True

    # Stack traces / build logs: most lines start with output indicators
    lines = stripped.split("\n")
    if len(lines) > 5:
        output_lines = sum(1 for line in lines if _OUTPUT_LINE_INDICATORS.match(line))
        if output_lines / len(lines) > 0.6:
            return True

    return False


# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

CONTENT_TYPE_KEYWORDS: dict[str, list[str]] = {
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

TECH_KEYWORDS = {
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


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def heuristic_classify(text: str) -> tuple[str, float]:
    """Classify text by scoring all content types and picking the highest.

    Uses Rust native implementation when available.
    """
    if _USE_NATIVE:
        return _native_classify(text)
    lower = text.lower()
    best_type = "raw_exchange"
    best_score = 0

    for ct, keywords in CONTENT_TYPE_KEYWORDS.items():
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


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------


def extract_named_entities(text: str) -> list[str]:
    """Extract named entities using regex heuristics (no NLP library needed).

    Uses Rust native implementation when available (10-20x faster).
    """
    if _USE_NATIVE:
        return list(_native_extract_entities(text))
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


# ---------------------------------------------------------------------------
# Topic + entity extraction
# ---------------------------------------------------------------------------


def heuristic_extract(text: str) -> tuple[list[str], list[str]]:
    """Extract technical topics (keyword match) and named entities (regex) from text.

    Uses Rust native implementation when available.
    """
    if _USE_NATIVE:
        topics, entities = _native_extract(text)
        return list(topics), list(entities)
    lower = text.lower()
    topics = [kw for kw in TECH_KEYWORDS if kw in lower]
    entities = extract_named_entities(text)
    return topics[:10], entities


# ---------------------------------------------------------------------------
# Extractive summarization
# ---------------------------------------------------------------------------


def heuristic_summarize(
    chunks: list[dict],
    topic_keywords: set[str] | None = None,
) -> str:
    """Produce an extractive summary from conversation chunks.

    Scores sentences by position weight and keyword density, then selects
    the top 3-5 sentences in original order.

    Args:
        chunks: List of dicts, each with a ``"content"`` key.
        topic_keywords: Optional set of topic keywords used to boost
            sentence relevance scoring.

    Returns:
        A summary string beginning with ``"Key points: "``.
    """
    if not chunks:
        return ""

    if len(chunks) < 2:
        return chunks[0].get("content", "")[:200]

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
            "heuristics.summarize",
            sentence_count=len(sentences),
            summary_length=len(summary),
        )
        return summary

    # Score sentences: position weight + keyword density
    scored: list[tuple[float, int, str]] = []
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
        "heuristics.summarize",
        sentence_count=len(sentences),
        summary_length=len(summary),
    )
    return summary
