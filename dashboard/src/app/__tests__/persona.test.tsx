import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import type { Persona } from '@/lib/types'

// --- API mocks ------------------------------------------------------------
// The persona page uses a handful of helpers from `@/lib/api`. We mock the
// module once at the top level and override per-test via `vi.mocked()`.
vi.mock('@/lib/api', () => ({
  getPersona: vi.fn(),
  putPersona: vi.fn(),
  bootstrapPersona: vi.fn(),
  acceptPersonaBootstrap: vi.fn(),
}))

// --- Toast mocks ----------------------------------------------------------
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// --- UI mocks (mirror settings.test.tsx conventions) ----------------------
vi.mock('@/components/layout/header', () => ({
  Header: ({ title }: { title: string }) =>
    React.createElement('header', { 'data-testid': 'header' }, title),
}))

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

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    ...props
  }: {
    children?: React.ReactNode
    [key: string]: unknown
  }) => React.createElement('button', props, children),
}))

vi.mock('@/components/ui/input', () => ({
  Input: (props: Record<string, unknown>) =>
    React.createElement('input', props),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: (props: Record<string, unknown>) =>
    React.createElement('textarea', props),
}))

vi.mock('@/components/ui/badge', () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode }) =>
    React.createElement('span', props, children),
}))

vi.mock('@/components/ui/separator', () => ({
  Separator: (props: Record<string, unknown>) =>
    React.createElement('hr', props),
}))

vi.mock('@/components/ui/checkbox', () => ({
  Checkbox: ({
    checked,
    onCheckedChange,
    ...props
  }: {
    checked?: boolean
    onCheckedChange?: (v: boolean) => void
    [key: string]: unknown
  }) =>
    React.createElement('input', {
      type: 'checkbox',
      checked: Boolean(checked),
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        onCheckedChange?.(e.target.checked),
      ...props,
    }),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    open,
    children,
  }: {
    open?: boolean
    onOpenChange?: (v: boolean) => void
    children: React.ReactNode
  }) =>
    open
      ? React.createElement('div', { role: 'dialog' }, children)
      : null,
  DialogContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogDescription: ({ children }: { children: React.ReactNode }) =>
    React.createElement('p', null, children),
  DialogFooter: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogHeader: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  DialogTitle: ({ children }: { children: React.ReactNode }) =>
    React.createElement('h2', null, children),
}))

// Importing after the mocks ensures the page picks up the mocked modules.
import PersonaPage from '../persona/page'
import {
  getPersona,
  putPersona,
  bootstrapPersona,
  acceptPersonaBootstrap,
} from '@/lib/api'
import { toast } from 'sonner'

// --- Fixtures -------------------------------------------------------------
function samplePersona(overrides: Partial<Persona> = {}): Persona {
  return {
    version: 1,
    identity: {
      name: 'Atlas',
      role: 'Personal AI assistant for Alice',
      tone: 'warm, direct',
      pronouns: null,
      voice_sample: null,
    },
    people: [
      {
        name: 'Alice',
        relationship: 'creator',
        preferences: ['prefers PostgreSQL'],
        do_not: [],
      },
    ],
    projects: [
      {
        name: 'journaling-app',
        status: 'active',
        stack: ['next.js', 'postgres'],
        tldr: 'journaling app that helps process emotions',
      },
    ],
    preferences: {
      remember: ['decisions with rationale'],
      avoid: ['apology-heavy responses'],
    },
    metadata: {
      workspace_inherit: false,
      updated_at: '2026-04-21T10:00:00Z',
      generated_by: 'manual',
    },
    ...overrides,
  }
}

function emptyPersona(): Persona {
  return {
    version: 1,
    identity: {
      name: 'Assistant',
      role: 'Memory-enabled AI assistant',
      tone: 'helpful, concise',
      pronouns: null,
      voice_sample: null,
    },
    people: [],
    projects: [],
    preferences: { remember: [], avoid: [] },
    metadata: {
      workspace_inherit: false,
      updated_at: null,
      generated_by: 'manual',
    },
  }
}

