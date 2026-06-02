// Page "Mes dilemmes en cours" — design tech-addictif aux couleurs Sylea
// (violet #5520b8 → bleu #1848d8 → cyan #00c8ff). Animations, glow,
// glassmorphism, scan lines, holographic borders, micro-interactions.

import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { formatImpactJours } from '../utils/duration'
import type { TrackingItem, TrackingStatus } from '../types'

type StatusFilter = TrackingStatus | 'all'

// Palette officielle Sylea
const SYLEA = {
  violet: '#5520b8',
  blue: '#1848d8',
  cyan: '#00c8ff',
  cyanGlow: '#00c8ff80',
  violetGlow: '#7c3aedaa',
  dark: '#050810',
  surface: 'rgba(11,14,28,0.78)',
}

const STATUS_COLORS: Record<TrackingStatus, { ring: string; text: string; label: string; glow: string }> = {
  tracking:            { ring: SYLEA.cyan,   text: SYLEA.cyan,   label: 'EN COURS',   glow: SYLEA.cyan + '66' },
  awaiting_validation: { ring: '#fbbf24',    text: '#fbbf24',    label: 'À VALIDER',  glow: '#fbbf24aa' },
  validated:           { ring: '#22c55e',    text: '#4ade80',    label: 'VALIDÉ',     glow: '#22c55eaa' },
  cancelled:           { ring: '#94a3b8',    text: '#cbd5e1',    label: 'ABANDONNÉ',  glow: '#94a3b855' },
}

