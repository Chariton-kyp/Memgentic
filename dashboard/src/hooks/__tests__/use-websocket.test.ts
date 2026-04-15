import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { ReactNode } from 'react'
import React from 'react'

// Mock dependencies before importing the hook
vi.mock('sonner', () => ({
  toast: { success: vi.fn() },
}))

// Track WebSocket instances
let mockWSInstances: MockWebSocket[] = []

class MockWebSocket {
  static CONNECTING = 0 as const
  static OPEN = 1 as const
  static CLOSING = 2 as const
  static CLOSED = 3 as const

  CONNECTING = 0 as const
  OPEN = 1 as const
  CLOSING = 2 as const
  CLOSED = 3 as const

  readyState: number = MockWebSocket.CONNECTING
  url: string
  onopen: ((ev: Event) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.(new CloseEvent('close'))
  })
  send = vi.fn()

  constructor(url: string) {
    this.url = url
    mockWSInstances.push(this)
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  simulateMessage(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }

  simulateError() {
    this.onerror?.(new Event('error'))
  }
}

// Install mock WebSocket globally
vi.stubGlobal('WebSocket', MockWebSocket)

// Mock @tanstack/react-query
const mockInvalidateQueries = vi.fn()
const mockQueryClient = { invalidateQueries: mockInvalidateQueries }

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => mockQueryClient,
  QueryClientProvider: ({ children }: { children: ReactNode }) => children,
  QueryClient: vi.fn(() => mockQueryClient),
}))

describe('useWebSocket', () => {
  beforeEach(() => {
    mockWSInstances = []
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  async function renderWebSocketHook() {
    // Dynamic import so mocks are in place
    const { useWebSocket } = await import('../use-websocket')
    return renderHook(() => useWebSocket())
  }

  it('starts with connecting status and creates WebSocket', async () => {
    const { result } = await renderWebSocketHook()
    expect(mockWSInstances.length).toBeGreaterThanOrEqual(1)
    expect(result.current.status).toBe('connecting')
  })

  it('transitions to connected on open', async () => {
    const { result } = await renderWebSocketHook()
    const ws = mockWSInstances[mockWSInstances.length - 1]

    act(() => {
      ws.simulateOpen()
    })

    expect(result.current.status).toBe('connected')
  })

  it('transitions to disconnected on close and schedules reconnect', async () => {
    const { result } = await renderWebSocketHook()
    const ws = mockWSInstances[mockWSInstances.length - 1]

    act(() => {
      ws.simulateOpen()
    })
    expect(result.current.status).toBe('connected')

    act(() => {
      ws.close()
    })
    expect(result.current.status).toBe('disconnected')
  })

  it('invalidates queries on memory_created message', async () => {
    await renderWebSocketHook()
    const ws = mockWSInstances[mockWSInstances.length - 1]

    act(() => {
      ws.simulateOpen()
    })

    act(() => {
      ws.simulateMessage({ type: 'memory_created', data: { content: 'test memory' } })
    })

    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['memories'] })
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['stats'] })
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['sources'] })
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['graph'] })
  })

  it('reconnects with backoff on close', async () => {
    await renderWebSocketHook()
    const ws = mockWSInstances[mockWSInstances.length - 1]
    const initialCount = mockWSInstances.length

    act(() => {
      ws.simulateOpen()
    })

    // Close to trigger reconnect
    act(() => {
      ws.close()
    })

    // Advance past initial backoff (1000ms)
    act(() => {
      vi.advanceTimersByTime(1100)
    })

    // A new WebSocket should have been created
    expect(mockWSInstances.length).toBeGreaterThan(initialCount)
  })

  it('cleans up on unmount', async () => {
    const { unmount } = await renderWebSocketHook()
    const ws = mockWSInstances[mockWSInstances.length - 1]

    act(() => {
      ws.simulateOpen()
    })

    unmount()

    expect(ws.close).toHaveBeenCalled()
  })
})
