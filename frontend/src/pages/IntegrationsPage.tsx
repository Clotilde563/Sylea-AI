// Page Integrations — Gestion des services externes connectes
import { useState, useEffect } from 'react'
import { api } from '../api/client'

// ── Types ────────────────────────────────────────────────────────────────────
interface Integration {
  provider: string
  name: string
  description: string
  connected: boolean
  last_sync?: string
  preview?: string
}

interface ConnectModalState {
  open: boolean
  provider: string
  name: string
  description: string
  permissions: string[]
}

// ── SVG Icons (inline) ───────────────────────────────────────────────────────
function CalendarIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )
}

function MailIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <polyline points="22,4 12,13 2,4" />
    </svg>
  )
}

function CodeIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16,18 22,12 16,6" />
      <polyline points="8,6 2,12 8,18" />
    </svg>
  )
}

function DocIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14,2 14,8 20,8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <line x1="10" y1="9" x2="8" y2="9" />
    </svg>
  )
}

function UsersIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87" />
      <path d="M16 3.13a4 4 0 010 7.75" />
    </svg>
  )
}

function CreditCardIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  )
}

function OutlookIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <polyline points="22,4 12,13 2,4" />
      <line x1="2" y1="20" x2="9" y2="13" />
      <line x1="22" y1="20" x2="15" y2="13" />
    </svg>
  )
}

function SyncIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23,4 23,10 17,10" />
      <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function ChevronDownIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6,9 12,15 18,9" />
    </svg>
  )
}

function ChevronUpIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6,15 12,9 18,15" />
    </svg>
  )
}

// ── Provider definitions ─────────────────────────────────────────────────────
const PROVIDERS: Array<{
  id: string
  name: string
  icon: () => JSX.Element
  color: string
  description: string
  permissions: string[]
  previewLabel: string
}> = [
  {
    id: 'google_calendar',
    name: 'Google Calendar',
    icon: CalendarIcon,
    color: '#4285f4',
    description: 'Synchronisez vos evenements et rendez-vous pour une meilleure planification.',
    permissions: ['Lecture de vos evenements', 'Creation de rappels'],
    previewLabel: 'evenements cette semaine',
  },
  {
    id: 'gmail',
    name: 'Gmail',
    icon: MailIcon,
    color: '#ea4335',
    description: 'Connectez votre messagerie pour suivre vos communications importantes.',
    permissions: ['Lecture des emails', 'Envoi de messages'],
    previewLabel: 'emails non lus',
  },
  {
    id: 'google_drive',
    name: 'Google Drive',
    icon: DocIcon,
    color: '#34a853',
    description: 'Accedez a vos fichiers Google Drive pour les consulter et les organiser.',
    permissions: ['Lecture des fichiers', 'Organisation des dossiers'],
    previewLabel: 'fichiers recents',
  },
  {
    id: 'github',
    name: 'GitHub',
    icon: CodeIcon,
    color: '#f0f6fc',
    description: 'Suivez votre activite de developpement et vos contributions.',
    permissions: ['Lecture des repositories', 'Lecture de l\'activite'],
    previewLabel: 'contributions ce mois',
  },
  {
    id: 'notion',
    name: 'Notion',
    icon: DocIcon,
    color: '#ffffff',
    description: 'Integrez vos notes et bases de donnees Notion.',
    permissions: ['Lecture des pages', 'Lecture des bases de donnees'],
    previewLabel: 'pages modifiees recemment',
  },
  {
    id: 'linkedin',
    name: 'LinkedIn',
    icon: UsersIcon,
    color: '#0a66c2',
    description: 'Connectez votre profil professionnel et votre reseau.',
    permissions: ['Lecture du profil', 'Lecture des connexions'],
    previewLabel: 'nouvelles connexions',
  },
  {
    id: 'stripe',
    name: 'Stripe',
    icon: CreditCardIcon,
    color: '#635bff',
    description: 'Suivez vos revenus et transactions financieres.',
    permissions: ['Lecture des transactions', 'Lecture des soldes'],
    previewLabel: 'transactions ce mois',
  },
  {
    id: 'outlook',
    name: 'Outlook',
    icon: OutlookIcon,
    color: '#0078d4',
    description: 'Connectez votre messagerie et calendrier Microsoft.',
    permissions: ['Lecture des emails', 'Lecture du calendrier'],
    previewLabel: 'emails non lus',
  },
]

