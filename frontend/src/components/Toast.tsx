/**
 * Toast — système de notifications éphémères Syléa.
 *
 * Provider + hook sans dependances externes. Injectable une seule fois dans
 * App.tsx via <ToastProvider>. Les composants consomment via `useToast()`.
 *
 * Usage :
 *   const { toast } = useToast()
 *   toast.success("Outil activé")
 *   toast.error("Échec de la sauvegarde")
 *   toast.info("Agent en cours...")
 *
 * Les toasts se ferment automatiquement apres 4s (succes/info) ou 7s (erreur).
 * Empilement en bas a droite, max 5 visibles simultanement (FIFO).
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

type ToastLevel = 'success' | 'error' | 'info' | 'warning'

interface ToastMessage {
  id: string
  level: ToastLevel
  text: string
  createdAt: number
}

interface ToastAPI {
  success: (text: string) => void
  error: (text: string) => void
  info: (text: string) => void
  warning: (text: string) => void
}

const ToastContext = createContext<{ toast: ToastAPI } | null>(null)

const MAX_TOASTS = 5
const AUTO_DISMISS_MS: Record<ToastLevel, number> = {
  success: 4000,
  info: 4000,
  warning: 5000,
  error: 7000,
}

const COLORS: Record<ToastLevel, { bg: string; border: string; accent: string; icon: string }> = {
  success: { bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.4)', accent: '#10b981', icon: '✓' },
  error: { bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.4)', accent: '#ef4444', icon: '✕' },
  warning: { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.4)', accent: '#f59e0b', icon: '⚠' },
  info: { bg: 'rgba(99,102,241,0.12)', border: 'rgba(99,102,241,0.4)', accent: '#6366f1', icon: 'ℹ' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback((level: ToastLevel, text: string) => {
    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const msg: ToastMessage = { id, level, text, createdAt: Date.now() }
    setToasts((prev) => {
      const next = [...prev, msg]
      // Limite stricte : on drop les plus anciens
      return next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next
    })
    setTimeout(() => remove(id), AUTO_DISMISS_MS[level])
  }, [remove])

  const api = useMemo<ToastAPI>(() => ({
    success: (text) => push('success', text),
    error: (text) => push('error', text),
    info: (text) => push('info', text),
    warning: (text) => push('warning', text),
  }), [push])

  return (
    <ToastContext.Provider value={{ toast: api }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: 'fixed',
          bottom: 20,
          right: 20,
          zIndex: 9998,
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          pointerEvents: 'none',
        }}
      >
        {toasts.map((t) => {
          const c = COLORS[t.level]
          return (
            <div
              key={t.id}
              onClick={() => remove(t.id)}
              style={{
                pointerEvents: 'auto',
                cursor: 'pointer',
                minWidth: 260,
                maxWidth: 380,
                padding: '0.7rem 0.9rem',
                background: c.bg,
                border: `1px solid ${c.border}`,
                borderLeft: `4px solid ${c.accent}`,
                borderRadius: 8,
                color: 'var(--text-primary, #fff)',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.5rem',
                backdropFilter: 'blur(8px)',
                boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
                animation: 'sylea-toast-in 0.22s ease-out',
              }}
            >
              <span style={{ color: c.accent, fontWeight: 700, flexShrink: 0 }}>{c.icon}</span>
              <span style={{ flex: 1, lineHeight: 1.4 }}>{t.text}</span>
            </div>
          )
        })}
      </div>
      <style>{`
        @keyframes sylea-toast-in {
          from { opacity: 0; transform: translateX(20px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </ToastContext.Provider>
  )
}

export function useToast(): { toast: ToastAPI } {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    // Fallback silencieux hors provider (au cas ou utilise avant mount).
    return {
      toast: {
        success: () => {},
        error: () => {},
        info: () => {},
        warning: () => {},
      },
    }
  }
  return ctx
}
