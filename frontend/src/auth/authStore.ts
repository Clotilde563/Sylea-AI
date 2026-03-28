// Store d'authentification Sylea.AI — Zustand

import { create } from 'zustand'
import { useStore } from '../store/useStore'

interface AuthUser {
  id: string
  email: string
  provider: 'local' | 'google' | 'github'
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  loading: boolean
  error: string | null

  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<{ requires_verification?: boolean }>
  verifyCode: (email: string, code: string) => Promise<void>
  logout: () => void
  loadToken: () => void
  clearError: () => void
}

const AUTH_TOKEN_KEY = 'sylea_auth_token'
const AUTH_USER_KEY = 'sylea_auth_user'

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  loading: true,
  error: null,

  login: async (email: string, password: string) => {
    set({ loading: true, error: null })
    try {
      const base = import.meta.env.VITE_API_URL || ''
      const res = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `Erreur ${res.status}`)
      }
      const data = await res.json()
      const token = data.access_token || data.token
      const user = { id: '', email, provider: 'local' as const }
      localStorage.setItem(AUTH_TOKEN_KEY, token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
      set({ token, user, loading: false, error: null })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur de connexion'
      set({ loading: false, error: msg })
      throw e
    }
  },

  register: async (email: string, password: string) => {
    set({ loading: true, error: null })
    try {
      const base = import.meta.env.VITE_API_URL || ''
      const res = await fetch(`${base}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, password_confirm: password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `Erreur ${res.status}`)
      }
      const data = await res.json()
      if (data.requires_verification) {
        set({ loading: false, error: null })
        return { requires_verification: true }
      }
      // Fallback: direct token (no verification)
      const token = data.access_token || data.token
      const user = { id: '', email, provider: 'local' as const }
      localStorage.setItem(AUTH_TOKEN_KEY, token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
      set({ token, user, loading: false, error: null })
      return {}
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erreur d'inscription"
      set({ loading: false, error: msg })
      throw e
    }
  },

  verifyCode: async (email: string, code: string) => {
    set({ loading: true, error: null })
    try {
      const base = import.meta.env.VITE_API_URL || ''
      const res = await fetch(`${base}/api/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `Erreur ${res.status}`)
      }
      // Verification succeeded — do NOT store token/user.
      // The user must log in separately after verification.
      set({ loading: false, error: null })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Code de verification invalide'
      set({ loading: false, error: msg })
      throw e
    }
  },

  logout: () => {
    localStorage.removeItem(AUTH_TOKEN_KEY)
    localStorage.removeItem(AUTH_USER_KEY)
    // Clear profil from main store to prevent flash of old data on next login
    useStore.getState().setProfil(null)
    useStore.getState().setSousObjectifs([])
    useStore.getState().setProbCalculee(false)
    set({ token: null, user: null, loading: false, error: null })
  },

  loadToken: () => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY)
    const userStr = localStorage.getItem(AUTH_USER_KEY)
    let user: AuthUser | null = null
    if (userStr) {
      try {
        user = JSON.parse(userStr)
      } catch {
        // corrupted data — ignore
      }
    }
    set({ token, user, loading: false })
  },

  clearError: () => set({ error: null }),
}))
