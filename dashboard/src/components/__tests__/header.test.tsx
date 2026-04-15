import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// Mock next-themes
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

// Mock UI components
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: { children?: React.ReactNode; [key: string]: unknown }) =>
    React.createElement('button', props, children),
}))

vi.mock('@/components/ui/sidebar', () => ({
  SidebarTrigger: () => React.createElement('button', { 'data-testid': 'sidebar-trigger' }, 'Toggle sidebar'),
}))

vi.mock('@/components/ui/separator', () => ({
  Separator: (props: Record<string, unknown>) => React.createElement('hr', props),
}))

import { Header } from '../layout/header'

describe('Header', () => {
  it('renders the title', () => {
    render(React.createElement(Header, { title: 'Memories' }))
    expect(screen.getByText('Memories')).toBeInTheDocument()
  })

  it('renders different titles', () => {
    render(React.createElement(Header, { title: 'Settings' }))
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('has a theme toggle button with correct aria-label', () => {
    render(React.createElement(Header, { title: 'Test' }))
    expect(screen.getByLabelText('Toggle theme')).toBeInTheDocument()
  })

  it('has a sidebar trigger', () => {
    render(React.createElement(Header, { title: 'Test' }))
    expect(screen.getByTestId('sidebar-trigger')).toBeInTheDocument()
  })

  it('renders children when provided', () => {
    render(
      React.createElement(Header, { title: 'Test' },
        React.createElement('span', { 'data-testid': 'child' }, 'Extra content')
      )
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
    expect(screen.getByText('Extra content')).toBeInTheDocument()
  })

  it('renders as a header element', () => {
    render(React.createElement(Header, { title: 'Test' }))
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })
})
