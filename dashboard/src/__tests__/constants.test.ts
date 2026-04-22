import { describe, it, expect } from 'vitest'
import {
  PLATFORM_CONFIG,
  CONTENT_TYPE_CONFIG,
  getPlatformConfig,
  getContentTypeConfig,
} from '../lib/constants'

describe('PLATFORM_CONFIG', () => {
  const expectedPlatforms = [
    'claude_code',
    'claude_web',
    'chatgpt',
    'gemini_cli',
    'aider',
    'codex_cli',
    'copilot_cli',
    'unknown',
  ]

  it('has entries for all expected platforms', () => {
    for (const platform of expectedPlatforms) {
      expect(PLATFORM_CONFIG).toHaveProperty(platform)
    }
  })

  it('every platform has label, color, and bgColor', () => {
    for (const config of Object.values(PLATFORM_CONFIG)) {
      expect(config.label).toBeTruthy()
      expect(config.color).toMatch(/^#[0-9A-Fa-f]{6}$/)
      expect(config.bgColor).toBeTruthy()
    }
  })

  it('has correct labels for known platforms', () => {
    expect(PLATFORM_CONFIG.claude_code.label).toBe('Claude Code')
    expect(PLATFORM_CONFIG.chatgpt.label).toBe('ChatGPT')
    expect(PLATFORM_CONFIG.gemini_cli.label).toBe('Gemini CLI')
    expect(PLATFORM_CONFIG.aider.label).toBe('Aider')
    expect(PLATFORM_CONFIG.codex_cli.label).toBe('Codex CLI')
    expect(PLATFORM_CONFIG.copilot_cli.label).toBe('Copilot CLI')
    expect(PLATFORM_CONFIG.unknown.label).toBe('Unknown')
  })

  it('claude_code and claude_web share the same color', () => {
    expect(PLATFORM_CONFIG.claude_code.color).toBe(PLATFORM_CONFIG.claude_web.color)
  })
})

describe('CONTENT_TYPE_CONFIG', () => {
  const expectedTypes = [
    'fact',
    'decision',
    'code_snippet',
    'preference',
    'learning',
    'action_item',
    'raw_exchange',
    'conversation_summary',
  ]

  it('has entries for all expected content types', () => {
    for (const type of expectedTypes) {
      expect(CONTENT_TYPE_CONFIG).toHaveProperty(type)
    }
  })

  it('every content type has a label and color', () => {
    for (const [, config] of Object.entries(CONTENT_TYPE_CONFIG)) {
      expect(config.label).toBeTruthy()
      expect(config.color).toMatch(/^bg-/)
    }
  })

  it('has correct labels', () => {
    expect(CONTENT_TYPE_CONFIG.fact.label).toBe('Fact')
    expect(CONTENT_TYPE_CONFIG.decision.label).toBe('Decision')
    expect(CONTENT_TYPE_CONFIG.code_snippet.label).toBe('Code')
    expect(CONTENT_TYPE_CONFIG.preference.label).toBe('Preference')
    expect(CONTENT_TYPE_CONFIG.learning.label).toBe('Learning')
    expect(CONTENT_TYPE_CONFIG.action_item.label).toBe('Action Item')
    expect(CONTENT_TYPE_CONFIG.raw_exchange.label).toBe('Exchange')
    expect(CONTENT_TYPE_CONFIG.conversation_summary.label).toBe('Summary')
  })
})

describe('getPlatformConfig', () => {
  it('returns config for known platforms', () => {
    expect(getPlatformConfig('claude_code')).toBe(PLATFORM_CONFIG.claude_code)
    expect(getPlatformConfig('chatgpt')).toBe(PLATFORM_CONFIG.chatgpt)
  })

  it('returns unknown config for unrecognized platforms', () => {
    expect(getPlatformConfig('nonexistent')).toBe(PLATFORM_CONFIG.unknown)
    expect(getPlatformConfig('')).toBe(PLATFORM_CONFIG.unknown)
  })
})

describe('getContentTypeConfig', () => {
  it('returns config for known content types', () => {
    expect(getContentTypeConfig('fact')).toBe(CONTENT_TYPE_CONFIG.fact)
    expect(getContentTypeConfig('decision')).toBe(CONTENT_TYPE_CONFIG.decision)
  })

  it('returns fallback for unknown content types', () => {
    const result = getContentTypeConfig('nonexistent')
    expect(result.label).toBe('nonexistent')
    expect(result.color).toBe('bg-gray-500')
  })
})
