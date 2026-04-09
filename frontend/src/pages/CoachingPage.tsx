// Page Coaching Vocal — Sessions, preferences, historique
import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'

// ── Types locaux ────────────────────────────────────────────────────────────
interface SessionPreference {
  id: string
  label: string
  description: string
  enabled: boolean
  time?: string
  day?: number
}

interface CoachingSession {
  id: string
  type: string
  date: string
  summary: string
  transcript?: string
  duration_minutes?: number
}

interface PendingSession {
  type: string
  scheduled_at: string
}

// ── Icones SVG ──────────────────────────────────────────────────────────────
function IconMic({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function IconCalendar({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )
}

function IconClock({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

function IconPlay({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  )
}

function IconX({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function IconChevron({ size = 14, direction = 'down' }: { size?: number; direction?: 'down' | 'up' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ transform: direction === 'up' ? 'rotate(180deg)' : undefined, transition: 'transform 0.2s' }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ── Sylea Logo for voice overlay ────────────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY - 105} C ${CX + 90} ${CY - 105}, ${CX + 90} ${CY - 28}, ${CX} ${CY} C ${CX - 90} ${CY + 28}, ${CX - 90} ${CY + 105}, ${CX} ${CY + 105}`

function SyleaLogoAnimated({ size = 140 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="coaching-logo-g" x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#7c3aed" />
          <stop offset="40%" stopColor="#8b5cf6" />
          <stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>
        <filter id="coaching-logo-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      {/* Animated halo */}
      <path
        d={S_PATH}
        stroke="url(#coaching-logo-g)"
        strokeWidth="90"
        fill="none"
        strokeLinecap="round"
        style={{ filter: 'url(#coaching-logo-glow)', opacity: 0.25 }}
      >
        <animate attributeName="opacity" values="0.15;0.35;0.15" dur="2s" repeatCount="indefinite" />
      </path>
      {/* Main S */}
      <path
        d={S_PATH}
        stroke="url(#coaching-logo-g)"
        strokeWidth="28"
        fill="none"
        strokeLinecap="round"
      />
      {/* Specular */}
      <path
        d={S_PATH}
        stroke="rgba(200,180,255,0.4)"
        strokeWidth="2.5"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────
const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '0.75rem',
  padding: '1.25rem',
}

const btnPrimary: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.4rem',
  padding: '0.5rem 1rem',
  borderRadius: '0.5rem',
  border: '1px solid var(--accent-violet)',
  background: 'rgba(139,92,246,0.15)',
  color: '#a78bfa',
  fontSize: '0.8rem',
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'all 0.15s',
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })} a ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`
}

function countdown(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return 'Maintenant'
  const hours = Math.floor(diff / 3600000)
  const mins = Math.floor((diff % 3600000) / 60000)
  if (hours > 24) {
    const days = Math.floor(hours / 24)
    return `dans ${days} jour${days > 1 ? 's' : ''}`
  }
  if (hours > 0) return `dans ${hours}h${mins > 0 ? ` ${mins}min` : ''}`
  return `dans ${mins} minute${mins > 1 ? 's' : ''}`
}

const SESSION_TYPES = [
  { type: 'monday_motivation', label: 'Motivation du lundi', icon: '\u2605', color: '#f59e0b' },
  { type: 'sunday_review', label: 'Bilan du dimanche', icon: '\u2610', color: '#3b82f6' },
  { type: 'monthly_recap', label: 'Recap mensuel', icon: '\u25C8', color: '#8b5cf6' },
  { type: 'yearly_recap', label: 'Bilan annuel', icon: '\u2726', color: '#22c55e' },
]

function sessionLabel(type: string): string {
  return SESSION_TYPES.find(s => s.type === type)?.label || type
}

function sessionColor(type: string): string {
  return SESSION_TYPES.find(s => s.type === type)?.color || '#8b5cf6'
}

function sessionIcon(type: string): string {
  return SESSION_TYPES.find(s => s.type === type)?.icon || '\u25C8'
}

// ── Composant principal ─────────────────────────────────────────────────────
export default function CoachingPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Preferences
  const [preferences, setPreferences] = useState<SessionPreference[]>([
    { id: 'monday_motivation', label: 'Motivation du lundi', description: 'Session de motivation pour bien commencer la semaine', enabled: true, time: '08:00' },
    { id: 'sunday_review', label: 'Bilan du dimanche', description: 'Faites le point sur votre semaine écoulée', enabled: true, time: '19:00' },
    { id: 'monthly_recap', label: 'Recap mensuel', description: 'Revue mensuelle de vos progrès', enabled: true, day: 1 },
    { id: 'yearly_recap', label: 'Bilan annuel', description: 'Bilan complet de votre année', enabled: true },
  ])

  // Sessions
  const [sessions, setSessions] = useState<CoachingSession[]>([])
  const [pendingSession, setPendingSession] = useState<PendingSession | null>(null)
  const [expandedSession, setExpandedSession] = useState<string | null>(null)

  // Voice overlay
  const [voiceActive, setVoiceActive] = useState(false)
  const [voiceType, setVoiceType] = useState<string>('motivation_lundi')
  const [voiceTranscript, setVoiceTranscript] = useState<string[]>([])
  const [startDropdown, setStartDropdown] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadAll()
  }, [])

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [voiceTranscript])

  async function loadAll() {
    setLoading(true)
    try {
      const [prefs, sessionsData, pending] = await Promise.all([
        api.getCoachingPreferences().catch(() => null),
        api.getCoachingSessions().catch(() => []),
        api.getPendingSession().catch(() => null),
      ])
      if (prefs && prefs.sessions) {
        setPreferences(prefs.sessions)
      }
      setSessions(Array.isArray(sessionsData) ? sessionsData : [])
      // API returns {pending: [...], count: N} — transform to PendingSession or null
      if (pending && Array.isArray(pending.pending) && pending.pending.length > 0) {
        const nextType = pending.pending[0]
        // Calculate a plausible next scheduled time
        const now = new Date()
        const nextDate = new Date(now)
        // Set next session time based on type
        if (nextType === 'monday_motivation') { nextDate.setHours(8, 0, 0, 0); while (nextDate.getDay() !== 1 || nextDate <= now) nextDate.setDate(nextDate.getDate() + 1) }
        else if (nextType === 'sunday_review') { nextDate.setHours(19, 0, 0, 0); while (nextDate.getDay() !== 0 || nextDate <= now) nextDate.setDate(nextDate.getDate() + 1) }
        else if (nextType === 'monthly_recap') { nextDate.setDate(1); nextDate.setHours(9, 0, 0, 0); if (nextDate <= now) nextDate.setMonth(nextDate.getMonth() + 1) }
        else if (nextType === 'yearly_recap') { nextDate.setMonth(0, 1); nextDate.setHours(10, 0, 0, 0); if (nextDate <= now) nextDate.setFullYear(nextDate.getFullYear() + 1) }
        else { nextDate.setDate(nextDate.getDate() + 1); nextDate.setHours(8, 0, 0, 0) }
        setPendingSession({ type: nextType, scheduled_at: nextDate.toISOString() })
      } else {
        setPendingSession(null)
      }
    } catch {
      // use defaults
    } finally {
      setLoading(false)
    }
  }

  async function togglePreference(id: string) {
    const updated = preferences.map(p =>
      p.id === id ? { ...p, enabled: !p.enabled } : p
    )
    setPreferences(updated)
    try {
      await api.updateCoachingPreferences({ sessions: updated })
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || e?.detail || 'Erreur inconnue'))
    }
  }

  async function updateTime(id: string, time: string) {
    const updated = preferences.map(p =>
      p.id === id ? { ...p, time } : p
    )
    setPreferences(updated)
    try {
      await api.updateCoachingPreferences({ sessions: updated })
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || e?.detail || 'Erreur inconnue'))
    }
  }

  async function updateDay(id: string, day: number) {
    const updated = preferences.map(p =>
      p.id === id ? { ...p, day } : p
    )
    setPreferences(updated)
    try {
      await api.updateCoachingPreferences({ sessions: updated })
    } catch (e: any) {
      setError(typeof e === 'string' ? e : (e?.message || e?.detail || 'Erreur inconnue'))
    }
  }

  async function handleStartSession(type: string) {
    setStartDropdown(false)
    setVoiceType(type)
    setVoiceTranscript([])
    setVoiceActive(true)
    try {
      const result = await api.startCoachingSession(type)
      if (result && result.transcript) {
        // Simulate progressive transcript display
        const lines = result.transcript.split('\n').filter((l: string) => l.trim())
        for (let i = 0; i < lines.length; i++) {
          await new Promise(resolve => setTimeout(resolve, 800))
          setVoiceTranscript(prev => [...prev, lines[i]])
        }
      } else {
        setVoiceTranscript(['Session démarrée. Syléa est en cours de réflexion...'])
      }
    } catch (e: any) {
      const errMsg = typeof e === 'string' ? e : (e?.message || e?.detail || JSON.stringify(e))
      setVoiceTranscript(prev => [...prev, `Erreur: ${errMsg}`])
    }
  }

  function closeVoice() {
    setVoiceActive(false)
    setVoiceTranscript([])
    loadAll() // reload sessions
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* Header */}
        <div style={{ marginBottom: '2rem' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '0.25rem' }}>
            Accompagnement personnalisé
          </p>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.25rem' }}>
            Coaching Vocal
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Sessions de coaching automatiques et à la demande avec Syléa
          </p>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            padding: '0.75rem 1rem',
            borderRadius: '0.5rem',
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.3)',
            color: '#f87171',
            fontSize: '0.8rem',
            marginBottom: '1rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span>{error}</span>
            <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}>
              <IconX size={14} />
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
            <div className="spinner" style={{ margin: '0 auto 1rem' }} />
            Chargement...
          </div>
        )}

        {!loading && (
          <>
            {/* ── Schedule Section ── */}
            <div style={{ marginBottom: '1.5rem' }}>
              <h2 style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-violet-light)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                {'\u25C8'} Planification des sessions
              </h2>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '0.75rem' }}>
                {preferences.map(pref => (
                  <div key={pref.id} style={{
                    ...cardStyle,
                    borderColor: pref.enabled ? `${sessionColor(pref.id)}40` : 'var(--border)',
                    transition: 'all 0.2s',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '1rem', color: sessionColor(pref.id) }}>
                          {sessionIcon(pref.id)}
                        </span>
                        <h3 style={{ fontSize: '0.88rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
                          {pref.label}
                        </h3>
                      </div>
                      {/* Toggle */}
                      <button
                        onClick={() => togglePreference(pref.id)}
                        style={{
                          width: 40,
                          height: 22,
                          borderRadius: 11,
                          border: 'none',
                          background: pref.enabled ? sessionColor(pref.id) : 'var(--border)',
                          cursor: 'pointer',
                          position: 'relative',
                          transition: 'background 0.2s',
                        }}
                      >
                        <span style={{
                          position: 'absolute',
                          top: 2,
                          left: pref.enabled ? 20 : 2,
                          width: 18,
                          height: 18,
                          borderRadius: '50%',
                          background: '#fff',
                          transition: 'left 0.2s',
                          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                        }} />
                      </button>
                    </div>

                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.4, marginBottom: '0.5rem' }}>
                      {pref.description}
                    </p>

                    {/* Time picker for daily sessions */}
                    {pref.time !== undefined && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <IconClock size={13} />
                        <input
                          type="time"
                          value={pref.time}
                          onChange={e => updateTime(pref.id, e.target.value)}
                          disabled={!pref.enabled}
                          style={{
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border)',
                            borderRadius: '0.35rem',
                            color: pref.enabled ? 'var(--text-primary)' : 'var(--text-muted)',
                            padding: '0.25rem 0.5rem',
                            fontSize: '0.78rem',
                            outline: 'none',
                            opacity: pref.enabled ? 1 : 0.5,
                          }}
                        />
                      </div>
                    )}

                    {/* Day picker for monthly session */}
                    {pref.day !== undefined && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <IconCalendar size={13} />
                        <select
                          value={pref.day}
                          onChange={e => updateDay(pref.id, parseInt(e.target.value))}
                          disabled={!pref.enabled}
                          style={{
                            background: 'var(--bg-surface)',
                            border: '1px solid var(--border)',
                            borderRadius: '0.35rem',
                            color: pref.enabled ? 'var(--text-primary)' : 'var(--text-muted)',
                            padding: '0.25rem 0.5rem',
                            fontSize: '0.78rem',
                            outline: 'none',
                            opacity: pref.enabled ? 1 : 0.5,
                          }}
                        >
                          {Array.from({ length: 28 }, (_, i) => (
                            <option key={i + 1} value={i + 1}>Le {i + 1}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* ── Next session card ── */}
            {pendingSession && (
              <div style={{
                ...cardStyle,
                marginBottom: '1.5rem',
                background: 'linear-gradient(135deg, var(--bg-surface), #0b1525)',
                border: '1px solid rgba(139,92,246,0.3)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '0.75rem',
              }}>
                <div>
                  <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.25rem' }}>
                    Prochaine session
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '1rem', color: sessionColor(pendingSession.type) }}>
                      {sessionIcon(pendingSession.type)}
                    </span>
                    <span style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {sessionLabel(pendingSession.type)}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    {formatDateTime(pendingSession.scheduled_at)}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#a78bfa' }}>
                    {countdown(pendingSession.scheduled_at)}
                  </div>
                </div>
              </div>
            )}

            {/* ── Session History ── */}
            <div style={{ marginBottom: '1.5rem' }}>
              <h2 style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-violet-light)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                {'\u25C8'} Historique des sessions
              </h2>

              {sessions.length === 0 ? (
                <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                  <IconMic size={36} />
                  <p style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>Aucune session passée</p>
                  <p style={{ fontSize: '0.75rem' }}>Démarrez votre première session de coaching vocal</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {sessions.map(session => {
                    const isExpanded = expandedSession === session.id
                    return (
                      <div key={session.id} style={cardStyle}>
                        <button
                          onClick={() => setExpandedSession(isExpanded ? null : session.id)}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            width: '100%',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: 0,
                            color: 'inherit',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <span style={{
                              width: 32,
                              height: 32,
                              borderRadius: '0.5rem',
                              background: `${sessionColor(session.type)}15`,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontSize: '0.9rem',
                              color: sessionColor(session.type),
                              flexShrink: 0,
                            }}>
                              {sessionIcon(session.type)}
                            </span>
                            <div style={{ textAlign: 'left' }}>
                              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                                {sessionLabel(session.type)}
                              </div>
                              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                {formatDate(session.date)}
                                {session.duration_minutes ? ` \u00B7 ${session.duration_minutes} min` : ''}
                              </div>
                            </div>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {!isExpanded ? session.summary : ''}
                            </span>
                            <span style={{ color: 'var(--text-muted)' }}>
                              <IconChevron size={14} direction={isExpanded ? 'up' : 'down'} />
                            </span>
                          </div>
                        </button>

                        {isExpanded && (
                          <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px solid var(--border)' }}>
                            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 }}>
                              {session.summary}
                            </p>
                            {session.transcript && (
                              <div style={{
                                marginTop: '0.75rem',
                                padding: '0.75rem',
                                background: 'var(--bg-surface)',
                                borderRadius: '0.5rem',
                                border: '1px solid var(--border)',
                                fontSize: '0.78rem',
                                color: 'var(--text-muted)',
                                lineHeight: 1.5,
                                maxHeight: '200px',
                                overflowY: 'auto',
                                whiteSpace: 'pre-wrap',
                              }}>
                                {session.transcript}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </>
        )}

        {/* ── Voice Call Overlay ── */}
        {voiceActive && (
          <div style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(5,5,15,0.95)',
            zIndex: 200,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            backdropFilter: 'blur(12px)',
          }}>
            {/* Close */}
            <button
              onClick={closeVoice}
              style={{
                position: 'absolute',
                top: '1.5rem',
                right: '1.5rem',
                background: 'rgba(255,255,255,0.1)',
                border: '1px solid rgba(255,255,255,0.15)',
                borderRadius: '50%',
                width: 40,
                height: 40,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                color: '#fff',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.2)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.1)')}
            >
              <IconX size={18} />
            </button>

            {/* Logo animation */}
            <div style={{ marginBottom: '1.5rem' }}>
              <SyleaLogoAnimated size={140} />
            </div>

            {/* Session type */}
            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: sessionColor(voiceType), marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              {sessionLabel(voiceType)}
            </div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginBottom: '1.5rem' }}>
              Session en cours...
            </div>

            {/* Transcript */}
            <div
              ref={transcriptRef}
              style={{
                width: '90%',
                maxWidth: '500px',
                maxHeight: '250px',
                overflowY: 'auto',
                padding: '1rem',
                background: 'rgba(255,255,255,0.03)',
                borderRadius: '0.75rem',
                border: '1px solid rgba(255,255,255,0.08)',
              }}
            >
              {voiceTranscript.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.3)', fontSize: '0.85rem' }}>
                  <div className="spinner" style={{ margin: '0 auto 0.5rem', borderColor: 'rgba(139,92,246,0.3)', borderTopColor: '#a78bfa' }} />
                  Connexion a Sylea...
                </div>
              ) : (
                voiceTranscript.map((line, i) => (
                  <p key={i} style={{
                    fontSize: '0.85rem',
                    color: 'rgba(255,255,255,0.8)',
                    lineHeight: 1.5,
                    marginBottom: '0.4rem',
                    animation: 'fadeIn 0.4s ease',
                  }}>
                    {line}
                  </p>
                ))
              )}
            </div>

            {/* Mic indicator */}
            <div style={{
              marginTop: '1.5rem',
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'linear-gradient(135deg, rgba(139,92,246,0.3), rgba(139,92,246,0.1))',
              border: '2px solid rgba(139,92,246,0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#a78bfa',
            }}>
              <IconMic size={24} />
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
