import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useKeyboardShortcuts, type KeyboardShortcut } from '../use-keyboard-shortcuts'

function fireKey(key: string, opts: Partial<KeyboardEventInit> = {}) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...opts }))
}

describe('useKeyboardShortcuts', () => {
  it('fires action when matching key is pressed', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '/', description: 'Focus search', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))
    fireKey('/')

    expect(action).toHaveBeenCalledOnce()
  })

  it('fires Escape shortcut', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: 'Escape', description: 'Clear', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))
    fireKey('Escape')

    expect(action).toHaveBeenCalledOnce()
  })

  it('fires ? shortcut for help', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '?', description: 'Show keyboard shortcuts', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))
    fireKey('?')

    expect(action).toHaveBeenCalledOnce()
  })

  it('fires ctrl shortcut only when ctrl/meta is held', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: 'k', ctrl: true, description: 'Focus search', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))

    // Without ctrl - should NOT fire
    fireKey('k')
    expect(action).not.toHaveBeenCalled()

    // With ctrl - should fire
    fireKey('k', { ctrlKey: true })
    expect(action).toHaveBeenCalledOnce()
  })

  it('does not fire shortcuts when typing in input elements', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '/', description: 'Focus search', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))

    // Create an input element and dispatch keydown from it
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))

    expect(action).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('does not fire shortcuts when typing in textarea elements', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '/', description: 'Focus search', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))

    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))

    expect(action).not.toHaveBeenCalled()
    document.body.removeChild(textarea)
  })

  it('allows Escape even in input elements', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: 'Escape', description: 'Clear', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))

    expect(action).toHaveBeenCalledOnce()
    document.body.removeChild(input)
  })

  it('does not fire non-matching keys', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '/', description: 'Focus search', action },
    ]

    renderHook(() => useKeyboardShortcuts(shortcuts))
    fireKey('a')

    expect(action).not.toHaveBeenCalled()
  })

  it('cleans up event listener on unmount', () => {
    const action = vi.fn()
    const shortcuts: KeyboardShortcut[] = [
      { key: '/', description: 'Focus search', action },
    ]

    const { unmount } = renderHook(() => useKeyboardShortcuts(shortcuts))
    unmount()
    fireKey('/')

    expect(action).not.toHaveBeenCalled()
  })
})
