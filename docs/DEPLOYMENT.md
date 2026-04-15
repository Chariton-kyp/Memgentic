# Memgentic Deployment Guide

## Local Development

### Prerequisites

- Python 3.12+
- UV package manager
- Docker (for Ollama + Qdrant)
- Node.js 20+ (for dashboard)

### Quick Start

```bash
# 1. Clone and install
git clone https://github.com/chariton-kyp/memgentic.git
cd memgentic
uv sync --all-extras

# 2. Start infrastructure
make dev    # Docker: Ollama + Qdrant + MCP + API

# 3. Verify
memgentic doctor

# 4. Import existing conversations
memgentic import-existing

# 5. Start dashboard (optional)
cd dashboard && npm install && npm run dev
```

### Environment Configuration

Create `.env` in the project root:

```env
# Embedding
MEMGENTIC_EMBEDDING_MODEL=qwen3-embedding:latest
MEMGENTIC_EMBEDDING_DIMENSIONS=768
MEMGENTIC_OLLAMA_URL=http://localhost:11434

# Storage
MEMGENTIC_SQLITE_PATH=~/.mneme/mneme.db
MEMGENTIC_QDRANT_URL=http://localhost:6333

# API
MEMGENTIC_API_HOST=0.0.0.0
MEMGENTIC_API_PORT=8100
MEMGENTIC_API_KEY=        # Optional, leave empty for local dev

# LLM (optional, for intelligence layer)
GEMINI_API_KEY=       # For Gemini Flash Lite classification
ANTHROPIC_API_KEY=    # For Claude fallback

# Rate Limiting
MEMGENTIC_RATE_LIMIT_DEFAULT=60
MEMGENTIC_RATE_LIMIT_SEARCH=30
MEMGENTIC_RATE_LIMIT_IMPORT=10
```

## Docker Deployment

### Full Stack

```bash
make dev
```

This starts:
- **Ollama** (port 11434) — Embedding model
- **Qdrant** (port 6333) — Vector database
- **Memgentic MCP** (port 8200) — MCP server over HTTP
- **Memgentic API** (port 8100) — REST API

### GPU Support

If you have an NVIDIA GPU:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

The GPU variant auto-detects NVIDIA and uses it for embedding generation.

### Data Persistence

Docker volumes store persistent data:
- `memgentic-data` — SQLite database
- `qdrant-data` — Vector store
- `ollama-data` — Downloaded models

### Health Checks

All services have health checks. Monitor with:

```bash
docker compose ps     # Service status
curl localhost:8100/api/v1/health   # API health
memgentic doctor          # Full diagnostic
```

## Production Deployment

### Recommended Architecture

```
[Reverse Proxy (nginx/Caddy)]
    ├── :443 → Dashboard (Next.js, port 3000)
    ├── :443/api → REST API (FastAPI, port 8100)
    └── :443/mcp → MCP Server (port 8200)

[Backend Services]
    ├── Qdrant (port 6333, internal only)
    ├── Ollama (port 11434, internal only)
    └── SQLite (file-based, no port)
```

### Security Checklist

- [ ] Set `MEMGENTIC_API_KEY` for API authentication
- [ ] Configure CORS origins in API (`MEMGENTIC_CORS_ORIGINS`)
- [ ] Use HTTPS via reverse proxy
- [ ] Restrict Qdrant/Ollama to internal network
- [ ] Set up regular backups: `memgentic backup -o /backups/`
- [ ] Monitor with `GET /api/v1/health`

### Backup & Restore

```bash
# Create backup
memgentic backup -o /path/to/backup.tar.gz

# Restore from backup
mneme restore /path/to/backup.tar.gz

# GDPR export (all user data)
memgentic export --gdpr -o /path/to/export.json
```

## Troubleshooting

### Common Issues

**"Embedding model not found"**
```bash
memgentic doctor          # Check Ollama status
make pull-models      # Pull embedding model
```

**"Cannot connect to Qdrant"**
```bash
docker compose ps     # Check Qdrant is running
curl localhost:6333   # Test connection
```

**"No memories found after import"**
```bash
mneme sources         # Check what was imported
mneme search "test"   # Try a broad search
```

**"API returns 429 Too Many Requests"**
Rate limiting is active. Wait 60 seconds or increase limits in `.env`.