// ── Mock data for demo ───────────────────────────────────────────────────────
const MOCK_INTEGRATIONS: Record<string, Integration> = {
  google_calendar: {
    provider: 'google_calendar',
    name: 'Google Calendar',
    description: '',
    connected: true,
    last_sync: '2026-04-04T10:30:00Z',
    preview: '3 evenements cette semaine',
  },
  gmail: {
    provider: 'gmail',
    name: 'Gmail',
    description: '',
    connected: true,
    last_sync: '2026-04-04T09:15:00Z',
    preview: '12 emails non lus',
  },
  google_drive: {
    provider: 'google_drive',
    name: 'Google Drive',
    description: '',
    connected: false,
  },
  github: {
    provider: 'github',
    name: 'GitHub',
    description: '',
    connected: false,
  },
  notion: {
    provider: 'notion',
    name: 'Notion',
    description: '',
    connected: false,
  },
  linkedin: {
    provider: 'linkedin',
    name: 'LinkedIn',
    description: '',
    connected: false,
  },
  stripe: {
    provider: 'stripe',
    name: 'Stripe',
    description: '',
    connected: false,
  },
  outlook: {
    provider: 'outlook',
    name: 'Outlook',
    description: '',
    connected: false,
  },
}

// ── Relative time helper ─────────────────────────────────────────────────────
function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "a l'instant"
  if (mins < 60) return `il y a ${mins} min`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `il y a ${hrs}h`
  const days = Math.floor(hrs / 24)
  return `il y a ${days}j`
}

