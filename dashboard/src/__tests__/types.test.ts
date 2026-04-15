import { describe, it, expect } from 'vitest'
import type {
  Memory,
  SourceMetadata,
  SourceStats,
  SearchResult,
  SearchResultResponse,
  MemoryListResponse,
  StatsResponse,
  GraphNode,
  GraphEdge,
  GraphData,
  HealthResponse,
} from '../lib/types'

describe('Type constructions', () => {
  const baseSource: SourceMetadata = {
    platform: 'claude_code',
    platform_version: '1.0.0',
    session_id: 'sess-123',
    session_title: 'Test Session',
    capture_method: 'auto_daemon',
    original_timestamp: '2026-01-01T00:00:00Z',
    file_path: '/home/user/.claude/projects/test.jsonl',
  }

  const baseMemory: Memory = {
    id: 'mem-001',
    content: 'TypeScript supports generics',
    content_type: 'fact',
    platform: 'claude_code',
    topics: ['typescript', 'generics'],
    entities: ['TypeScript'],
    confidence: 0.95,
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    last_accessed: null,
    access_count: 0,
    source: baseSource,
  }

  it('constructs a valid Memory object', () => {
    expect(baseMemory.id).toBe('mem-001')
    expect(baseMemory.content).toBe('TypeScript supports generics')
    expect(baseMemory.content_type).toBe('fact')
    expect(baseMemory.platform).toBe('claude_code')
    expect(baseMemory.topics).toHaveLength(2)
    expect(baseMemory.entities).toContain('TypeScript')
    expect(baseMemory.confidence).toBeGreaterThan(0)
    expect(baseMemory.source.platform).toBe('claude_code')
  })

  it('constructs a valid SourceMetadata with all fields', () => {
    expect(baseSource.platform).toBe('claude_code')
    expect(baseSource.platform_version).toBe('1.0.0')
    expect(baseSource.session_id).toBe('sess-123')
    expect(baseSource.capture_method).toBe('auto_daemon')
    expect(baseSource.original_timestamp).toBeTruthy()
    expect(baseSource.file_path).toBeTruthy()
  })

  it('allows nullable SourceMetadata fields to be null', () => {
    const minimal: SourceMetadata = {
      platform: 'chatgpt',
      platform_version: null,
      session_id: null,
      session_title: null,
      capture_method: 'json_import',
      original_timestamp: null,
      file_path: null,
    }
    expect(minimal.platform_version).toBeNull()
    expect(minimal.session_id).toBeNull()
    expect(minimal.session_title).toBeNull()
    expect(minimal.original_timestamp).toBeNull()
    expect(minimal.file_path).toBeNull()
  })

  it('constructs a valid SourceStats object', () => {
    const stats: SourceStats = {
      platform: 'claude_code',
      count: 42,
      percentage: 78.5,
    }
    expect(stats.platform).toBe('claude_code')
    expect(stats.count).toBe(42)
    expect(stats.percentage).toBeCloseTo(78.5)
  })

  it('constructs a valid SearchResult', () => {
    const result: SearchResult = {
      memory: baseMemory,
      score: 0.89,
    }
    expect(result.score).toBeGreaterThan(0)
    expect(result.memory.id).toBe('mem-001')
  })

  it('constructs a valid SearchResultResponse', () => {
    const response: SearchResultResponse = {
      results: [{ memory: baseMemory, score: 0.89 }],
      query: 'typescript generics',
      total: 1,
    }
    expect(response.results).toHaveLength(1)
    expect(response.query).toBe('typescript generics')
    expect(response.total).toBe(1)
  })

  it('constructs a valid MemoryListResponse', () => {
    const response: MemoryListResponse = {
      memories: [baseMemory],
      total: 100,
      page: 1,
      page_size: 20,
    }
    expect(response.memories).toHaveLength(1)
    expect(response.total).toBe(100)
    expect(response.page).toBe(1)
    expect(response.page_size).toBe(20)
  })

  it('constructs a valid StatsResponse', () => {
    const stats: StatsResponse = {
      total_memories: 500,
      vector_count: 500,
      store_status: 'healthy',
      sources: [{ platform: 'claude_code', count: 300, percentage: 60 }],
    }
    expect(stats.total_memories).toBe(500)
    expect(stats.vector_count).toBe(500)
    expect(stats.store_status).toBe('healthy')
    expect(stats.sources).toHaveLength(1)
  })

  it('constructs valid GraphNode and GraphEdge', () => {
    const node: GraphNode = { id: 'TypeScript', type: 'entity', count: 10 }
    const edge: GraphEdge = { source: 'TypeScript', target: 'React', weight: 5 }
    expect(node.id).toBe('TypeScript')
    expect(edge.weight).toBe(5)
  })

  it('constructs a valid GraphData', () => {
    const data: GraphData = {
      nodes: [{ id: 'A', type: 'entity', count: 1 }],
      edges: [{ source: 'A', target: 'B', weight: 2 }],
    }
    expect(data.nodes).toHaveLength(1)
    expect(data.edges).toHaveLength(1)
  })

  it('constructs a valid HealthResponse', () => {
    const health: HealthResponse = {
      status: 'ok',
      version: '0.1.0',
      storage_backend: 'qdrant+sqlite',
    }
    expect(health.status).toBe('ok')
    expect(health.version).toBe('0.1.0')
    expect(health.storage_backend).toBe('qdrant+sqlite')
  })
})
