// Route protegee — redirige vers /login si non authentifie

import { useEffect, useRef } from 'react'
import { Outlet, Navigate } from 'react-router-dom'
import { useAuthStore } from './authStore'
import { useStore } from '../store/useStore'

export function ProtectedRoute() {
  const { token, loading, loadToken } = useAuthStore()
  const prevTokenRef = useRef<string | null | undefined>(undefined)

  useEffect(() => {
    loadToken()
  }, [loadToken])

  // When token changes (new login), clear old profil to prevent flash of stale data
  useEffect(() => {
    if (prevTokenRef.current !== undefined && prevTokenRef.current !== token && token) {
      // Token changed — new user logged in, clear old profil
      useStore.getState().setProfil(null)
      useStore.getState().setSousObjectifs([])
      useStore.getState().setProbCalculee(false)
    }
    prevTokenRef.current = token
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
