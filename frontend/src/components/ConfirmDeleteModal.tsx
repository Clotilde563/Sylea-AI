// Modal de confirmation de suppression — Design Syléa.AI
import { useT } from '../i18n/LanguageContext'

interface ConfirmDeleteModalProps {
  visible: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDeleteModal({ visible, onConfirm, onCancel }: ConfirmDeleteModalProps) {
  const t = useT()
  if (!visible) return null

  return (
    <div
      onClick={onCancel}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(2, 5, 9, 0.85)',
        backdropFilter: 'blur(6px)',
        animation: 'fadeIn 0.15s ease',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '2rem',
          maxWidth: '420px',
          width: '90%',
          boxShadow: 'var(--shadow-card)',
          animation: 'fadeInScale 0.2s ease',
        }}
      >
        {/* Icon */}
        <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '48px',
            height: '48px',
            borderRadius: '50%',
            background: 'var(--danger-dim)',
          }}>
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
              fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </div>
        </div>

        {/* Title */}
        <h3 style={{
          textAlign: 'center',
          color: 'var(--text-primary)',
          fontSize: '1.05rem',
          fontWeight: 700,
          marginBottom: '0.75rem',
        }}>
          {t('modal.supprimer_decision')}
        </h3>

        {/* Message */}
        <p style={{
          textAlign: 'center',
          color: 'var(--text-secondary)',
          fontSize: '0.85rem',
          lineHeight: 1.6,
          marginBottom: '1.75rem',
        }}>
          {t('modal.supprimer_desc')}
        </p>

        {/* Buttons */}
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1,
              padding: '0.7rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
          >
            {t('common.annuler')}
          </button>
          <button
            onClick={onConfirm}
            style={{
              flex: 1,
              padding: '0.7rem',
              borderRadius: 'var(--radius-md)',
              border: 'none',
              background: 'var(--danger)',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 600,
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = '#dc2626' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = '#ef4444' }}
          >
            {t('stats.supprimer')}
          </button>
        </div>
      </div>
    </div>
  )
}
