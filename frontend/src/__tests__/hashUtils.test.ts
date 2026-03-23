import { describe, it, expect, beforeEach, vi } from 'vitest'
import { hashString, verifyHash, passwordStrength, computeSecurityLevel } from '../security/hashUtils'

// Mock localStorage for computeSecurityLevel tests
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value }),
    removeItem: vi.fn((key: string) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
    get length() { return Object.keys(store).length },
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

describe('hashString', () => {
  it('returns a consistent hash for the same input', async () => {
    const h1 = await hashString('hello')
    const h2 = await hashString('hello')
    expect(h1).toBe(h2)
  })

  it('returns different hashes for different inputs', async () => {
    const h1 = await hashString('hello')
    const h2 = await hashString('world')
    expect(h1).not.toBe(h2)
  })

  it('returns a 64-character hex string (SHA-256)', async () => {
    const h = await hashString('test')
    expect(h).toHaveLength(64)
    expect(h).toMatch(/^[0-9a-f]{64}$/)
  })

  it('handles empty string', async () => {
    const h = await hashString('')
    expect(h).toHaveLength(64)
  })
})

describe('verifyHash', () => {
  it('returns true for correct input', async () => {
    const hash = await hashString('mypassword')
    const result = await verifyHash('mypassword', hash)
    expect(result).toBe(true)
  })

  it('returns false for wrong input', async () => {
    const hash = await hashString('mypassword')
    const result = await verifyHash('wrongpassword', hash)
    expect(result).toBe(false)
  })
})

describe('passwordStrength', () => {
  it('returns 0 for very short/empty password', () => {
    expect(passwordStrength('')).toBe(0)
    expect(passwordStrength('abc')).toBe(0)
  })

  it('gives points for length >= 8', () => {
    // 8 chars lowercase only: +15 (length >= 8)
    expect(passwordStrength('abcdefgh')).toBe(15)
  })

  it('gives more points for length >= 12', () => {
    // 12 chars lowercase: +15 (>=8) + 10 (>=12) = 25
    expect(passwordStrength('abcdefghijkl')).toBe(25)
  })

  it('gives points for mixed case', () => {
    // 8 chars mixed case: +15 (length) + 10 (mixed) = 25
    expect(passwordStrength('Abcdefgh')).toBe(25)
  })

  it('gives points for digits', () => {
    // 8 chars lower + digit: +15 (length) + 10 (digit) = 25
    expect(passwordStrength('abcdefg1')).toBe(25)
  })

  it('gives points for special chars', () => {
    // 8 chars lower + special: +15 (length) + 15 (special) = 30
    expect(passwordStrength('abcdefg!')).toBe(30)
  })

  it('gives maximum score for strong password', () => {
    // >= 12 chars, mixed case, digit, special
    // +15 (>=8) + 10 (>=12) + 10 (mixed) + 10 (digit) + 15 (special) = 60
    expect(passwordStrength('Abcdefghijk1!')).toBe(60)
  })
})

describe('computeSecurityLevel', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('returns 0 with no auth token and no lock', () => {
    expect(computeSecurityLevel()).toBe(0)
  })

  it('returns 40 with auth token only', () => {
    localStorageMock.setItem('sylea_auth_token', 'some-token')
    expect(computeSecurityLevel()).toBe(40)
  })

  it('returns 35 with pattern lock only (no auth)', () => {
    localStorageMock.setItem('sylea-lock-type', 'pattern')
    expect(computeSecurityLevel()).toBe(35)
  })

  it('returns 75 with auth token + pattern lock', () => {
    localStorageMock.setItem('sylea_auth_token', 'tok')
    localStorageMock.setItem('sylea-lock-type', 'pattern')
    expect(computeSecurityLevel()).toBe(75)
  })

  it('returns 20+bonus for password lock without auth', () => {
    localStorageMock.setItem('sylea-lock-type', 'password')
    localStorageMock.setItem('sylea-pwd-strength', '30')
    // 0 (no auth) + 20 (password base) + 30 (strength) = 50
    expect(computeSecurityLevel()).toBe(50)
  })

  it('caps at 100', () => {
    localStorageMock.setItem('sylea_auth_token', 'tok')
    localStorageMock.setItem('sylea-lock-type', 'password')
    localStorageMock.setItem('sylea-pwd-strength', '60')
    // 40 + 20 + 60 = 120, but capped at 100
    // Actually min(40, strength) so 40+20+40 = 100
    expect(computeSecurityLevel()).toBe(100)
  })
})