function formatCountdown(targetIso: string | null, now: number = Date.now()): string {
  if (!targetIso) return '—'
  const diff = new Date(targetIso).getTime() - now
  if (diff <= 0) return 'DUE'
  const d = Math.floor(diff / 86400000)
  const h = Math.floor((diff % 86400000) / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

// ─── Styles globaux + animations ────────────────────────────────────────────

const STYLES = `
  @keyframes sylea-grid {
    0% { background-position: 0 0, 0 0; }
    100% { background-position: 50px 50px, 50px 50px; }
  }
  @keyframes sylea-shimmer {
    0% { background-position: -200% 50%; }
    100% { background-position: 200% 50%; }
  }
  @keyframes sylea-pulse-ring {
    0%, 100% { box-shadow: 0 0 0 0 var(--ring), 0 0 14px var(--ring); }
    50%      { box-shadow: 0 0 0 4px transparent, 0 0 28px var(--ring); }
  }
  @keyframes sylea-pulse-soft {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50%      { opacity: 1;   transform: scale(1.03); }
  }
  @keyframes sylea-scan-h {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(200%); }
  }
  @keyframes sylea-float {
    0%, 100% { transform: translateY(0); }
    50%      { transform: translateY(-3px); }
  }
  @keyframes sylea-digit {
    from { transform: translateY(8px); opacity: 0; }
    to   { transform: translateY(0);   opacity: 1; }
  }
  @keyframes sylea-border-rotate {
    0% { background-position: 0% 0%; }
    100% { background-position: 200% 0%; }
  }
  @keyframes sylea-fade-in {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .sylea-tech-card {
    position: relative;
    background: linear-gradient(135deg, rgba(11,14,28,0.85), rgba(20,18,38,0.78), rgba(11,14,28,0.85));
    border: 1px solid rgba(0,200,255,0.12);
    border-radius: 16px;
    padding: 1.5rem 1.6rem;
    transition: transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.25s;
    overflow: hidden;
    backdrop-filter: blur(10px);
  }
  .sylea-tech-card::before {
    content: '';
    position: absolute;
    inset: -1px;
    border-radius: 16px;
    padding: 1px;
    background: linear-gradient(120deg, transparent 30%, var(--card-glow, #00c8ff66) 50%, transparent 70%);
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
            mask-composite: exclude;
    background-size: 200% 100%;
    opacity: 0.7;
    animation: sylea-shimmer 8s linear infinite;
    pointer-events: none;
  }
  .sylea-tech-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(0,200,255,0.15), 0 0 60px rgba(85,32,184,0.18);
  }
  .sylea-tech-card:hover::before {
    opacity: 1;
  }

  .sylea-grid-bg {
    background-image:
      linear-gradient(rgba(0,200,255,0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,200,255,0.04) 1px, transparent 1px);
    background-size: 50px 50px;
    animation: sylea-grid 18s linear infinite;
  }

  .sylea-chip {
    padding: 0.5rem 1rem 0.5rem 0.85rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.08);
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 0.82rem;
    font-weight: 500;
    display: flex; align-items: center; gap: 0.55rem;
    transition: all 0.2s;
    position: relative;
    overflow: hidden;
  }
  .sylea-chip:hover {
    background: rgba(0,200,255,0.07);
    border-color: rgba(0,200,255,0.25);
    transform: translateY(-1px);
  }
  .sylea-chip-active {
    background: linear-gradient(135deg, rgba(85,32,184,0.35), rgba(24,72,216,0.25), rgba(0,200,255,0.2)) !important;
    border-color: ${SYLEA.cyan} !important;
    color: #fff !important;
    box-shadow: 0 0 18px rgba(0,200,255,0.4), inset 0 1px 0 rgba(255,255,255,0.15);
  }
  .sylea-chip-count {
    background: rgba(255,255,255,0.08);
    padding: 0.05rem 0.55rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    font-family: var(--font-mono, ui-monospace, monospace);
  }
  .sylea-chip-active .sylea-chip-count {
    background: rgba(0,200,255,0.3);
    color: #fff;
  }

  .sylea-status-badge {
    --ring: var(--badge-ring, #00c8ff);
    padding: 0.25rem 0.8rem 0.25rem 0.75rem;
    border-radius: 999px;
    background: rgba(0,0,0,0.35);
    border: 1px solid var(--ring);
    color: var(--ring);
    font-size: 0.65rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-family: var(--font-mono, ui-monospace, monospace);
    display: inline-flex; align-items: center; gap: 0.45rem;
    box-shadow: 0 0 12px var(--ring), inset 0 0 8px rgba(0,0,0,0.3);
  }
  .sylea-status-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--ring);
    box-shadow: 0 0 8px var(--ring);
    animation: sylea-pulse-soft 1.8s ease-in-out infinite;
  }

  .sylea-progress-track {
    position: relative;
    height: 6px;
    background: rgba(255,255,255,0.04);
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid rgba(0,200,255,0.08);
  }
  .sylea-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, ${SYLEA.violet}, ${SYLEA.blue}, ${SYLEA.cyan});
    border-radius: 3px;
    box-shadow: 0 0 12px var(--ring, #00c8ff80);
    transition: width 0.5s cubic-bezier(0.2, 0.8, 0.2, 1);
    position: relative;
  }
  .sylea-progress-fill::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
    animation: sylea-scan-h 2.5s linear infinite;
  }

  .sylea-period-cell {
    width: 32px; height: 32px;
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.75rem;
    font-weight: 700;
    font-family: var(--font-mono, ui-monospace, monospace);
    transition: all 0.2s;
    border: 1px solid rgba(255,255,255,0.06);
    background: rgba(255,255,255,0.02);
    color: rgba(255,255,255,0.35);
    position: relative;
  }
  .sylea-period-cell-filled {
    background: linear-gradient(135deg, ${SYLEA.violet}aa, ${SYLEA.blue}cc) !important;
    border-color: ${SYLEA.cyan} !important;
    color: #fff !important;
    box-shadow: 0 0 12px ${SYLEA.cyan}66, inset 0 1px 0 rgba(255,255,255,0.2);
  }
  .sylea-period-cell-none {
    background: rgba(148,163,184,0.15) !important;
    border-color: rgba(148,163,184,0.3) !important;
    color: #cbd5e1 !important;
  }
  .sylea-period-cell-due {
    border: 2px solid #fbbf24 !important;
    background: rgba(251,191,36,0.1) !important;
    box-shadow: 0 0 16px rgba(251,191,36,0.5);
    animation: sylea-pulse-soft 1.4s ease-in-out infinite;
  }

  .sylea-action-btn {
    flex: 1;
    padding: 0.65rem 1rem;
    border-radius: 10px;
    border: 1px solid var(--btn-ring);
    background: var(--btn-bg, transparent);
    color: var(--btn-color);
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    display: flex; align-items: center; justify-content: center; gap: 0.45rem;
    position: relative;
    overflow: hidden;
  }
  .sylea-action-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px var(--btn-glow);
    background: var(--btn-bg-hover);
  }
  .sylea-action-btn-abandon {
    --btn-ring: rgba(251,191,36,0.4);
    --btn-color: #fbbf24;
    --btn-glow: rgba(251,191,36,0.3);
    --btn-bg-hover: rgba(251,191,36,0.1);
  }
  .sylea-action-btn-delete {
    --btn-ring: rgba(239,68,68,0.4);
    --btn-color: #f87171;
    --btn-glow: rgba(239,68,68,0.3);
    --btn-bg-hover: rgba(239,68,68,0.1);
  }
  .sylea-action-btn-validate {
    --btn-ring: ${SYLEA.cyan};
    --btn-color: #fff;
    --btn-glow: ${SYLEA.cyan}66;
    --btn-bg: linear-gradient(135deg, ${SYLEA.violet}, ${SYLEA.blue}, ${SYLEA.cyan});
    --btn-bg-hover: linear-gradient(135deg, ${SYLEA.violet}, ${SYLEA.blue}, ${SYLEA.cyan});
    box-shadow: 0 4px 16px ${SYLEA.cyan}44;
  }
  .sylea-action-btn-respond {
    --btn-ring: rgba(251,191,36,0.6);
    --btn-color: #fff;
    --btn-bg: linear-gradient(135deg, rgba(251,191,36,0.95), rgba(217,119,6,0.9));
    --btn-glow: rgba(251,191,36,0.5);
    box-shadow: 0 4px 16px rgba(251,191,36,0.35);
  }

  .sylea-countdown {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 0.78rem;
    font-weight: 700;
    color: ${SYLEA.cyan};
    letter-spacing: 0.05em;
    text-shadow: 0 0 8px ${SYLEA.cyan}80;
  }
  .sylea-countdown-due {
    color: #fbbf24;
    text-shadow: 0 0 10px #fbbf24aa;
    animation: sylea-pulse-soft 1.2s ease-in-out infinite;
  }
`

export function TrackingsPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<TrackingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(i)
  }, [])

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await api.trackingList()
      setItems(r.items || [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const filtered = useMemo(() => filter === 'all' ? items : items.filter(t => t.status === filter), [items, filter])
  const counts = useMemo(() => ({
    all: items.length,
    tracking: items.filter(t => t.status === 'tracking').length,
    awaiting_validation: items.filter(t => t.status === 'awaiting_validation').length,
    validated: items.filter(t => t.status === 'validated').length,
    cancelled: items.filter(t => t.status === 'cancelled').length,
  }), [items])

  return (
    <>
      <style>{STYLES}</style>
      <div className="page animate-fade-in" style={{ position: 'relative' }}>
        {/* Background grid Tron-like */}
        <div className="sylea-grid-bg" style={{
          position: 'absolute', inset: 0, opacity: 0.4, pointerEvents: 'none',
          maskImage: 'radial-gradient(ellipse at top, black 30%, transparent 80%)',
        }} />

        <div className="container page-content" style={{ position: 'relative' }}>
          {/* Hero header */}
          <div style={{ marginBottom: '2rem', position: 'relative' }}>
            <p style={{
              fontSize: '0.72rem',
              color: SYLEA.cyan,
              fontFamily: 'var(--font-mono, ui-monospace, monospace)',
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              marginBottom: '0.5rem',
              textShadow: `0 0 12px ${SYLEA.cyanGlow}`,
            }}>
              ◢ TRACKING SYSTEM v1.0
            </p>
            <h1 style={{
              fontSize: '2.4rem',
              fontWeight: 800,
              background: `linear-gradient(135deg, #fff 0%, ${SYLEA.cyan} 60%, ${SYLEA.blue} 100%)`,
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              margin: 0,
              letterSpacing: '-0.02em',
            }}>
              Mes dilemmes
            </h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.92rem', marginTop: '0.4rem', maxWidth: 640 }}>
              Engagements pris et mesurés dans le temps. Sylea notifie à chaque période pour capter vos vraies actions.
            </p>
          </div>

          {/* Filter chips */}
          <div style={{ display: 'flex', gap: '0.55rem', marginBottom: '1.75rem', flexWrap: 'wrap' }}>
            {([
              ['all', 'Tous', counts.all],
              ['tracking', 'En cours', counts.tracking],
              ['awaiting_validation', 'À valider', counts.awaiting_validation],
              ['validated', 'Validés', counts.validated],
              ['cancelled', 'Abandonnés', counts.cancelled],
            ] as [StatusFilter, string, number][]).map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                onClick={() => setFilter(key)}
                className={`sylea-chip ${filter === key ? 'sylea-chip-active' : ''}`}
              >
                {label}
                <span className="sylea-chip-count">{count}</span>
              </button>
            ))}
          </div>

          {/* Loading */}
          {loading && (
            <div className="loading-center" style={{ padding: '3rem 1rem' }}>
              <div style={{
                width: '52px', height: '52px', borderRadius: '50%',
                border: `2px solid ${SYLEA.cyan}33`,
                borderTopColor: SYLEA.cyan,
                animation: 'spin 0.7s linear infinite',
                boxShadow: `0 0 24px ${SYLEA.cyan}55`,
              }} />
              <p style={{ color: 'var(--text-muted)', marginTop: '1rem', fontFamily: 'var(--font-mono, monospace)', fontSize: '0.78rem', letterSpacing: '0.1em' }}>
                LOADING_TRACKINGS...
              </p>
            </div>
          )}

          {error && (
            <div className="sylea-tech-card" style={{ '--card-glow': '#f8717188' } as React.CSSProperties}>
              <p style={{ color: '#fca5a5', margin: 0 }}>⚠ {error}</p>
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && filtered.length === 0 && (
            <div className="sylea-tech-card" style={{
              textAlign: 'center',
              padding: '3.5rem 2rem',
              '--card-glow': SYLEA.cyan + '44',
            } as React.CSSProperties}>
              <div style={{
                fontSize: '3rem',
                marginBottom: '0.75rem',
                background: `linear-gradient(135deg, ${SYLEA.violet}, ${SYLEA.cyan})`,
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                display: 'inline-block',
                animation: 'sylea-float 4s ease-in-out infinite',
              }}>◇</div>
              <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                {filter === 'all' ? 'Aucun dilemme suivi' : 'Aucun dilemme dans cette catégorie'}
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', marginBottom: '1.5rem', maxWidth: 380, margin: '0 auto 1.5rem' }}>
                Confirmez un dilemme pour démarrer un suivi mesuré dans le temps.
              </p>
              {filter === 'all' && (
                <button
                  type="button"
                  className="sylea-action-btn sylea-action-btn-validate"
                  onClick={() => navigate('/dilemme')}
                  style={{ maxWidth: 240, margin: '0 auto', flex: 'none' }}
                >
                  ⟢ Analyser un choix
                </button>
              )}
            </div>
          )}

          {/* Cards */}
          {!loading && filtered.length > 0 && (
            <div style={{ display: 'grid', gap: '1.2rem' }}>
              {filtered.map(t => (
                <TrackingCard key={t.id} tracking={t} now={now} onChanged={refresh} navigate={navigate} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ─── TrackingCard ───────────────────────────────────────────────────────────

function TrackingCard({
  tracking: tr,
  now,
  onChanged,
  navigate,
}: {
  tracking: TrackingItem
  now: number
  onChanged: () => void
  navigate: (path: string) => void
}) {
  const sc = STATUS_COLORS[tr.status]
  const nbResponded = tr.choices.filter(c => c.choice !== null).length
  const progressPct = (nbResponded / Math.max(1, tr.nb_periodes)) * 100
  const currentPendingIdx = tr.choices.findIndex(c => c.choice === null)
  const nextNotifAt = tr.next_notif_at ? new Date(tr.next_notif_at).getTime() : null
  const isPeriodDue = nextNotifAt !== null && now >= nextNotifAt
  const countdown = formatCountdown(tr.next_notif_at, now)

  const [responding, setResponding] = useState<string | null>(null)
  const [respondError, setRespondError] = useState<string | null>(null)
  const [showAbandon, setShowAbandon] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const handleRespond = async (choice: string) => {
    if (currentPendingIdx < 0) return
    setResponding(choice)
    setRespondError(null)
    try {
      await api.trackingRespond(tr.id, currentPendingIdx, choice)
      onChanged()
    } catch (e: unknown) {
      setRespondError(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setResponding(null)
    }
  }

  const handleAbandon = async () => {
    setActionLoading(true); setActionError(null)
    try {
      await api.trackingCancel(tr.id, 'partial')
      onChanged(); setShowAbandon(false)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Erreur abandon')
    } finally { setActionLoading(false) }
  }

  const handleDelete = async () => {
    setActionLoading(true); setActionError(null)
    try {
      await api.trackingDelete(tr.id)
      onChanged(); setShowDelete(false)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Erreur suppression')
    } finally { setActionLoading(false) }
  }

  return (
    <div
      className="sylea-tech-card"
      style={{
        '--card-glow': sc.glow,
      } as React.CSSProperties}
    >
      {/* Top row : badge + countdown */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        gap: '1rem', marginBottom: '1rem',
      }}>
        <span
          className="sylea-status-badge"
          style={{ '--badge-ring': sc.ring } as React.CSSProperties}
        >
          <span className="sylea-status-dot" />
          {sc.label}
        </span>
        {tr.status === 'tracking' && nextNotifAt && (
          <span className={`sylea-countdown ${isPeriodDue ? 'sylea-countdown-due' : ''}`}>
            {isPeriodDue ? '⚡ DUE' : `◴ ${countdown}`}
          </span>
        )}
      </div>

      {/* Question */}
      <h3 style={{
        fontSize: '1.05rem',
        fontWeight: 700,
        color: 'var(--text-primary)',
        marginBottom: '0.4rem',
        lineHeight: 1.35,
      }}>
        {tr.question}
      </h3>

      {/* Meta */}
      <p style={{
        color: 'var(--text-muted)',
        fontSize: '0.75rem',
        marginBottom: '1.25rem',
        fontFamily: 'var(--font-mono, monospace)',
        letterSpacing: '0.04em',
      }}>
        ⟁ {tr.impact_temporel_jours} JOURS · {tr.nb_periodes} PÉRIODE{tr.nb_periodes > 1 ? 'S' : ''} · {new Date(tr.created_at).toLocaleDateString('fr-FR')}
      </p>

      {/* Progress bar */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', marginBottom: '0.35rem', fontFamily: 'var(--font-mono, monospace)' }}>
          <span style={{ color: 'var(--text-secondary)' }}>{nbResponded} / {tr.nb_periodes}</span>
          <span style={{ color: SYLEA.cyan, textShadow: `0 0 6px ${SYLEA.cyan}66` }}>{progressPct.toFixed(0)}%</span>
        </div>
        <div className="sylea-progress-track" style={{ '--ring': sc.glow } as React.CSSProperties}>
          <div className="sylea-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
      </div>

      {/* Period cells */}
      <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
        {tr.choices.map((c, i) => {
          const isPending = c.choice === null
          const isCurrentDue = isPending && i === currentPendingIdx && isPeriodDue
          const cls = `sylea-period-cell ${
            !isPending
              ? c.choice === 'none' ? 'sylea-period-cell-none' : 'sylea-period-cell-filled'
              : isCurrentDue ? 'sylea-period-cell-due' : ''
          }`
          const label = !isPending
            ? c.choice === 'none' ? '—' : (tr.options[Number(c.choice)]?.lettre || c.choice)
            : (i + 1)
          return (
            <div
              key={i}
              className={cls}
              title={c.responded_at
                ? `Période ${i + 1} : ${label} (${new Date(c.responded_at).toLocaleDateString('fr-FR')})`
                : `Période ${i + 1}${isCurrentDue ? ' — DUE' : ''}`}
            >
              {label}
            </div>
          )
        })}
      </div>

      {/* Response panel (si periode due) */}
      {tr.status === 'tracking' && isPeriodDue && currentPendingIdx >= 0 && (
        <div style={{
          padding: '1rem',
          background: 'linear-gradient(135deg, rgba(251,191,36,0.08), rgba(217,119,6,0.04))',
          border: '1px solid rgba(251,191,36,0.35)',
          borderRadius: '10px',
          marginBottom: '1.1rem',
          position: 'relative',
        }}>
          <p style={{ fontSize: '0.78rem', color: '#fbbf24', marginBottom: '0.7rem', fontWeight: 700, fontFamily: 'var(--font-mono, monospace)', letterSpacing: '0.05em' }}>
            ⚡ PÉRIODE {currentPendingIdx + 1} DUE — QU'AVEZ-VOUS FAIT ?
          </p>
          <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
            {tr.options.map((o, idx) => (
              <button
                key={o.lettre}
                type="button"
                onClick={() => handleRespond(String(idx))}
                disabled={responding !== null}
                className="sylea-action-btn sylea-action-btn-respond"
                style={{ flex: '1 1 200px', minWidth: 0, textAlign: 'left', justifyContent: 'flex-start' }}
              >
                <strong style={{
                  width: '22px', height: '22px', borderRadius: '50%',
                  background: 'rgba(255,255,255,0.25)', display: 'inline-flex',
                  alignItems: 'center', justifyContent: 'center', fontSize: '0.78rem',
                }}>{o.lettre}</strong>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {o.description.length > 38 ? o.description.slice(0, 35) + '…' : o.description}
                </span>
              </button>
            ))}
            <button
              type="button"
              onClick={() => handleRespond('none')}
              disabled={responding !== null}
              className="sylea-action-btn"
              style={{
                flex: '0 0 auto',
                '--btn-ring': 'rgba(148,163,184,0.3)',
                '--btn-color': '#cbd5e1',
                '--btn-bg-hover': 'rgba(148,163,184,0.1)',
                '--btn-glow': 'rgba(148,163,184,0.2)',
              } as React.CSSProperties}
            >
              Aucun
            </button>
          </div>
          {respondError && (
            <p style={{ color: '#fca5a5', fontSize: '0.78rem', marginTop: '0.5rem' }}>⚠ {respondError}</p>
          )}
        </div>
      )}

      {/* Awaiting validation panel */}
      {tr.status === 'awaiting_validation' && (
        <div style={{
          padding: '1rem',
          background: 'linear-gradient(135deg, rgba(34,197,94,0.08), rgba(16,185,129,0.04))',
          border: '1px solid rgba(34,197,94,0.35)',
          borderRadius: '10px',
          marginBottom: '1.1rem',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap',
        }}>
          <div>
            <p style={{ fontSize: '0.78rem', color: '#4ade80', fontWeight: 700, fontFamily: 'var(--font-mono, monospace)', letterSpacing: '0.05em', marginBottom: '0.2rem' }}>
              ✓ TOUTES LES PÉRIODES RENSEIGNÉES
            </p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', margin: 0 }}>
              Validez pour appliquer l'impact pondéré
            </p>
          </div>
          <button
            className="sylea-action-btn sylea-action-btn-validate"
            onClick={() => navigate(`/tracking/${tr.id}/recap`)}
            style={{ flex: '0 0 auto', minWidth: 180 }}
          >
            ◊ Voir le récap →
          </button>
        </div>
      )}

      {/* Validated result */}
      {tr.status === 'validated' && tr.impact_final_jours !== null && (
        <div style={{
          padding: '0.85rem 1rem',
          background: 'rgba(34,197,94,0.06)',
          border: '1px solid rgba(34,197,94,0.3)',
          borderRadius: '10px',
          marginBottom: '1rem',
          display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: '0.75rem', color: '#4ade80', fontFamily: 'var(--font-mono, monospace)', letterSpacing: '0.05em' }}>
            IMPACT FINAL
          </span>
          <span style={{ fontSize: '1.1rem', fontWeight: 800, color: '#4ade80', fontFamily: 'var(--font-mono, monospace)' }}>
            {formatImpactJours(tr.impact_final_jours)}
          </span>
          {tr.impact_final_probabilite !== null && (
            <span style={{ fontSize: '0.85rem', color: '#86efac' }}>
              Δ {tr.impact_final_probabilite >= 0 ? '+' : ''}{tr.impact_final_probabilite.toFixed(2)}%
            </span>
          )}
        </div>
      )}

      {/* === BOUTONS D'ACTION TOUJOURS VISIBLES === */}
      <div style={{
        display: 'flex', gap: '0.55rem',
        paddingTop: '0.85rem',
        borderTop: '1px solid rgba(0,200,255,0.08)',
      }}>
        {(tr.status === 'tracking' || tr.status === 'awaiting_validation') ? (
          <>
            <button
              type="button"
              onClick={() => setShowAbandon(true)}
              className="sylea-action-btn sylea-action-btn-abandon"
            >
              ◯ Abandonner
            </button>
            <button
              type="button"
              onClick={() => setShowDelete(true)}
              className="sylea-action-btn sylea-action-btn-delete"
            >
              ✕ Supprimer
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setShowDelete(true)}
            className="sylea-action-btn sylea-action-btn-delete"
          >
            ✕ Supprimer de l'historique
          </button>
        )}
      </div>

      {/* === MODALS === */}
      {showAbandon && (
        <Modal
          color="#fbbf24"
          icon="◯"
          title="Abandonner ce suivi ?"
          loading={actionLoading}
          error={actionError}
          onClose={() => { setShowAbandon(false); setActionError(null) }}
          onConfirm={handleAbandon}
          confirmLabel="Abandonner et appliquer"
          confirmGradient="linear-gradient(135deg, #d97706, #f59e0b)"
        >
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.6 }}>
            L'impact partiel basé sur vos <strong style={{ color: '#fbbf24' }}>{nbResponded}/{tr.nb_periodes}</strong> période{nbResponded > 1 ? 's' : ''} déjà renseignée{nbResponded > 1 ? 's' : ''} sera appliqué à votre objectif. Le suivi sera marqué comme abandonné dans votre historique.
          </p>
          {nbResponded === 0 && (
            <div style={{
              background: 'rgba(248,113,113,0.08)',
              border: '1px solid rgba(248,113,113,0.25)',
              borderRadius: '8px', padding: '0.6rem 0.85rem',
              marginTop: '0.85rem',
              color: '#fca5a5', fontSize: '0.78rem',
            }}>
              ⚠ Aucune période renseignée. Aucun impact ne sera appliqué. Utilisez plutôt « Supprimer » pour effacer.
            </div>
          )}
        </Modal>
      )}

      {showDelete && (
        <Modal
          color="#f87171"
          icon="✕"
          title="Supprimer ce dilemme ?"
          loading={actionLoading}
          error={actionError}
          onClose={() => { setShowDelete(false); setActionError(null) }}
          onConfirm={handleDelete}
          confirmLabel="Supprimer définitivement"
          confirmGradient="linear-gradient(135deg, #dc2626, #ef4444)"
        >
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.6 }}>
            Le dilemme sera <strong style={{ color: '#f87171' }}>complètement effacé</strong> — aucune trace dans votre historique. <strong>Aucun impact</strong> appliqué à votre objectif. Cette action est <strong>irréversible</strong>.
          </p>
          {tr.status === 'validated' && tr.impact_final_jours !== null && (
            <div style={{
              background: `rgba(0,200,255,0.06)`,
              border: `1px solid ${SYLEA.cyan}44`,
              borderRadius: '8px', padding: '0.6rem 0.85rem',
              marginTop: '0.85rem',
              color: '#93c5fd', fontSize: '0.78rem',
            }}>
              ℹ L'impact de <strong>{formatImpactJours(tr.impact_final_jours)}</strong> déjà appliqué <strong>ne sera pas reversé</strong>. Seul l'enregistrement disparaît.
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}

// ─── Modal commun ───────────────────────────────────────────────────────────

function Modal({
  color, icon, title, children, error, loading, onClose, onConfirm, confirmLabel, confirmGradient,
}: {
  color: string
  icon: string
  title: string
  children: React.ReactNode
  error: string | null
  loading: boolean
  onClose: () => void
  onConfirm: () => void
  confirmLabel: string
  confirmGradient: string
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(2,5,15,0.85)',
        backdropFilter: 'blur(14px)',
        zIndex: 9000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '1rem',
        animation: 'sylea-fade-in 0.18s ease-out',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="sylea-tech-card"
        style={{
          maxWidth: 480, width: '100%',
          padding: '1.85rem',
          border: `1px solid ${color}55`,
          '--card-glow': `${color}66`,
        } as React.CSSProperties}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', marginBottom: '1rem' }}>
          <div style={{
            width: 40, height: 40,
            borderRadius: '10px',
            background: `${color}22`,
            border: `1px solid ${color}66`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: color, fontSize: '1.15rem', fontWeight: 700,
            boxShadow: `0 0 16px ${color}55`,
          }}>{icon}</div>
          <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.1rem' }}>{title}</h3>
        </div>
        {children}
        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: '8px', padding: '0.55rem 0.85rem',
            marginTop: '0.85rem',
            color: '#fca5a5', fontSize: '0.78rem',
          }}>⚠ {error}</div>
        )}
        <div style={{ display: 'flex', gap: '0.55rem', marginTop: '1.2rem' }}>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            style={{
              flex: 1, padding: '0.7rem',
              background: 'transparent',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--text-muted)',
              borderRadius: '10px',
              cursor: loading ? 'wait' : 'pointer',
              fontSize: '0.85rem',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
          >
            Retour
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            style={{
              flex: 1, padding: '0.7rem',
              background: confirmGradient,
              border: 'none', color: 'white',
              borderRadius: '10px',
              cursor: loading ? 'wait' : 'pointer',
              fontSize: '0.85rem', fontWeight: 600,
              opacity: loading ? 0.6 : 1,
              boxShadow: `0 4px 16px ${color}55`,
              transition: 'transform 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={(e) => {
              if (!loading) {
                (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)'
                ;(e.currentTarget as HTMLElement).style.boxShadow = `0 6px 24px ${color}88`
              }
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.transform = 'translateY(0)'
              ;(e.currentTarget as HTMLElement).style.boxShadow = `0 4px 16px ${color}55`
            }}
          >
            {loading ? 'En cours…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
