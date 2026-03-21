import { useT } from '../i18n/LanguageContext'

export default function AgentsPage() {
  const t = useT()

  return (
    <div className="page animate-fade-in">
      <div className="container page-content" style={{ maxWidth: 680, margin: '0 auto', padding: '2rem 1rem', textAlign: 'center' }}>
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{
            fontSize: '1.5rem', fontWeight: 800, marginBottom: '0.5rem',
            background: 'linear-gradient(90deg, #3b82f6, #8b5cf6, #ef4444, #f59e0b)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          }}>
            {t('nav.agents')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            Vos assistants IA personnels — bientot disponible
          </p>
        </div>

        <div style={{
          padding: '3rem 2rem', borderRadius: '1rem',
          background: 'var(--bg-surface)', border: '1px solid var(--border)',
        }}>
          <div style={{
            width: 80, height: 80, borderRadius: '50%', margin: '0 auto 1.5rem',
            background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.15), rgba(239,68,68,0.15))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '2px solid rgba(139,92,246,0.2)',
          }}>
            <svg width={36} height={36} viewBox="0 0 24 24" fill="none"
              stroke="url(#agent-gradient)" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
              <defs>
                <linearGradient id="agent-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#3b82f6" />
                  <stop offset="50%" stopColor="#8b5cf6" />
                  <stop offset="100%" stopColor="#ef4444" />
                </linearGradient>
              </defs>
              <path d="M12 2a4 4 0 0 1 4 4v1a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z" />
              <path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
              <circle cx="19" cy="8" r="2" />
              <path d="M19 10v1a2 2 0 0 0 2 2" />
              <circle cx="5" cy="8" r="2" />
              <path d="M5 10v1a2 2 0 0 1-2 2" />
            </svg>
          </div>

          <p style={{
            fontSize: '0.95rem', color: 'var(--text-secondary)', lineHeight: 1.6,
            maxWidth: 400, margin: '0 auto',
          }}>
            Les agents Sylea.AI automatiseront vos taches quotidiennes : emails, recherches, calendrier et bien plus encore.
          </p>

          <div style={{
            marginTop: '1.5rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
            padding: '0.4rem 1rem', borderRadius: '999px', fontSize: '0.75rem', fontWeight: 600,
            background: 'linear-gradient(135deg, rgba(59,130,246,0.1), rgba(139,92,246,0.1), rgba(239,68,68,0.1))',
            border: '1px solid rgba(139,92,246,0.2)',
            color: '#a78bfa',
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: '#8b5cf6',
              animation: 'pulse 2s ease-in-out infinite',
            }} />
            En cours de developpement
          </div>
        </div>
      </div>
    </div>
  )
}
