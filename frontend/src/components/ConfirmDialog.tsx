/**
 * ConfirmDialog — modale de confirmation custom Syléa (remplace window.confirm).
 *
 * Usage :
 *   const [dialog, setDialog] = useState<ConfirmDialogProps | null>(null)
 *   ...
 *   setDialog({
 *     title: "Activer cet outil ?",
 *     description: "L'agent pourra...",
 *     bullets: ["• Ligne 1", "• Ligne 2"],
 *     severity: "warning",
 *     confirmLabel: "Activer",
 *     onConfirm: () => { ...; setDialog(null) },
 *     onCancel: () => setDialog(null),
 *   })
 *   ...
 *   <ConfirmDialog {...dialog} />
 *
 * Le composant s'affiche uniquement si `open !== false` (par defaut open=true).
 * Utilise un <dialog> HTML natif avec backdrop (meilleure accessibilite a11y +
 * auto-focus + trap Escape).
 */

import { useEffect, useRef } from 'react'

export type ConfirmSeverity = 'info' | 'warning' | 'danger'

export interface ConfirmDialogProps {
  open?: boolean
  title: string
  description?: string
  bullets?: string[]
  severity?: ConfirmSeverity
  confirmLabel?: string
  cancelLabel?: string
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
}

const COLORS: Record<ConfirmSeverity, { accent: string; bg: string; border: string; icon: string }> = {
  info: {
    accent: '#6366f1',
    bg: 'rgba(99,102,241,0.08)',
    border: 'rgba(99,102,241,0.35)',
    icon: 'ℹ️',
  },
  warning: {
    accent: '#f59e0b',
    bg: 'rgba(245,158,11,0.08)',
    border: 'rgba(245,158,11,0.35)',
    icon: '⚠️',
  },
  danger: {
    accent: '#ef4444',
    bg: 'rgba(239,68,68,0.08)',
    border: 'rgba(239,68,68,0.4)',
    icon: '🚨',
  },
}

export default function ConfirmDialog(props: ConfirmDialogProps) {
  const {
    open = true,
    title,
    description,
    bullets,
    severity = 'warning',
    confirmLabel = 'Confirmer',
    cancelLabel = 'Annuler',
    onConfirm,
    onCancel,
    busy = false,
  } = props

  const dialogRef = useRef<HTMLDivElement>(null)
  const confirmBtnRef = useRef<HTMLButtonElement>(null)

  // Escape ferme la modale. Focus sur le bouton confirmer a l'ouverture.
  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel()
      if (e.key === 'Enter' && !busy) onConfirm()
    }
    window.addEventListener('keydown', handleKey)
    // Petit delai pour laisser React render avant focus
    const t = setTimeout(() => confirmBtnRef.current?.focus(), 50)
    return () => {
      window.removeEventListener('keydown', handleKey)
      clearTimeout(t)
    }
  }, [open, busy, onCancel, onConfirm])

  if (!open) return null

  const c = COLORS[severity]

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      onClick={(e) => {
        // Click sur backdrop = annulation (sauf si busy)
        if (e.target === e.currentTarget && !busy) onCancel()
      }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 10000,
        background: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
      }}
    >
      <div
        ref={dialogRef}
        style={{
          maxWidth: 520,
          width: '100%',
          background: 'var(--bg-panel, #1a1a1a)',
          border: `1px solid ${c.border}`,
          borderRadius: 12,
          padding: '1.5rem',
          boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.8rem' }}>
          <span style={{ fontSize: '1.25rem' }}>{c.icon}</span>
          <h3
            id="confirm-dialog-title"
            style={{
              margin: 0,
              color: c.accent,
              fontSize: '1.05rem',
              fontWeight: 700,
              lineHeight: 1.3,
            }}
          >
            {title}
          </h3>
        </div>

        {description && (
          <p
            style={{
              margin: '0 0 0.9rem 0',
              fontSize: '0.9rem',
              color: 'var(--text-secondary, #d0d0d0)',
              lineHeight: 1.5,
            }}
          >
            {description}
          </p>
        )}

        {bullets && bullets.length > 0 && (
          <ul
            style={{
              margin: '0 0 1rem 0',
              paddingLeft: '1.1rem',
              background: c.bg,
              border: `1px solid ${c.border}`,
              borderRadius: 8,
              padding: '0.6rem 1.1rem',
              listStyle: 'none',
            }}
          >
            {bullets.map((b, i) => (
              <li
                key={i}
                style={{
                  fontSize: '0.82rem',
                  color: 'var(--text-secondary, #d0d0d0)',
                  lineHeight: 1.6,
                  marginBottom: i < bullets.length - 1 ? '0.2rem' : 0,
                }}
              >
                {b}
              </li>
            ))}
          </ul>
        )}

        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            disabled={busy}
            style={{
              padding: '8px 16px',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid var(--border, rgba(255,255,255,0.1))',
              borderRadius: 8,
              color: 'var(--text-secondary, #d0d0d0)',
              cursor: busy ? 'not-allowed' : 'pointer',
              fontSize: '0.88rem',
              fontWeight: 500,
              opacity: busy ? 0.5 : 1,
            }}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmBtnRef}
            onClick={onConfirm}
            disabled={busy}
            style={{
              padding: '8px 16px',
              background: c.accent,
              border: `1px solid ${c.accent}`,
              borderRadius: 8,
              color: '#fff',
              cursor: busy ? 'not-allowed' : 'pointer',
              fontSize: '0.88rem',
              fontWeight: 600,
              opacity: busy ? 0.5 : 1,
            }}
          >
            {busy ? '…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
