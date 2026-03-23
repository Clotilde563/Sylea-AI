import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuthStore } from '../auth/authStore'

// Mock localStorage
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

describe('useAuthStore', () => {
  beforeEach(() => {
    // Reset the zustand store between tests
    useAuthStore.setState({
      token: null,
      user: null,
      loading: true,
      error: null,
    })
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('has correct initial state', () => {
    const state = useAuthStore.getState()
    expect(state.token).toBeNull()
    expect(state.user).toBeNull()
    expect(state.loading).toBe(true)
    expect(state.error).toBeNull()
  })

  describe('loadToken', () => {
    it('sets loading false and token null when localStorage is empty', () => {
      useAuthStore.getState().loadToken()
      const state = useAuthStore.getState()
      expect(state.loading).toBe(false)
      expect(state.token).toBeNull()
      expect(state.user).toBeNull()
    })

    it('loads token from localStorage', () => {
      localStorageMock.setItem('sylea_auth_token', 'test-token-123')
      localStorageMock.setItem('sylea_auth_user', JSON.stringify({
        id: '1', email: 'test@example.com', provider: 'local',
      }))

      useAuthStore.getState().loadToken()
      const state = useAuthStore.getState()

      expect(state.token).toBe('test-token-123')
      expect(state.user).toEqual({
        id: '1',
        email: 'test@example.com',
        provider: 'local',
      })
      expect(state.loading).toBe(false)
    })

    it('handles corrupted user JSON gracefully', () => {
      localStorageMock.setItem('sylea_auth_token', 'tok')
      localStorageMock.setItem('sylea_auth_user', '{bad json')

      useAuthStore.getState().loadToken()
      const state = useAuthStore.getState()

      expect(state.token).toBe('tok')
      expect(state.user).toBeNull()
      expect(state.loading).toBe(false)
    })
  })

  describe('logout', () => {
    it('clears token, user, and loading', () => {
      // Set some state first
      useAuthStore.setState({
        token: 'abc',
        user: { id: '1', email: 'x@x.com', provider: 'local' },
        loading: false,
      })
      localStorageMock.setItem('sylea_auth_token', 'abc')
      localStorageMock.setItem('sylea_auth_user', '{}')

      useAuthStore.getState().logout()
      const state = useAuthStore.getState()

      expect(state.token).toBeNull()
      expect(state.user).toBeNull()
      expect(state.loading).toBe(false)
      expect(state.error).toBeNull()
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('sylea_auth_token')
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('sylea_auth_user')
    })
  })

  describe('clearError', () => {
    it('clears the error', () => {
      useAuthStore.setState({ error: 'Some error' })
      useAuthStore.getState().clearError()
      expect(useAuthStore.getState().error).toBeNull()
    })
  })
})
