// Route protegee — redirige vers /login si non authentifie
// Charge le profil globalement dès que l'utilisateur est authentifié
// Proactive agent polling + push notifications

import { useEffect, useRef } from 'react'
import { Outlet, Navigate } from 'react-router-dom'
import { useAuthStore } from './authStore'
import { useStore } from '../store/useStore'
import { api } from '../api/client'

export function ProtectedRoute() {
  const { token, loading, loadToken } = useAuthStore()
  const prevTokenRef = useRef<string | null | undefined>(undefined)
  const profilLoadedRef = useRef(false)

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
  useEffect(() => {
    if (!token) return

    // Check if agent is active
    const agentActive = localStorage.getItem('sylea_agent1_active') === 'true'
    if (!agentActive) return

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }

    // Check once on load, then poll every 30 minutes
    // (the backend handles timing — returns null if too early)
    const checkProactive = async () => {
      if (localStorage.getItem('sylea_agent1_active') !== 'true') return
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
    }

    // Check once after 10 seconds (let the app load first)
    const initialTimeout = setTimeout(checkProactive, 10_000)
    // Then poll every 30 minutes
    const interval = setInterval(checkProactive, 30 * 60 * 1000)

    return () => {
      clearTimeout(initialTimeout)
      clearInterval(interval)
    }
  }, [token])

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
