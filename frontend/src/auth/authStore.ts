// Store d'authentification Sylea.AI — Zustand

import { create } from 'zustand'
import { useStore } from '../store/useStore'
import { api, API_BASE } from '../api/client'

interface AuthUser {
  id: string
  email: string
  provider: 'local' | 'google' | 'github' | 'apple'
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  loading: boolean
  error: string | null

  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<{ requires_verification?: boolean }>
  verifyCode: (email: string, code: string) => Promise<void>
  googleLogin: () => Promise<void>
  handleGoogleCallback: (code: string) => Promise<void>
  githubLogin: () => Promise<void>
  handleGithubCallback: (code: string) => Promise<void>
  appleLogin: () => Promise<void>
  handleAppleCallback: (
    code: string,
    options?: { firstName?: string; lastName?: string; idToken?: string },
  ) => Promise<void>
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
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        // credentials: 'include' pour recevoir le cookie sylea_csrf que le
        // backend pose dans la réponse (utilisé sur les POST suivants).
        credentials: 'include',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        // Cas special : 409 USE_OAUTH = compte OAuth-only.
        // Le backend renvoie un detail object {code, provider, message}, on
        // affiche un message friendly pointant vers le bon bouton.
        if (res.status === 409 && err?.detail?.code === 'USE_OAUTH') {
          const provider = (err.detail.provider || 'OAuth').toString()
          const providerCap = provider.charAt(0).toUpperCase() + provider.slice(1)
          throw new Error(
            `Ce compte se connecte avec ${providerCap}. Utilise le bouton "Continuer avec ${providerCap}" ci-dessous.`,
          )
        }
        // Cas normal : detail peut etre string ou objet
        const msg = typeof err?.detail === 'string'
          ? err.detail
          : (err?.detail?.message || `Erreur ${res.status}`)
        throw new Error(msg)
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
      const res = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, password_confirm: password }),
        credentials: 'include',
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

  googleLogin: async () => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const { url } = await api.authGoogleUrl(redirectUri)
      window.location.href = url
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur Google OAuth'
      set({ loading: false, error: msg })
    }
  },

  githubLogin: async () => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const { url } = await api.authGithubUrl(redirectUri)
      window.location.href = url
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur GitHub OAuth'
      set({ loading: false, error: msg })
    }
  },

  handleGithubCallback: async (code: string) => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const data = await api.authOAuthGithub(code, redirectUri)
      const token = data.access_token

      // Get user info
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      }
      const meResp = await fetch(`${API_BASE}/api/auth/me`, { headers })
      const user = meResp.ok ? await meResp.json() : { id: '', email: '', provider: 'github' }

      localStorage.setItem(AUTH_TOKEN_KEY, token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
      set({ token, user, loading: false, error: null })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur callback GitHub'
      set({ loading: false, error: msg })
      throw e
    }
  },

  handleGoogleCallback: async (code: string) => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const data = await api.authOAuthGoogle(code, redirectUri)
      const token = data.access_token

      // Get user info
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      }
      const meResp = await fetch(`${API_BASE}/api/auth/me`, { headers })
      const user = meResp.ok ? await meResp.json() : { id: '', email: '', provider: 'google' }

      localStorage.setItem(AUTH_TOKEN_KEY, token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
      set({ token, user, loading: false, error: null })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur callback Google'
      set({ loading: false, error: msg })
      throw e
    }
  },

  appleLogin: async () => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const { url } = await api.authAppleUrl(redirectUri)
      window.location.href = url
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur Apple Sign-In'
      set({ loading: false, error: msg })
    }
  },

  handleAppleCallback: async (
    code: string,
    options?: { firstName?: string; lastName?: string; idToken?: string },
  ) => {
    set({ loading: true, error: null })
    try {
      const redirectUri = `${window.location.origin}/auth/callback`
      const data = await api.authOAuthApple(code, redirectUri, options)
      const token = data.access_token

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      }
      const meResp = await fetch(`${API_BASE}/api/auth/me`, { headers })
      const user = meResp.ok
        ? await meResp.json()
        : { id: '', email: '', provider: 'apple' }

      localStorage.setItem(AUTH_TOKEN_KEY, token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user))
      set({ token, user, loading: false, error: null })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erreur callback Apple'
      set({ loading: false, error: msg })
      throw e
    }
  },

  verifyCode: async (email: string, code: string) => {
    set({ loading: true, error: null })
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code }),
        credentials: 'include',
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
    // Revocation server-side (best-effort) : invalide tous les tokens cote
    // backend AVANT de purger le local. Si l'appel echoue (reseau), on purge
    // quand meme le local — l'important cote UX est de deconnecter ici.
    try {
      void api.authLogout().catch(() => { /* best-effort */ })
    } catch { /* api indispo */ }
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
