import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock the API module
vi.mock('@/lib/api', () => ({
  listMemories: vi.fn(),
  getMemory: vi.fn(),
  searchMemories: vi.fn(),
  getSources: vi.fn(),
  getStats: vi.fn(),
  getGraphData: vi.fn(),
  deleteMemory: vi.fn(),
  createMemory: vi.fn(),
}))

import * as api from '@/lib/api'
import {
  useMemories,
  useMemory,
  useSearch,
  useSources,
  useStats,
  useDeleteMemory,
  useCreateMemory,
} from '../use-memories'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children)
  }
}

describe('useMemories', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('starts in loading state', () => {
    vi.mocked(api.listMemories).mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useMemories({ page: 1 }), {
      wrapper: createWrapper(),
    })
    expect(result.current.isLoading).toBe(true)
    expect(result.current.data).toBeUndefined()
  })

  it('returns data after successful fetch', async () => {
    const mockData = { memories: [], total: 0, page: 1, page_size: 20 }
    vi.mocked(api.listMemories).mockResolvedValue(mockData)

    const { result } = renderHook(() => useMemories({ page: 1 }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(mockData)
    expect(api.listMemories).toHaveBeenCalledWith({ page: 1 })
  })

  it('passes params to listMemories', async () => {
    vi.mocked(api.listMemories).mockResolvedValue({ memories: [], total: 0, page: 2, page_size: 10 })

    const { result } = renderHook(
      () => useMemories({ page: 2, page_size: 10, source: 'claude_code' }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.listMemories).toHaveBeenCalledWith({ page: 2, page_size: 10, source: 'claude_code' })
  })

  it('returns error state on failure', async () => {
    vi.mocked(api.listMemories).mockRejectedValue(new Error('API error'))

    const { result } = renderHook(() => useMemories({ page: 1 }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeTruthy()
  })
})

describe('useMemory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches a single memory by id', async () => {
    const mockMemory = { id: 'abc', content: 'test' }
    vi.mocked(api.getMemory).mockResolvedValue(mockMemory as never)

    const { result } = renderHook(() => useMemory('abc'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.getMemory).toHaveBeenCalledWith('abc')
  })

  it('does not fetch when id is empty', () => {
    const { result } = renderHook(() => useMemory(''), {
      wrapper: createWrapper(),
    })
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('useSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not search when query is too short', () => {
    const { result } = renderHook(() => useSearch('a'), {
      wrapper: createWrapper(),
    })
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.searchMemories).not.toHaveBeenCalled()
  })

  it('searches when query is at least 2 characters', async () => {
    const mockResults = { results: [], query: 'te', total: 0 }
    vi.mocked(api.searchMemories).mockResolvedValue(mockResults)

    const { result } = renderHook(() => useSearch('te'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.searchMemories).toHaveBeenCalledWith({ query: 'te' })
  })
})

describe('useSources', () => {
  it('fetches sources', async () => {
    const mockSources = { sources: [], total: 0 }
    vi.mocked(api.getSources).mockResolvedValue(mockSources)

    const { result } = renderHook(() => useSources(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(mockSources)
  })
})

describe('useStats', () => {
  it('fetches stats', async () => {
    const mockStats = { total_memories: 10, vector_count: 10, store_status: 'ok', sources: [] }
    vi.mocked(api.getStats).mockResolvedValue(mockStats)

    const { result } = renderHook(() => useStats(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(mockStats)
  })
})
