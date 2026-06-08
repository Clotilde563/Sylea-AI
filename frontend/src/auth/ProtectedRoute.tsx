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
  // Retry logic: si l'API est injoignable, on retente 3 fois avant d'abandonner
  useEffect(() => {
    if (token && !profilLoadedRef.current) {
      profilLoadedRef.current = true

      const loadProfil = async (retries = 3) => {
        for (let i = 0; i < retries; i++) {
          try {
            const p = await api.getProfil()
            useStore.getState().setProfil(p)
            return
          } catch (err: any) {
            const status = err?.response?.status
            if (status === 404) {
              // 404 = pas de profil, nouvel utilisateur → c'est normal
              useStore.getState().setProfil(null)
              return
            }
            // Erreur réseau ou serveur → retenter après délai
            if (i < retries - 1) {
              await new Promise(r => setTimeout(r, 2000 * (i + 1)))
            }
          }
        }
        // Après 3 tentatives échouées, on laisse profil tel quel
        // (ne pas mettre null si c'est un problème réseau)
        console.warn('[ProtectedRoute] Impossible de charger le profil après 3 tentatives')
      }

      loadProfil()
    }
  }, [token])

  // Notification permission is requested on user interaction only
  // (agent activation, bilan click, etc.) — NOT on page load
  // Chrome blocks auto-requests without user interaction

  // Daily check-in reminder — notify at 8am when check-in resets
  useEffect(() => {
    if (!token) return

    const checkReminder = async () => {
      try {
        const lastCheckin = localStorage.getItem('sylea_last_checkin_date')
        const today = new Date().toISOString().split('T')[0]

        if (lastCheckin !== today) {
          const hour = new Date().getHours()
          if (hour >= 8) {
            // Check-in pas fait aujourd'hui et il est 8h ou plus → rappel
            if ('Notification' in window && Notification.permission === 'granted') {
              // Ne notifier qu'une fois par jour
              const lastNotif = localStorage.getItem('sylea_last_checkin_notif')
              if (lastNotif !== today) {
                localStorage.setItem('sylea_last_checkin_notif', today)
                new Notification('Sylea.AI — Bilan du jour', {
                  body: 'Bonjour ! Pensez a faire votre bilan quotidien pour suivre votre progression.',
                  icon: '/sylea-logo.png',
                  tag: 'daily-checkin',
                })
              }
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
    // Non connecté → landing publique (intro + documentation + CTA central),
    // pas le login direct. Le bouton "Prendre en main mon objectif de vie"
    // (et "Se connecter") de la landing mène ensuite à /login.
    return <Navigate to="/bienvenue" replace />
  }

  return <Outlet />
}