describe('PersonaPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // -- Initial load ------------------------------------------------------
  it('fetches persona on mount and renders identity, people, projects, and preferences', async () => {
    vi.mocked(getPersona).mockResolvedValue(samplePersona())

    render(React.createElement(PersonaPage))

    // identity block
    const nameInput = (await screen.findByLabelText('Name')) as HTMLInputElement
    expect(nameInput.value).toBe('Atlas')

    const roleInput = screen.getByLabelText('Role') as HTMLInputElement
    expect(roleInput.value).toBe('Personal AI assistant for Alice')

    // people block
    expect(screen.getByDisplayValue('Alice')).toBeInTheDocument()
    expect(screen.getByDisplayValue('creator')).toBeInTheDocument()

    // projects block
    expect(screen.getByDisplayValue('journaling-app')).toBeInTheDocument()
    expect(
      screen.getByDisplayValue(
        'journaling app that helps process emotions',
      ),
    ).toBeInTheDocument()

    // preferences block — "one item per line" textareas
    const remember = screen.getByLabelText('Remember') as HTMLTextAreaElement
    expect(remember.value).toBe('decisions with rationale')
    const avoid = screen.getByLabelText('Avoid') as HTMLTextAreaElement
    expect(avoid.value).toBe('apology-heavy responses')

    expect(getPersona).toHaveBeenCalledTimes(1)
  })

  // -- Edit + save --------------------------------------------------------
  it('edits identity.name, clicks Save, and PUTs the updated persona to /api/v1/persona', async () => {
    const user = userEvent.setup()
    const initial = samplePersona()
    vi.mocked(getPersona).mockResolvedValue(initial)
    vi.mocked(putPersona).mockImplementation(async (p) => p)

    render(React.createElement(PersonaPage))

    const nameInput = (await screen.findByLabelText('Name')) as HTMLInputElement
    await user.clear(nameInput)
    await user.type(nameInput, 'Nyx')

    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(putPersona).toHaveBeenCalledTimes(1)
    })

    // The page uses putPersona (PUT /api/v1/persona) as its save path.
    const submitted = vi.mocked(putPersona).mock.calls[0][0]
    expect(submitted.identity.name).toBe('Nyx')
    // Preferences are re-derived from the textarea lines on submit.
    expect(submitted.preferences.remember).toEqual([
      'decisions with rationale',
    ])
    expect(submitted.preferences.avoid).toEqual(['apology-heavy responses'])

    expect(toast.success).toHaveBeenCalledWith('Persona saved')

    // Updated persona is rendered after the server response comes back.
    await waitFor(() => {
      const updatedNameInput = screen.getByLabelText('Name') as HTMLInputElement
      expect(updatedNameInput.value).toBe('Nyx')
    })
  })

  // -- Validation ---------------------------------------------------------
  it('clicking Validate on an invalid persona surfaces an inline error via toast', async () => {
    const user = userEvent.setup()
    // Server returns a persona with a blank required identity.name.
    const bad = samplePersona({
      identity: {
        name: '',
        role: null,
        tone: null,
        pronouns: null,
        voice_sample: null,
      },
    })
    vi.mocked(getPersona).mockResolvedValue(bad)

    render(React.createElement(PersonaPage))

    // Wait for the page to finish loading.
    await screen.findByLabelText('Name')

    await user.click(screen.getByRole('button', { name: /validate/i }))

    expect(toast.error).toHaveBeenCalledTimes(1)
    const msg = vi.mocked(toast.error).mock.calls[0][0] as string
    expect(msg).toMatch(/identity\.name is required/)
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('Validate passes and toasts success for a well-formed persona', async () => {
    const user = userEvent.setup()
    vi.mocked(getPersona).mockResolvedValue(samplePersona())

    render(React.createElement(PersonaPage))
    await screen.findByLabelText('Name')

    await user.click(screen.getByRole('button', { name: /validate/i }))

    expect(toast.success).toHaveBeenCalledWith('Persona is valid')
    expect(toast.error).not.toHaveBeenCalled()
  })

  // -- Error state --------------------------------------------------------
  it('when getPersona fails the page surfaces an error toast and does not crash', async () => {
    vi.mocked(getPersona).mockRejectedValue(new Error('offline'))

    render(React.createElement(PersonaPage))

    // Falls back to emptyPersona() locally so the form still renders.
    const nameInput = (await screen.findByLabelText('Name')) as HTMLInputElement
    expect(nameInput.value).toBe('Assistant')
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining('Failed to load persona'),
    )
  })

  it('when putPersona fails the page surfaces an error toast and stays usable', async () => {
    const user = userEvent.setup()
    vi.mocked(getPersona).mockResolvedValue(samplePersona())
    vi.mocked(putPersona).mockRejectedValue(new Error('boom'))

    render(React.createElement(PersonaPage))
    await screen.findByLabelText('Name')

    await user.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining('Save failed'),
      )
    })
    // Page still rendered — save button is back to enabled state.
    const saveBtn = screen.getByRole('button', {
      name: /save/i,
    }) as HTMLButtonElement
    expect(saveBtn.disabled).toBe(false)
  })

  // -- Empty state --------------------------------------------------------
  it('first load with no people/projects renders empty placeholders and the bootstrap CTA', async () => {
    vi.mocked(getPersona).mockResolvedValue(emptyPersona())

    render(React.createElement(PersonaPage))
    await screen.findByLabelText('Name')

    expect(screen.getByText('No people yet.')).toBeInTheDocument()
    expect(screen.getByText('No projects yet.')).toBeInTheDocument()

    // The LLM bootstrap button is the "generate a starting persona" CTA.
    expect(
      screen.getByRole('button', { name: /bootstrap from memories/i }),
    ).toBeInTheDocument()
    // "Reset to default" is the manual equivalent.
    expect(
      screen.getByRole('button', { name: /reset to default/i }),
    ).toBeInTheDocument()
  })

  // -- Bootstrap flow -----------------------------------------------------
  it('Bootstrap from memories opens a diff dialog and Accept persists the proposed persona', async () => {
    const user = userEvent.setup()
    const initial = samplePersona()
    const proposed = samplePersona({
      identity: {
        name: 'Prometheus',
        role: 'Research co-pilot',
        tone: 'curious, rigorous',
        pronouns: null,
        voice_sample: null,
      },
      metadata: {
        workspace_inherit: false,
        updated_at: '2026-04-22T10:00:00Z',
        generated_by: 'bootstrap',
      },
    })
    vi.mocked(getPersona).mockResolvedValue(initial)
    vi.mocked(bootstrapPersona).mockResolvedValue({ persona: proposed })
    vi.mocked(acceptPersonaBootstrap).mockResolvedValue(proposed)

    render(React.createElement(PersonaPage))
    await screen.findByLabelText('Name')

    await user.click(
      screen.getByRole('button', { name: /bootstrap from memories/i }),
    )

    // Bootstrap call uses the default "recent" source + limit 100.
    await waitFor(() => {
      expect(bootstrapPersona).toHaveBeenCalledWith({
        source: 'recent',
        limit: 100,
      })
    })

    // Dialog with diff preview is visible.
    expect(
      await screen.findByText('Review proposed persona'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /accept/i }))

    await waitFor(() => {
      expect(acceptPersonaBootstrap).toHaveBeenCalledTimes(1)
    })
    expect(vi.mocked(acceptPersonaBootstrap).mock.calls[0][0].identity.name).toBe(
      'Prometheus',
    )

    // After accept, the form reflects the newly saved persona.
    await waitFor(() => {
      const nameInput = screen.getByLabelText('Name') as HTMLInputElement
      expect(nameInput.value).toBe('Prometheus')
    })
    expect(toast.success).toHaveBeenCalledWith('Persona bootstrapped')
  })

  it('Bootstrap failure surfaces a toast error and does not open the dialog', async () => {
    const user = userEvent.setup()
    vi.mocked(getPersona).mockResolvedValue(samplePersona())
    vi.mocked(bootstrapPersona).mockRejectedValue(new Error('no llm'))

    render(React.createElement(PersonaPage))
    await screen.findByLabelText('Name')

    await user.click(
      screen.getByRole('button', { name: /bootstrap from memories/i }),
    )

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining('Bootstrap failed'),
      )
    })
    expect(screen.queryByText('Review proposed persona')).not.toBeInTheDocument()
  })
})
