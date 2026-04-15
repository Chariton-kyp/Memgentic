import { describe, it, expect, vi } from 'vitest'
import { render as rtlRender, screen } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// HomePage uses useQueryClient internally, so we wrap every render in a
// fresh QueryClientProvider. Retries disabled to keep tests deterministic.
const render = (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  return rtlRender(
    React.createElement(QueryClientProvider, { client }, ui)
  )
}

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) =>
    React.createElement('a', { href, ...props }, children),
}))

// Mock next-themes
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

// Mock the header
vi.mock('@/components/layout/header', () => ({
  Header: ({ title }: { title: string }) =>
    React.createElement('header', { 'data-testid': 'header' }, title),
}))

// Mock UI components
vi.mock('@/components/ui/input', () => ({
  Input: (props: Record<string, unknown>) =>
    React.createElement('input', props),
}))

vi.mock('@/components/ui/card', () => ({
  Card: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'card', ...props }, children),
  CardContent: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', props, children),
}))

vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('span', props, children),
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: { children?: React.ReactNode; [key: string]: unknown }) =>
    React.createElement('button', props, children),
}))

vi.mock('@/components/ui/skeleton', () => ({
  Skeleton: (props: Record<string, unknown>) =>
    React.createElement('div', { 'data-testid': 'skeleton', ...props }),
}))

vi.mock('@/components/ui/sidebar', () => ({
  SidebarTrigger: () => React.createElement('button', null, 'Toggle sidebar'),
}))

vi.mock('@/components/ui/separator', () => ({
  Separator: () => React.createElement('hr'),
}))

// Mock date-fns
vi.mock('date-fns', () => ({
  formatDistanceToNow: () => '2 hours ago',
}))

// Mock Select components
vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'select' }, children),
  SelectTrigger: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SelectValue: ({ placeholder }: { placeholder?: string }) =>
    React.createElement('span', null, placeholder),
  SelectContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SelectItem: ({ children }: { children: React.ReactNode; value: string }) =>
    React.createElement('div', null, children),
}))

// We'll mock the hooks at the top level so we can control them per test
const mockUseMemories = vi.fn()
const mockUseSearch = vi.fn()
const mockUseSources = vi.fn()

vi.mock('@/hooks/use-memories', () => ({
  useMemories: (...args: unknown[]) => mockUseMemories(...args),
  useSearch: (...args: unknown[]) => mockUseSearch(...args),
  useSources: (...args: unknown[]) => mockUseSources(...args),
  usePinnedMemories: () => ({ data: { memories: [], total: 0 }, isLoading: false, error: null }),
  usePinMemory: () => ({ mutate: vi.fn(), isPending: false }),
  useUnpinMemory: () => ({ mutate: vi.fn(), isPending: false }),
  useTopics: () => ({ data: [], isLoading: false }),
  useDeleteMemory: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/hooks/use-collections', () => ({
  useCollections: () => ({ data: [], isLoading: false }),
  useCreateCollection: () => ({ mutate: vi.fn(), isPending: false }),
}))

import HomePage from '../page'

describe('HomePage', () => {
  beforeEach(() => {
    mockUseSources.mockReturnValue({
      data: { sources: [] },
      isLoading: false,
      error: null,
    })
  })

  it('renders search input with placeholder', () => {
    mockUseMemories.mockReturnValue({
      data: { memories: [], total: 0 },
      isLoading: false,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByPlaceholderText('Search memories...')).toBeInTheDocument()
  })

  it('renders header with Memories title', () => {
    mockUseMemories.mockReturnValue({
      data: { memories: [], total: 0 },
      isLoading: false,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByTestId('header')).toHaveTextContent('Memories')
  })

  it('renders loading skeletons when data is loading', () => {
    mockUseMemories.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    const skeletons = screen.getAllByTestId('skeleton')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders empty state when no memories', () => {
    mockUseMemories.mockReturnValue({
      data: { memories: [], total: 0 },
      isLoading: false,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByText('No memories yet')).toBeInTheDocument()
    expect(screen.getByText('Start capturing knowledge to see it here.')).toBeInTheDocument()
  })

  it('renders memory cards when data is available', () => {
    const mockMemory = {
      id: 'mem-1',
      content: 'Test memory content for rendering',
      content_type: 'fact',
      platform: 'claude_code',
      topics: ['testing'],
      entities: ['Test'],
      confidence: 0.9,
      status: 'active',
      created_at: '2026-01-01T00:00:00Z',
      last_accessed: null,
      access_count: 0,
      source: {
        platform: 'claude_code',
        platform_version: null,
        session_id: null,
        session_title: null,
        capture_method: 'auto_daemon',
        original_timestamp: null,
        file_path: null,
      },
    }

    mockUseMemories.mockReturnValue({
      data: { memories: [mockMemory], total: 1 },
      isLoading: false,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByText('Test memory content for rendering')).toBeInTheDocument()
    expect(screen.getByText('Claude Code')).toBeInTheDocument()
    // "Fact" appears both in the content type filter and in the memory card badge
    expect(screen.getAllByText('Fact').length).toBeGreaterThanOrEqual(1)
  })

  it('renders error message when API fails', () => {
    mockUseMemories.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Network error'),
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByText(/Network error/)).toBeInTheDocument()
  })

  it('renders topic badges on memory cards', () => {
    const mockMemory = {
      id: 'mem-2',
      content: 'Memory with topics',
      content_type: 'learning',
      platform: 'chatgpt',
      topics: ['react', 'hooks', 'state'],
      entities: [],
      confidence: 0.8,
      status: 'active',
      created_at: '2026-01-01T00:00:00Z',
      last_accessed: null,
      access_count: 0,
      source: {
        platform: 'chatgpt',
        platform_version: null,
        session_id: null,
        session_title: null,
        capture_method: 'json_import',
        original_timestamp: null,
        file_path: null,
      },
    }

    mockUseMemories.mockReturnValue({
      data: { memories: [mockMemory], total: 1 },
      isLoading: false,
      error: null,
    })
    mockUseSearch.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    })

    render(React.createElement(HomePage))
    expect(screen.getByText('react')).toBeInTheDocument()
    expect(screen.getByText('hooks')).toBeInTheDocument()
    expect(screen.getByText('state')).toBeInTheDocument()
  })
})
