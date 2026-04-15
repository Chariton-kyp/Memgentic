import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: vi.fn().mockReturnValue({ push: vi.fn(), replace: vi.fn() }),
  usePathname: vi.fn().mockReturnValue('/settings'),
}))

// Mock API module
vi.mock('@/lib/api', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'ok', version: '0.1.0', storage_backend: 'qdrant' }),
  getStats: vi.fn().mockResolvedValue({
    total_memories: 100,
    vector_count: 100,
    store_status: 'healthy',
    sources: [],
  }),
  exportMemories: vi.fn().mockResolvedValue({ count: 0, memories: [] }),
  importJson: vi.fn().mockResolvedValue({ imported: 0, errors: 0, total: 0 }),
  getMe: vi.fn().mockResolvedValue({ authenticated: false }),
  clearApiKey: vi.fn(),
  hasApiKey: vi.fn().mockReturnValue(false),
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components
vi.mock('@/components/ui/card', () => ({
  Card: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'card', ...props }, children),
  CardContent: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', props, children),
  CardHeader: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('div', props, children),
  CardTitle: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('h3', props, children),
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

vi.mock('@/components/ui/textarea', () => ({
  Textarea: (props: Record<string, unknown>) =>
    React.createElement('textarea', props),
}))

import SettingsPage from '../settings/page'

describe('SettingsPage', () => {
  it('renders loading skeletons initially', () => {
    render(React.createElement(SettingsPage))
    const skeletons = screen.getAllByTestId('skeleton')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders the Settings heading after loading', async () => {
    render(React.createElement(SettingsPage))
    const heading = await screen.findByText('Settings')
    expect(heading).toBeInTheDocument()
  })

  it('renders Connection Status section', async () => {
    render(React.createElement(SettingsPage))
    const section = await screen.findByText('Connection Status')
    expect(section).toBeInTheDocument()
  })

  it('renders Statistics section', async () => {
    render(React.createElement(SettingsPage))
    const section = await screen.findByText('Statistics')
    expect(section).toBeInTheDocument()
  })

  it('renders Import / Export section', async () => {
    render(React.createElement(SettingsPage))
    const section = await screen.findByText('Import / Export')
    expect(section).toBeInTheDocument()
  })

  it('renders Export button', async () => {
    render(React.createElement(SettingsPage))
    const btn = await screen.findByText('Export All Memories')
    expect(btn).toBeInTheDocument()
  })

  it('renders Upload JSON File button', async () => {
    render(React.createElement(SettingsPage))
    const btn = await screen.findByText('Upload JSON File')
    expect(btn).toBeInTheDocument()
  })

  it('renders Import from Text button', async () => {
    render(React.createElement(SettingsPage))
    const btn = await screen.findByText('Import from Text')
    expect(btn).toBeInTheDocument()
  })

  it('renders a textarea for JSON import', async () => {
    render(React.createElement(SettingsPage))
    // Wait for the page to finish loading
    await screen.findByText('Settings')
    const textarea = screen.getByPlaceholderText(/Paste JSON here/)
    expect(textarea).toBeInTheDocument()
  })

  it('renders Refresh button for connection status', async () => {
    render(React.createElement(SettingsPage))
    const btn = await screen.findByText('Refresh')
    expect(btn).toBeInTheDocument()
  })
})