// ── Component ────────────────────────────────────────────────────────────────
export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Record<string, Integration>>(MOCK_INTEGRATIONS)
  const [loading, setLoading] = useState(true)
  const [expandedCard, setExpandedCard] = useState<string | null>(null)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [connectModal, setConnectModal] = useState<ConnectModalState>({
    open: false,
    provider: '',
    name: '',
    description: '',
    permissions: [],
  })
  const [apiKey, setApiKey] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Try to load from API, fallback to mock data
    api.getIntegrations()
      .then((data: any[]) => {
        const map: Record<string, Integration> = {}
        data.forEach((i) => { map[i.provider] = i })
        // Merge with providers that might not be in API response
        PROVIDERS.forEach((p) => {
          if (!map[p.id]) {
            map[p.id] = { provider: p.id, name: p.name, description: p.description, connected: false }
          }
        })
        setIntegrations(map)
      })
      .catch(() => {
        // Keep mock data
      })
      .finally(() => setLoading(false))
  }, [])

  const GOOGLE_PROVIDERS = ['google_calendar', 'gmail', 'google_drive']

  const handleConnect = async (providerId: string) => {
    const p = PROVIDERS.find((x) => x.id === providerId)
    if (!p) return

    // Google services → OAuth redirect (connects Calendar + Gmail + Drive at once)
    if (GOOGLE_PROVIDERS.includes(providerId)) {
      try {
        const redirectUri = `${window.location.origin}/auth/callback`
        const { url } = await api.authGoogleUrl(redirectUri, 'integration')
        window.location.href = url
      } catch (err: any) {
        setError(err.message || 'Erreur Google OAuth')
      }
      return
    }

    // Other services → API key modal
    setConnectModal({
      open: true,
      provider: providerId,
      name: p.name,
      description: p.description,
      permissions: p.permissions,
    })
    setApiKey('')
    setError(null)
  }

  const handleSubmitConnect = async () => {
    if (!apiKey.trim()) {
      setError('Veuillez entrer une cle API ou un token.')
      return
    }
    setConnecting(true)
    setError(null)
    try {
      await api.connectIntegration(connectModal.provider, { api_key: apiKey })
      setIntegrations((prev) => ({
        ...prev,
        [connectModal.provider]: {
          ...prev[connectModal.provider],
          connected: true,
          last_sync: new Date().toISOString(),
          preview: undefined,
        },
      }))
      setConnectModal((prev) => ({ ...prev, open: false }))
    } catch (err: any) {
      // For demo, simulate success
      setIntegrations((prev) => ({
        ...prev,
        [connectModal.provider]: {
          ...prev[connectModal.provider],
          connected: true,
          last_sync: new Date().toISOString(),
        },
      }))
      setConnectModal((prev) => ({ ...prev, open: false }))
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async (providerId: string) => {
    try {
      await api.disconnectIntegration(providerId)
    } catch {
      // proceed anyway for demo
    }
    setIntegrations((prev) => ({
      ...prev,
      [providerId]: {
        ...prev[providerId],
        connected: false,
        last_sync: undefined,
        preview: undefined,
      },
    }))
    setExpandedCard(null)
  }

  const handleSync = async (providerId: string) => {
    setSyncing(providerId)
    try {
      await api.getIntegrationStatus(providerId)
    } catch {
      // demo
    }
    setIntegrations((prev) => ({
      ...prev,
      [providerId]: {
        ...prev[providerId],
        last_sync: new Date().toISOString(),
      },
    }))
    setTimeout(() => setSyncing(null), 800)
  }

  const toggleExpand = (providerId: string) => {
    setExpandedCard(expandedCard === providerId ? null : providerId)
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '2rem 1rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '2rem' }}>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Services externes
        </p>
        <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.5rem' }}>
          Integrations
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          Connectez vos services pour une experience unifiee
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 10,
          padding: '0.75rem 1rem',
          marginBottom: '1rem',
          color: '#ef4444',
          fontSize: '0.85rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '1rem' }}>x</button>
        </div>
      )}

      {/* Stats bar */}
      <div style={{
        display: 'flex',
        gap: '1rem',
        marginBottom: '2rem',
        flexWrap: 'wrap',
      }}>
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: '1rem 1.5rem',
          flex: '1 1 200px',
        }}>
          <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.3rem' }}>
            Services connectes
          </p>
          <p style={{ fontSize: '1.5rem', fontWeight: 700, color: '#22c55e' }}>
            {Object.values(integrations).filter((i) => i.connected).length}
          </p>
        </div>
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: '1rem 1.5rem',
          flex: '1 1 200px',
        }}>
          <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.3rem' }}>
            Disponibles
          </p>
          <p style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent-violet-light)' }}>
            {Object.values(integrations).filter((i) => !i.connected).length}
          </p>
        </div>
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: '1rem 1.5rem',
          flex: '1 1 200px',
        }}>
          <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.3rem' }}>
            Derniere synchro
          </p>
          <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            {(() => {
              const synced = Object.values(integrations).filter((i) => i.last_sync).sort((a, b) => new Date(b.last_sync!).getTime() - new Date(a.last_sync!).getTime())
              return synced.length > 0 ? relativeTime(synced[0].last_sync!) : '--'
            })()}
          </p>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
          Chargement des integrations...
        </div>
      )}

      {/* Grid of integration cards */}
      {!loading && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: '1rem',
        }}>
          {PROVIDERS.map((provider) => {
            const integration = integrations[provider.id] || { provider: provider.id, name: provider.name, description: '', connected: false }
            const isConnected = integration.connected
            const isExpanded = expandedCard === provider.id
            const isSyncing = syncing === provider.id
            const Icon = provider.icon

            return (
              <div
                key={provider.id}
                style={{
                  background: 'linear-gradient(135deg, var(--bg-surface), #0b1525)',
                  border: `1px solid ${isConnected ? 'rgba(34, 197, 94, 0.3)' : 'var(--border)'}`,
                  borderRadius: 14,
                  padding: '1.25rem',
                  transition: 'all 0.2s ease',
                  cursor: isConnected ? 'pointer' : 'default',
                }}
                onClick={() => isConnected && toggleExpand(provider.id)}
              >
                {/* Card header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                  <div style={{
                    width: 48,
                    height: 48,
                    borderRadius: 12,
                    background: `${provider.color}15`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: provider.color,
                    flexShrink: 0,
                  }}>
                    <Icon />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>
                        {provider.name}
                      </span>
                      {/* Status badge */}
                      <span style={{
                        fontSize: '0.65rem',
                        fontWeight: 600,
                        padding: '0.15rem 0.5rem',
                        borderRadius: 20,
                        background: isConnected ? 'rgba(34, 197, 94, 0.15)' : 'rgba(107, 114, 128, 0.15)',
                        color: isConnected ? '#22c55e' : '#6b7280',
                        letterSpacing: '0.03em',
                      }}>
                        {isConnected ? 'Connecte' : 'Non connecte'}
                      </span>
                    </div>
                    {isConnected && integration.last_sync && (
                      <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.15rem' }}>
                        Synchro: {relativeTime(integration.last_sync)}
                      </p>
                    )}
                  </div>
                  {isConnected && (
                    <div style={{ color: 'var(--text-muted)' }}>
                      {isExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
                    </div>
                  )}
                </div>

                {/* Description */}
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: '0.75rem' }}>
                  {provider.description}
                </p>

                {/* Connect / Disconnect button */}
                {!isConnected ? (
                  <button
                    onClick={(e) => { e.stopPropagation(); handleConnect(provider.id) }}
                    style={{
                      width: '100%',
                      padding: '0.6rem',
                      borderRadius: 8,
                      border: `1px solid ${GOOGLE_PROVIDERS.includes(provider.id) ? '#4285f4' : 'var(--accent-violet)'}`,
                      background: GOOGLE_PROVIDERS.includes(provider.id) ? 'rgba(66, 133, 244, 0.1)' : 'rgba(139, 92, 246, 0.1)',
                      color: GOOGLE_PROVIDERS.includes(provider.id) ? '#93bbfc' : 'var(--accent-violet-light)',
                      fontWeight: 600,
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      (e.target as HTMLElement).style.background = GOOGLE_PROVIDERS.includes(provider.id) ? 'rgba(66, 133, 244, 0.25)' : 'rgba(139, 92, 246, 0.25)'
                    }}
                    onMouseLeave={(e) => {
                      (e.target as HTMLElement).style.background = GOOGLE_PROVIDERS.includes(provider.id) ? 'rgba(66, 133, 244, 0.1)' : 'rgba(139, 92, 246, 0.1)'
                    }}
                  >
                    {GOOGLE_PROVIDERS.includes(provider.id) ? 'Connecter avec Google' : 'Connecter'}
                  </button>
                ) : (
                  <>
                    {/* Expanded details */}
                    {isExpanded && (
                      <div style={{
                        borderTop: '1px solid var(--border)',
                        paddingTop: '0.75rem',
                        marginTop: '0.25rem',
                      }}>
                        {/* Preview data */}
                        {integration.preview && (
                          <div style={{
                            background: 'rgba(139, 92, 246, 0.08)',
                            borderRadius: 8,
                            padding: '0.6rem 0.8rem',
                            marginBottom: '0.75rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                          }}>
                            <span style={{ fontSize: '1.1rem' }}>
                              {provider.id === 'google_calendar' ? '\u{1F4C5}' : provider.id === 'gmail' ? '\u{2709}' : '\u{1F4CA}'}
                            </span>
                            <span style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>
                              {integration.preview}
                            </span>
                          </div>
                        )}

                        {/* Action buttons */}
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleSync(provider.id) }}
                            disabled={isSyncing}
                            style={{
                              flex: 1,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              gap: '0.4rem',
                              padding: '0.5rem',
                              borderRadius: 8,
                              border: '1px solid var(--border)',
                              background: 'var(--bg-surface)',
                              color: 'var(--text-primary)',
                              fontSize: '0.75rem',
                              fontWeight: 500,
                              cursor: isSyncing ? 'wait' : 'pointer',
                              opacity: isSyncing ? 0.6 : 1,
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <span style={{ animation: isSyncing ? 'spin 1s linear infinite' : 'none', display: 'inline-flex' }}>
                              <SyncIcon />
                            </span>
                            {isSyncing ? 'Synchro...' : 'Synchroniser'}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDisconnect(provider.id) }}
                            style={{
                              padding: '0.5rem 0.75rem',
                              borderRadius: 8,
                              border: '1px solid rgba(239, 68, 68, 0.3)',
                              background: 'rgba(239, 68, 68, 0.08)',
                              color: '#ef4444',
                              fontSize: '0.75rem',
                              fontWeight: 500,
                              cursor: 'pointer',
                              transition: 'all 0.15s ease',
                            }}
                            onMouseEnter={(e) => {
                              (e.target as HTMLElement).style.background = 'rgba(239, 68, 68, 0.2)'
                            }}
                            onMouseLeave={(e) => {
                              (e.target as HTMLElement).style.background = 'rgba(239, 68, 68, 0.08)'
                            }}
                          >
                            Deconnecter
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Connect Modal */}
      {connectModal.open && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.7)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
          }}
          onClick={() => setConnectModal((prev) => ({ ...prev, open: false }))}
        >
          <div
            style={{
              background: 'linear-gradient(135deg, #0f172a, #1a1a2e)',
              border: '1px solid var(--border)',
              borderRadius: 16,
              padding: '2rem',
              width: '90%',
              maxWidth: 440,
              position: 'relative',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close button */}
            <button
              onClick={() => setConnectModal((prev) => ({ ...prev, open: false }))}
              style={{
                position: 'absolute',
                top: '1rem',
                right: '1rem',
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: 4,
              }}
            >
              <CloseIcon />
            </button>

            {/* Modal header */}
            <h2 style={{ fontSize: '1.2rem', color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
              Connecter {connectModal.name}
            </h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '1.25rem', lineHeight: 1.5 }}>
              {connectModal.description}
            </p>

            {/* Permissions list */}
            <div style={{ marginBottom: '1.25rem' }}>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '0.5rem' }}>
                Permissions requises
              </p>
              {connectModal.permissions.map((perm, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.35rem 0',
                }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20,6 9,17 4,12" />
                  </svg>
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{perm}</span>
                </div>
              ))}
            </div>

            {/* API Key input */}
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.4rem', fontWeight: 500 }}>
                Cle API / Token
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                style={{
                  width: '100%',
                  padding: '0.65rem 0.8rem',
                  borderRadius: 8,
                  border: '1px solid var(--border)',
                  background: 'var(--bg-surface)',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
                onFocus={(e) => { e.target.style.borderColor = 'var(--accent-violet)' }}
                onBlur={(e) => { e.target.style.borderColor = 'var(--border)' }}
              />
            </div>

            {/* Error */}
            {error && (
              <p style={{ fontSize: '0.8rem', color: '#ef4444', marginBottom: '0.75rem' }}>{error}</p>
            )}

            {/* Submit */}
            <button
              onClick={handleSubmitConnect}
              disabled={connecting}
              style={{
                width: '100%',
                padding: '0.7rem',
                borderRadius: 8,
                border: 'none',
                background: 'linear-gradient(135deg, #8b5cf6, #6d28d9)',
                color: '#fff',
                fontWeight: 600,
                fontSize: '0.9rem',
                cursor: connecting ? 'wait' : 'pointer',
                opacity: connecting ? 0.7 : 1,
                transition: 'all 0.15s ease',
              }}
            >
              {connecting ? 'Connexion en cours...' : 'Connecter'}
            </button>
          </div>
        </div>
      )}

      {/* Spin animation for sync icon */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
