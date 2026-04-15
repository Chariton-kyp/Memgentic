use pyo3::prelude::*;
use std::collections::HashSet;
use std::sync::LazyLock;

struct ContentTypeKeywords {
    name: &'static str,
    keywords: &'static [&'static str],
}

static CONTENT_TYPE_KEYWORDS: &[ContentTypeKeywords] = &[
    ContentTypeKeywords {
        name: "decision",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "code_snippet",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "action_item",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "preference",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "learning",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "fact",
        keywords: &[
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
    },
    ContentTypeKeywords {
        name: "conversation_summary",
        keywords: &[
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
    },
];

static TECH_KEYWORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
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
    ]
    .into_iter()
    .collect()
});

/// Core classification logic (no GIL needed).
pub fn heuristic_classify_inner(text: &str) -> (String, f64) {
    let lower = text.to_lowercase();
    let mut best_type = "raw_exchange";
    let mut best_score: usize = 0;

    for ct in CONTENT_TYPE_KEYWORDS.iter() {
        let matches = ct.keywords.iter().filter(|kw| lower.contains(**kw)).count();
        if matches > best_score {
            best_score = matches;
            best_type = ct.name;
        }
    }

    if best_score == 0 {
        return ("raw_exchange".to_string(), 0.5);
    }

    let confidence = if best_score >= 2 { 0.85 } else { 0.7 };
    (best_type.to_string(), confidence)
}

/// Classify text by scoring all content types and picking the highest.
/// Returns (content_type, confidence).
#[pyfunction]
pub fn heuristic_classify(text: &str) -> (String, f64) {
    heuristic_classify_inner(text)
}

/// Extract technical topics (keyword match) and named entities (regex) from text.
/// Returns (topics, entities).
#[pyfunction]
pub fn heuristic_extract(text: &str) -> (Vec<String>, Vec<String>) {
    let lower = text.to_lowercase();

    let topics: Vec<String> = TECH_KEYWORDS
        .iter()
        .filter(|kw| lower.contains(**kw))
        .take(10)
        .map(|kw| kw.to_string())
        .collect();

    let entities = super::entities::extract_named_entities_inner(text);

    (topics, entities)
}
