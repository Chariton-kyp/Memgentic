import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render as rtlRender, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const render = (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  return rtlRender(
    React.createElement(QueryClientProvider, { client }, ui),
  )
}

// next/navigation + next-themes are pulled in transitively by Header.
vi.mock('next/navigation', () => ({
  useRouter: vi.fn().mockReturnValue({ push: vi.fn(), replace: vi.fn() }),
  usePathname: vi.fn().mockReturnValue('/briefing'),
}))

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

vi.mock('@/components/layout/header', () => ({
  Header: ({ title }: { title: string }) =>
    React.createElement('header', { 'data-testid': 'header' }, title),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// UI component mocks — keep them minimal so the real page logic is exercised
// but we don't pull in Radix/base-ui portals or CSS-dependent behavior.
vi.mock('@/components/ui/card', () => ({
  Card: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'card', ...props }, children),
  CardContent: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', props, children),
  CardHeader: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', props, children),
  CardTitle: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('h3', props, children),
  CardDescription: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('p', props, children),
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

vi.mock('@/components/ui/input', () => ({
  Input: (props: Record<string, unknown>) =>
    React.createElement('input', props),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: (props: Record<string, unknown>) =>
    React.createElement('textarea', props),
}))

const getBriefing = vi.fn()
const listBriefingTiers = vi.fn()
const previewBriefingWeights = vi.fn()

vi.mock('@/lib/api', () => ({
  getBriefing: (...args: unknown[]) => getBriefing(...args),
  listBriefingTiers: (...args: unknown[]) => listBriefingTiers(...args),
  previewBriefingWeights: (...args: unknown[]) => previewBriefingWeights(...args),
}))

import BriefingPage from '../briefing/page'

function mockBriefingResponse(text: string, tier = 'T1') {
  return {
    tier,
    text,
    tokens: 120,
    model_context: 200_000,
    max_memories: 15,
    status: {},
  }
}

function mockTiersResponse() {
  return {
    tiers: {
      T0: {
        label: 'T0 Persona',
        budget: { tier: 'T0', tokens: 100, max_memories: 0, model_context: 200_000 },
      },
      T1: {
        label: 'T1 Horizon',
        budget: { tier: 'T1', tokens: 800, max_memories: 15, model_context: 200_000 },
      },
    },
  }
}

describe('BriefingPage', () => {
  beforeEach(() => {
    getBriefing.mockReset()
    listBriefingTiers.mockReset()
    previewBriefingWeights.mockReset()
    listBriefingTiers.mockResolvedValue(mockTiersResponse())
  })

  it('renders the page header', () => {
    // Never-resolving promise keeps the query in a loading state so we can
    // check the initial shell renders before any data arrives.
    getBriefing.mockReturnValue(new Promise(() => {}))
    render(React.createElement(BriefingPage))
    expect(screen.getByTestId('header')).toHaveTextContent('Briefing')
  })

  it('shows loading skeletons on initial fetch', () => {
    getBriefing.mockReturnValue(new Promise(() => {}))
    render(React.createElement(BriefingPage))
    expect(screen.getAllByTestId('skeleton').length).toBeGreaterThan(0)
  })

  it('renders the briefing text when the fetch succeeds', async () => {
    getBriefing.mockResolvedValue(
      mockBriefingResponse('## T1 — Horizon\n- pinned memory one'),
    )
    render(React.createElement(BriefingPage))
    const preview = await screen.findByTestId('briefing-preview')
    expect((preview as HTMLTextAreaElement).value).toContain('pinned memory one')
  })

  it('switches tier and refetches with the new tier param', async () => {
    getBriefing.mockResolvedValue(mockBriefingResponse('horizon text', 'T1'))
    render(React.createElement(BriefingPage))

    // Wait for the first (T1 default) fetch to happen.
    await waitFor(() => expect(getBriefing).toHaveBeenCalled())
    const firstCall = getBriefing.mock.calls[0]?.[0] as { tier?: string }
    expect(firstCall.tier).toBe('T1')

    // Switch to T3 Deep Recall — requires a query-mode param.
    getBriefing.mockResolvedValue(mockBriefingResponse('deep recall text', 'T3'))
    const t3Button = screen.getByText('T3 Deep Recall')
    fireEvent.click(t3Button)

    await waitFor(() => {
      const calls = getBriefing.mock.calls
      const hasT3 = calls.some((c) => (c[0] as { tier?: string })?.tier === 'T3')
      expect(hasT3).toBe(true)
    })
  })

  it('renders a non-crashing error fallback when the fetch fails', async () => {
    getBriefing.mockRejectedValue(new Error('boom'))
    render(React.createElement(BriefingPage))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Failed to load briefing')
    expect(alert.textContent).toContain('boom')
  })
})
