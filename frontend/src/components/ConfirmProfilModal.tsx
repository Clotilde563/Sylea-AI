// Modale de confirmation avant modification du profil

interface ConfirmProfilModalProps {
  visible: boolean
  onConfirm: () => void
  onCancel: () => void
  title?: string
  message?: string
}

export function ConfirmProfilModal({ visible, onConfirm, onCancel, title, message }: ConfirmProfilModalProps) {
  if (!visible) return null

  return (
    <div
      onClick={onCancel}
      style={{
        position: 'fixed', inset: 0, zIndex: 9000,
        background: 'rgba(2, 5, 9, 0.85)',
        backdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        animation: 'fadeIn 0.15s ease',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '2rem',
          maxWidth: 440, width: '90%',
          boxShadow: 'var(--shadow-card)',
          animation: 'fadeInScale 0.2s ease',
        }}
      >
        {/* Icône warning */}
        <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            background: 'rgba(234,179,8,0.15)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#eab308" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
        </div>

        <h3 style={{ textAlign: 'center', fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.75rem' }}>
          {title || 'Modifier mon profil ?'}
        </h3>

        <div style={{ textAlign: 'center', fontSize: '0.85rem', lineHeight: 1.7, color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
          {message || (
            <>
              <p style={{ marginBottom: '0.5rem' }}>
                Modifier vos <strong style={{ color: 'var(--text-primary)' }}>informations personnelles</strong> entraînera un recalcul de votre probabilité.
              </p>
              <p>
                Modifier votre <strong style={{ color: '#ef4444' }}>objectif de vie</strong> réinitialisera <span style={{ color: '#ef4444' }}>tout votre historique</span> (décisions, sous-objectifs, tâches).
              </p>
            </>
          )}
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, padding: '0.7rem', borderRadius: 'var(--radius-md)',
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.85rem',
            }}
          >Annuler</button>
          <button
            onClick={onConfirm}
            style={{
              flex: 1, padding: '0.7rem', borderRadius: 'var(--radius-md)',
              background: 'var(--accent-violet)', border: 'none',
              color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem',
            }}
          >Continuer</button>
        </div>
      </div>
    </div>
  )
}
