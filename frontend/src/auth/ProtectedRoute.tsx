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

  // Request notification permission as soon as user is authenticated (not just when agent is active)
  useEffect(() => {
    if (!token) return
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [token])

  // Daily check-in reminder — notify user in the evening if no bilan done today
  useEffect(() => {
    if (!token) return

    const checkReminder = async () => {
      try {
        const lastCheckin = localStorage.getItem('sylea_last_checkin_date')
        const today = new Date().toISOString().split('T')[0]

        if (lastCheckin !== today) {
          const hour = new Date().getHours()
          if (hour >= 19 && hour <= 22) {
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('Sylea.AI -- Bilan du jour', {
                body: "N'oubliez pas de faire votre bilan quotidien !",
                icon: '/sylea-logo.png',
                tag: 'daily-checkin',
              })
            }
          }
        }
      } catch {}
    }

    // Check after 30 seconds, then every hour
    const timeout = setTimeout(checkReminder, 30000)
    const interval = setInterval(checkReminder, 60 * 60 * 1000)

    return () => { clearTimeout(timeout); clearInterval(interval) }
  }, [token])

  // Proactive agent polling + push notifications
  // Debounced check: max once per 5 minutes
  const checkProactive = useCallback(async () => {
    const agentActive = localStorage.getItem('sylea_agent1_active') === 'true'
    const now = Date.now()
    const timeSinceLastCheck = now - lastProactiveCheckRef.current
    console.log('[Proactive] Checking...', { agentActive, timeSinceLastCheck: Math.round(timeSinceLastCheck / 1000) + 's' })
    if (!agentActive) return
    if (timeSinceLastCheck < 5 * 60 * 1000) return // 5 min debounce
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
