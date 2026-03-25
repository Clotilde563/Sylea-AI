// Route protegee — redirige vers /login si non authentifie
// Charge le profil globalement dès que l'utilisateur est authentifié
// Proactive agent polling + push notifications

import { useEffect, useRef, useCallback } from 'react'
import { Outlet, Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from './authStore'
import { useStore } from '../store/useStore'
import { api } from '../api/client'

export function ProtectedRoute() {
  const { token, loading, loadToken } = useAuthStore()
  const prevTokenRef = useRef<string | null | undefined>(undefined)
  const profilLoadedRef = useRef(false)
  const lastProactiveCheckRef = useRef(0)
  const location = useLocation()

  useEffect(() => {
    loadToken()
  }, [loadToken])

  // When token changes from one valid token to ANOTHER valid token (different user),
  // clear old profil to prevent flash of stale data.
  useEffect(() => {
    const prev = prevTokenRef.current
    if (prev && token && prev !== token) {
      useStore.getState().setProfil(null)
      useStore.getState().setSousObjectifs([])
      useStore.getState().setProbCalculee(false)
      useStore.getState().clearUnreadAgentMessages()
      profilLoadedRef.current = false
    }
    prevTokenRef.current = token
  }, [token])

  // Charger le profil globalement dès qu'on a un token (quelle que soit la page)
  useEffect(() => {
    if (token && !profilLoadedRef.current) {
      profilLoadedRef.current = true
      api.getProfil()
        .then(p => useStore.getState().setProfil(p))
        .catch(() => {
          // Pas de profil = nouvel utilisateur, c'est normal
          useStore.getState().setProfil(null)
        })
    }
  }, [token])

  // Proactive agent polling + push notifications
  // Debounced check: max once per 5 minutes
  const checkProactive = useCallback(async () => {
    if (localStorage.getItem('sylea_agent1_active') !== 'true') return
    const now = Date.now()
    if (now - lastProactiveCheckRef.current < 5 * 60 * 1000) return // 5 min debounce
    lastProactiveCheckRef.current = now

    try {
      const res = await api.agentProactive()
      if (res.message) {
        useStore.getState().incrementUnreadAgentMessages()
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Agent Syléa 1', {
            body: res.message,
            icon: '/sylea-logo.png',
            tag: 'agent-proactive',
          })
        }
      }
    } catch {
      // Silently ignore polling errors
    }
  }, [])

  // Initial load + 30-minute polling
  useEffect(() => {
    if (!token) return

    const agentActive = localStorage.getItem('sylea_agent1_active') === 'true'
    if (!agentActive) return

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }

    // Check once after 10 seconds (let the app load first)
    const initialTimeout = setTimeout(checkProactive, 10_000)
    // Then poll every 30 minutes
    const interval = setInterval(checkProactive, 30 * 60 * 1000)

    return () => {
      clearTimeout(initialTimeout)
      clearInterval(interval)
    }
  }, [token, checkProactive])

  // Check on page visibility change (user comes back to the tab)
  useEffect(() => {
    if (!token) return
    const agentActive = localStorage.getItem('sylea_agent1_active') === 'true'
    if (!agentActive) return

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkProactive()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [token, checkProactive])

  // Check on page navigation
  useEffect(() => {
    if (!token) return
    const agentActive = localStorage.getItem('sylea_agent1_active') === 'true'
    if (!agentActive) return

    checkProactive()
  }, [location.pathname, token, checkProactive])

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          background: 'var(--bg-primary)',
        }}
      >
        <div className="spinner" />
      </div>
    )
  }

  if (!token) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
