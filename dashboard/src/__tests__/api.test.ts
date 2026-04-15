import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock fetch globally
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

function mockJsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  }
}

describe('API client', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Re-import to get fresh module with mocked fetch
    vi.resetModules()
  })

  async function importApi() {
    return import('../lib/api')
  }

  it('constructs correct URL for listMemories', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ memories: [], total: 0, page: 1, page_size: 20 }))
    const api = await importApi()

    await api.listMemories({ page: 2, page_size: 10 })

    const calledUrl = mockFetch.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/memories')
    expect(calledUrl).toContain('page=2')
    expect(calledUrl).toContain('page_size=10')
  })

  it('constructs correct URL for listMemories with source filter', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ memories: [], total: 0, page: 1, page_size: 20 }))
    const api = await importApi()

    await api.listMemories({ source: 'claude_code' })

    const calledUrl = mockFetch.mock.calls[0][0] as string
    expect(calledUrl).toContain('source=claude_code')
  })

  it('constructs correct URL for getMemory', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'abc-123', content: 'test' }))
    const api = await importApi()

    await api.getMemory('abc-123')

    const calledUrl = mockFetch.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/memories/abc-123')
  })

  it('sends POST request for createMemory', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'new-1', content: 'test' }))
    const api = await importApi()

    await api.createMemory({ content: 'test memory', topics: ['testing'] })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/memories'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ content: 'test memory', topics: ['testing'] }),
      })
    )
  })

  it('sends POST request for searchMemories', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ results: [], query: 'test', total: 0 }))
    const api = await importApi()

    await api.searchMemories({ query: 'test query', limit: 5 })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/memories/search'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ query: 'test query', limit: 5 }),
      })
    )
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse('Not Found', 404))
    const api = await importApi()

    await expect(api.getMemory('nonexistent')).rejects.toThrow('API 404')
  })

  it('sets Content-Type header to application/json', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ sources: [], total: 0 }))
    const api = await importApi()

    await api.getSources()

    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.headers).toEqual(
      expect.objectContaining({ 'Content-Type': 'application/json' })
    )
  })

  it('constructs correct URL for getGraphData with minWeight', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ nodes: [], edges: [] }))
    const api = await importApi()

    await api.getGraphData(3)

    const calledUrl = mockFetch.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/graph?min_weight=3')
  })

  it('constructs correct URL for getGraphNeighbors with encoding', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ entity: 'test entity', neighbors: [] }))
    const api = await importApi()

    await api.getGraphNeighbors('test entity', 2)

    const calledUrl = mockFetch.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/graph/test%20entity')
    expect(calledUrl).toContain('depth=2')
  })

  it('sends PATCH request for updateMemory', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse({ id: 'abc', content: 'test' }))
    const api = await importApi()

    await api.updateMemory('abc', { topics: ['updated'] })

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/memories/abc'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ topics: ['updated'] }),
      })
    )
  })

  it('sends DELETE request for deleteMemory', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true })
    const api = await importApi()

    await api.deleteMemory('abc-123')

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/memories/abc-123'),
      expect.objectContaining({ method: 'DELETE' })
    )
  })
})
