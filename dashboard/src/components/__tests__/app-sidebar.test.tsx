import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) =>
    React.createElement('a', { href, ...props }, children),
}))

// Mock next-themes
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

// Mock the sidebar UI components to simplify rendering
vi.mock('@/components/ui/sidebar', () => ({
  Sidebar: ({ children }: { children: React.ReactNode }) =>
    React.createElement('nav', { 'data-testid': 'sidebar' }, children),
  SidebarContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SidebarFooter: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SidebarHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SidebarGroup: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SidebarGroupContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  SidebarMenu: ({ children }: { children: React.ReactNode }) =>
    React.createElement('ul', null, children),
  SidebarMenuItem: ({ children }: { children: React.ReactNode }) =>
    React.createElement('li', null, children),
  SidebarMenuButton: ({ children, render, ...rest }: { children: React.ReactNode; render?: React.ReactElement; tooltip?: string; isActive?: boolean }) => {
    // Drop the ``tooltip`` prop — it's a Sidebar-specific label that would
    // warn if forwarded to a DOM button.
    const { tooltip, ...props } = rest
    void tooltip
    if (render && React.isValidElement(render)) {
      return React.cloneElement(render as React.ReactElement<{ children?: React.ReactNode }>, props, children)
    }
    return React.createElement('button', props, children)
  },
  SidebarSeparator: () => React.createElement('hr'),
}))

// Mock Button
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('button', props, children),
}))

import { AppSidebar } from '../layout/app-sidebar'

describe('AppSidebar', () => {
  it('renders the sidebar', () => {
    render(React.createElement(AppSidebar))
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
  })

  it('renders the Memgentic brand link', () => {
    render(React.createElement(AppSidebar))
    expect(screen.getByText('Memgentic')).toBeInTheDocument()
  })

  it('renders all navigation labels', () => {
    render(React.createElement(AppSidebar))
    expect(screen.getByText('Memories')).toBeInTheDocument()
    expect(screen.getByText('Sources')).toBeInTheDocument()
    expect(screen.getByText('Graph')).toBeInTheDocument()
    expect(screen.getByText('Timeline')).toBeInTheDocument()
    expect(screen.getByText('Analytics')).toBeInTheDocument()
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('renders correct hrefs for navigation links', () => {
    render(React.createElement(AppSidebar))
    const links = screen.getAllByRole('link')
    const hrefs = links.map((link) => link.getAttribute('href'))
    expect(hrefs).toContain('/')
    expect(hrefs).toContain('/sources')
    expect(hrefs).toContain('/graph')
    expect(hrefs).toContain('/timeline')
    expect(hrefs).toContain('/analytics')
    expect(hrefs).toContain('/settings')
  })

  it('renders a theme toggle button', () => {
    render(React.createElement(AppSidebar))
    expect(screen.getByLabelText('Toggle theme')).toBeInTheDocument()
  })
})
