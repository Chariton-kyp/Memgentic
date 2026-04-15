# Memgentic REST API Guide

## Base URL

```
http://localhost:8100/api/v1
```

## Authentication

For protected deployments, set `MEMGENTIC_API_KEY` in your environment. Pass it via header:

```
Authorization: Bearer <your-api-key>
```

Local development doesn't require authentication by default.

## Endpoints

### Health Check

```http
GET /health
```

Returns service status, version, uptime, memory count, and vector store info.

### Memories

#### List Memories (paginated)
```http
GET /memories?offset=0&limit=20&platform=claude_code&content_type=decision
```

Query params: `offset`, `limit`, `platform`, `content_type`, `status`, `from_date`, `to_date`

#### Get Single Memory
```http
GET /memories/{memory_id}
```

#### Create Memory
```http
POST /memories
Content-Type: application/json

{
  "content": "FastAPI supports async out of the box",
  "content_type": "fact",
  "platform": "claude_code",
  "topics": ["python", "fastapi"],
  "entities": ["FastAPI"]
}
```

#### Update Memory
```http
PATCH /memories/{memory_id}
Content-Type: application/json

{
  "content_type": "decision",
  "topics": ["python", "web"]
}
```

#### Delete Memory
```http
DELETE /memories/{memory_id}
```

### Search

#### Semantic Search
```http
POST /memories/search
Content-Type: application/json

{
  "query": "async web frameworks",
  "limit": 10,
  "platform": "claude_code",
  "min_score": 0.5
}
```

Returns scored results ranked by hybrid search (semantic 60% + keyword 20% + graph 20%).

#### Keyword Search
```http
POST /memories/keyword-search
Content-Type: application/json

{
  "query": "FastAPI async",
  "limit": 10
}
```

Uses SQLite FTS5 for full-text keyword matching.

#### Recall (with session filters)
```http
POST /memories/recall
Content-Type: application/json

{
  "query": "database choice",
  "session_id": "my-session",
  "exclude_sources": ["chatgpt"]
}
```

### Sources & Stats

```http
GET /sources          # Per-platform memory counts
GET /stats            # Total counts, vector info, uptime
GET /stats/timeline   # Date-bucketed memory counts
GET /stats/topics     # Top topics across memories
```

### Knowledge Graph

```http
GET /graph?query=python&limit=50
```

Returns nodes (entities/topics) and edges (co-occurrence relationships) for visualization.

### Import / Export

```http
POST /import/file     # Upload JSONL/JSON file for processing
POST /import/json     # Send JSON body with memories array

GET /export           # Download all memories as JSON
GET /export?format=markdown&platform=claude_code  # Filtered markdown export
```

### WebSocket (Real-time Events)

```javascript
const ws = new WebSocket('ws://localhost:8100/api/v1/ws');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // data.type: "memory_created" | "memory_updated" | "memory_deleted"
  // data.timestamp: ISO 8601
  // data.data: { id, content_type, platform, ... }
};
```

## Rate Limits

| Tier | Default | Search | Import |
|------|---------|--------|--------|
| Unauthenticated | 60/min | 30/min | 10/min |

Rate limit headers are returned on every response:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

## Error Responses

All errors follow this format:

```json
{
  "detail": "Memory not found",
  "status_code": 404
}
```

Common status codes: 400 (bad request), 404 (not found), 422 (validation error), 429 (rate limited), 500 (server error).
