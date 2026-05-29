// Page "Mes dilemmes en cours" — liste des trackings actifs
// Design tech & addictif : countdown jusqu'à la prochaine notification,
// visualisation des périodes répondues vs en attente, possibilité de
// répondre manuellement aux périodes échues, annulation, etc.

import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useT } from '../i18n/LanguageContext'
import type { TrackingItem, TrackingStatus } from '../types'

type StatusFilter = TrackingStatus | 'all'

const STATUS_COLORS: Record<TrackingStatus, { bg: string; border: string; text: string; label: string }> = {
  tracking: { bg: 'rgba(59,130,246,0.08)', border: 'rgba(59,130,246,0.35)', text: '#60a5fa', label: 'En cours' },
  awaiting_validation: { bg: 'rgba(245,158,11,0.08)', border: 'rgba(245,158,11,0.4)', text: '#fbbf24', label: 'À valider' },
  validated: { bg: 'rgba(34,197,94,0.08)', border: 'rgba(34,197,94,0.35)', text: '#4ade80', label: 'Validé' },
  cancelled: { bg: 'rgba(148,163,184,0.08)', border: 'rgba(148,163,184,0.3)', text: '#94a3b8', label: 'Annulé' },
}

function formatCountdown(targetIso: string | null): string {
  if (!targetIso) return '—'
  const target = new Date(targetIso).getTime()
  const now = Date.now()
  const diffMs = target - now
  if (diffMs <= 0) return 'Maintenant'
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))
  if (days > 0) return `${days}j ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

export function TrackingsPage() {
  const t = useT()
  const navigate = useNavigate()
  const [items, setItems] = useState<TrackingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [now, setNow] = useState(Date.now())

  // Refresh "now" toutes les secondes pour les countdowns
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(i)
  }, [])

  // Charge les trackings
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

  useEffect(() => {
    refresh()
  }, [])

  const filtered = useMemo(() => {
    if (filter === 'all') return items
    return items.filter(t => t.status === filter)
  }, [items, filter])

  const counts = useMemo(() => {
    return {
      all: items.length,
      tracking: items.filter(t => t.status === 'tracking').length,
      awaiting_validation: items.filter(t => t.status === 'awaiting_validation').length,
      validated: items.filter(t => t.status === 'validated').length,
      cancelled: items.filter(t => t.status === 'cancelled').length,
    }
  }, [items])

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">
        <div style={{ marginBottom: '1.5rem' }}>
          <h1 className="page-title" style={{ marginBottom: '0.35rem' }}>
            Mes dilemmes en cours
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>
            Engagements pris et suivis dans le temps. Sylea vous notifiera à
            chaque période pour mesurer vos vraies actions.
          </p>
        </div>

        {/* Filtres */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
          {([
            ['all', 'Tous', counts.all],
            ['tracking', 'En cours', counts.tracking],
            ['awaiting_validation', 'À valider', counts.awaiting_validation],
            ['validated', 'Validés', counts.validated],
            ['cancelled', 'Annulés', counts.cancelled],
          ] as [StatusFilter, string, number][]).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              style={{
                padding: '0.45rem 0.85rem',
                borderRadius: 'var(--radius-md)',
                border: filter === key
                  ? '1px solid var(--accent-violet)'
                  : '1px solid var(--border)',
                background: filter === key
                  ? 'rgba(124,58,237,0.15)'
                  : 'rgba(255,255,255,0.03)',
                color: filter === key ? 'var(--accent-violet-light)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: filter === key ? 600 : 400,
                display: 'flex', alignItems: 'center', gap: '0.45rem',
              }}
            >
              {label}
              <span style={{
                background: filter === key ? 'rgba(124,58,237,0.25)' : 'rgba(255,255,255,0.05)',
                padding: '0.05rem 0.5rem',
                borderRadius: '999px',
                fontSize: '0.72rem',
                fontWeight: 600,
              }}>
                {count}
              </span>
            </button>
          ))}
        </div>

        {/* États */}
        {loading && (
          <div className="loading-center" style={{ padding: '3rem 1rem' }}>
            <div style={{
              width: '48px', height: '48px', borderRadius: '50%',
              border: '3px solid var(--accent-violet-dim)',
              borderTop: '3px solid var(--accent-violet)',
              animation: 'spin 0.8s linear infinite',
            }} />
            <p style={{ color: 'var(--text-muted)', marginTop: '1rem' }}>Chargement…</p>
          </div>
        )}

        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            color: '#fca5a5',
            marginBottom: '1rem',
          }}>
            {'⚠'} {error}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="card" style={{
            padding: '3rem 2rem',
            textAlign: 'center',
            border: '1px dashed var(--border)',
          }}>
            <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem', opacity: 0.4 }}>{'◇'}</div>
            <h3 style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '1.1rem' }}>
              {filter === 'all' ? 'Aucun dilemme suivi' : 'Aucun dilemme dans cette catégorie'}
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', marginBottom: '1.25rem' }}>
              {filter === 'all'
                ? 'Confirmez votre prochain dilemme pour démarrer un suivi.'
                : 'Changez de filtre pour voir d\'autres dilemmes.'}
            </p>
            {filter === 'all' && (
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/dilemme')}>
                Analyser un choix
              </button>
            )}
          </div>
        )}

        {/* Cards */}
        {!loading && filtered.length > 0 && (
          <div style={{ display: 'grid', gap: '1rem' }}>
            {filtered.map(t => (
              <TrackingCard
                key={t.id}
                tracking={t}
                now={now}
                onChanged={refresh}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


// ── TrackingCard : un tracking unique avec sa visualisation tech-addictive ──

function TrackingCard({
  tracking: tr,
  now,
  onChanged,
}: {
  tracking: TrackingItem
  now: number
  onChanged: () => void
}) {
  const navigate = useNavigate()
  const sc = STATUS_COLORS[tr.status]
  const nbResponded = tr.choices.filter(c => c.choice !== null).length
  const progressPct = (nbResponded / tr.nb_periodes) * 100
  // Trouve la 1ere periode en attente
  const currentPendingIdx = tr.choices.findIndex(c => c.choice === null)
  const nextNotifAt = tr.next_notif_at ? new Date(tr.next_notif_at).getTime() : null
  const isPeriodDue = nextNotifAt !== null && now >= nextNotifAt
  const countdown = formatCountdown(tr.next_notif_at)

  const [responding, setResponding] = useState<string | null>(null) // choice id being submitted
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
      const msg = e instanceof Error ? e.message : 'Erreur'
      setRespondError(msg)
    } finally {
      setResponding(null)
    }
  }

  // ABANDONNER : applique l'impact partiel (compute_recap des choix deja faits)
  // et marque status='cancelled' (conserve dans l'historique)
  const handleAbandon = async () => {
    setActionLoading(true)
    setActionError(null)
    try {
      await api.trackingCancel(tr.id, 'partial')
      onChanged()
      setShowAbandon(false)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Erreur abandon')
    } finally {
      setActionLoading(false)
    }
  }

  // SUPPRIMER : retire de la DB completement, aucune trace, aucun impact
  const handleDelete = async () => {
    setActionLoading(true)
    setActionError(null)
    try {
      await api.trackingDelete(tr.id)
      onChanged()
      setShowDelete(false)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Erreur suppression')
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div
      className="card"
      style={{
        background: 'linear-gradient(135deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01))',
        border: `1px solid ${sc.border}`,
        padding: '1.25rem',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Status badge (haut droite) */}
      <div style={{
        position: 'absolute', top: '0.85rem', right: '0.85rem',
        padding: '0.2rem 0.7rem',
        background: sc.bg,
        border: `1px solid ${sc.border}`,
        borderRadius: '999px',
        color: sc.text,
        fontSize: '0.72rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}>
        {sc.label}
      </div>

      {/* Question */}
      <h3 style={{
        fontSize: '1.05rem',
        fontWeight: 700,
        color: 'var(--text-primary)',
        marginBottom: '0.5rem',
        paddingRight: '5.5rem',
        lineHeight: 1.35,
      }}>
        {tr.question}
      </h3>

      {/* Meta */}
      <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginBottom: '1rem' }}>
        Engagement de {tr.impact_temporel_jours} jours · {tr.nb_periodes} période{tr.nb_periodes > 1 ? 's' : ''} · créé le {new Date(tr.created_at).toLocaleDateString('fr-FR')}
      </p>

      {/* Progress bar visuelle */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
          <span>{nbResponded} / {tr.nb_periodes} période{tr.nb_periodes > 1 ? 's' : ''} renseignée{nbResponded > 1 ? 's' : ''}</span>
          {tr.status === 'tracking' && nextNotifAt && (
            <span style={{ color: isPeriodDue ? '#fbbf24' : 'var(--text-muted)' }}>
              {isPeriodDue ? '⚡ Période due' : `Prochaine notif dans ${countdown}`}
            </span>
          )}
        </div>
        <div style={{
          height: '6px',
          background: 'rgba(255,255,255,0.05)',
          borderRadius: '3px',
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: `linear-gradient(90deg, ${sc.text}, ${sc.text}aa)`,
            transition: 'width 0.4s ease',
          }} />
        </div>
      </div>

      {/* Périodes visualisées */}
      <div style={{ display: 'flex', gap: '0.3rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {tr.choices.map((c, i) => {
          const opt = c.choice !== null
            ? c.choice === 'none' ? '—' : tr.options[Number(c.choice)]?.lettre || c.choice
            : ''
          const colors = c.choice === null
            ? 'rgba(255,255,255,0.05)'
            : c.choice === 'none' ? 'rgba(148,163,184,0.18)'
            : 'rgba(124,58,237,0.22)'
          return (
            <div
              key={i}
              title={c.responded_at ? `Période ${i + 1} : ${opt} (${new Date(c.responded_at).toLocaleDateString('fr-FR')})` : `Période ${i + 1} en attente`}
              style={{
                width: '28px', height: '28px',
                borderRadius: '6px',
                background: colors,
                border: c.choice === null && i === currentPendingIdx && isPeriodDue
                  ? '2px solid #fbbf24'
                  : '1px solid rgba(255,255,255,0.08)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.75rem',
                fontWeight: 700,
                color: c.choice === null ? 'var(--text-muted)' : '#fff',
              }}
            >
              {opt || (i + 1)}
            </div>
          )
        })}
      </div>

      {/* Actions selon le statut */}
      {tr.status === 'tracking' && isPeriodDue && currentPendingIdx >= 0 && (
        <div style={{
          background: 'rgba(245,158,11,0.05)',
          border: '1px dashed rgba(245,158,11,0.3)',
          borderRadius: 'var(--radius-md)',
          padding: '0.75rem',
          marginBottom: '0.85rem',
        }}>
          <p style={{ fontSize: '0.85rem', color: '#fbbf24', marginBottom: '0.6rem', fontWeight: 600 }}>
            Période {currentPendingIdx + 1} due — Qu'avez-vous fait ?
          </p>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {tr.options.map((o, idx) => (
              <button
                key={o.lettre}
                type="button"
                onClick={() => handleRespond(String(idx))}
                disabled={responding !== null}
                style={{
                  padding: '0.5rem 0.85rem',
                  background: responding === String(idx)
                    ? 'rgba(124,58,237,0.3)'
                    : 'rgba(124,58,237,0.12)',
                  border: '1px solid rgba(124,58,237,0.35)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--accent-violet-light)',
                  fontSize: '0.82rem',
                  fontWeight: 500,
                  cursor: responding !== null ? 'wait' : 'pointer',
                  flex: '1 1 auto',
                  minWidth: 0,
                  textAlign: 'left',
                }}
              >
                <strong style={{ marginRight: '0.4rem' }}>{o.lettre}</strong>
                {o.description.length > 50 ? o.description.slice(0, 47) + '…' : o.description}
              </button>
            ))}
            <button
              type="button"
              onClick={() => handleRespond('none')}
              disabled={responding !== null}
              style={{
                padding: '0.5rem 0.85rem',
                background: 'rgba(148,163,184,0.12)',
                border: '1px solid rgba(148,163,184,0.3)',
                borderRadius: 'var(--radius-md)',
                color: '#94a3b8',
                fontSize: '0.82rem',
                fontWeight: 500,
                cursor: responding !== null ? 'wait' : 'pointer',
              }}
            >
              Aucun des deux
            </button>
          </div>
          {respondError && (
            <p style={{ color: '#fca5a5', fontSize: '0.78rem', marginTop: '0.5rem' }}>{respondError}</p>
          )}
        </div>
      )}

      {/* Status: awaiting validation -> bouton valider */}
      {tr.status === 'awaiting_validation' && (
        <div style={{
          background: 'rgba(34,197,94,0.06)',
          border: '1px dashed rgba(34,197,94,0.35)',
          borderRadius: 'var(--radius-md)',
          padding: '0.85rem',
          marginBottom: '0.5rem',
        }}>
          <p style={{ fontSize: '0.85rem', color: '#4ade80', marginBottom: '0.6rem', fontWeight: 600 }}>
            ✓ Toutes les périodes sont renseignées. Validez pour appliquer l'impact.
          </p>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => navigate(`/tracking/${tr.id}/recap`)}
          >
            Voir le récap et valider
          </button>
        </div>
      )}

      {/* Status: validated -> impact final */}
      {tr.status === 'validated' && (
        <div style={{
          background: 'rgba(34,197,94,0.06)',
          border: '1px solid rgba(34,197,94,0.25)',
          borderRadius: 'var(--radius-md)',
          padding: '0.75rem',
          fontSize: '0.85rem',
          color: '#4ade80',
        }}>
          Impact final appliqué&nbsp;: <strong>{tr.impact_final_jours?.toFixed(1)} j</strong>
          {tr.impact_final_probabilite !== null && (
            <span> · Δ probabilité <strong>{tr.impact_final_probabilite >= 0 ? '+' : ''}{tr.impact_final_probabilite.toFixed(2)}%</strong></span>
          )}
        </div>
      )}

      {/* Actions secondaires : 2 boutons distincts */}
      {(tr.status === 'tracking' || tr.status === 'awaiting_validation') && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.5rem' }}>
          <button
            type="button"
            onClick={() => setShowAbandon(true)}
            style={{
              background: 'transparent',
              border: '1px solid rgba(251,191,36,0.25)',
              color: '#fbbf24',
              fontSize: '0.75rem',
              cursor: 'pointer',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            ◯ Abandonner
          </button>
          <button
            type="button"
            onClick={() => setShowDelete(true)}
            style={{
              background: 'transparent',
              border: '1px solid rgba(239,68,68,0.25)',
              color: '#f87171',
              fontSize: '0.75rem',
              cursor: 'pointer',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            ✕ Supprimer
          </button>
        </div>
      )}
      {/* Cas particulier : tracking deja cancelled ou validated, on autorise
          seulement la Suppression definitive de l'historique */}
      {(tr.status === 'cancelled' || tr.status === 'validated') && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
          <button
            type="button"
            onClick={() => setShowDelete(true)}
            style={{
              background: 'transparent',
              border: '1px solid rgba(239,68,68,0.2)',
              color: '#f87171',
              fontSize: '0.7rem',
              cursor: 'pointer',
              padding: '0.3rem 0.65rem',
              borderRadius: 'var(--radius-sm)',
              opacity: 0.7,
            }}
          >
            ✕ Supprimer de l'historique
          </button>
        </div>
      )}

      {/* Modal ABANDONNER : applique impact partiel */}
      {showAbandon && (
        <div
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.75)',
            backdropFilter: 'blur(6px)',
            zIndex: 4000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '1rem',
          }}
          onClick={e => { if (e.target === e.currentTarget) setShowAbandon(false) }}
        >
          <div className="card" style={{ maxWidth: '460px', width: '100%', padding: '1.75rem', border: '1px solid rgba(251,191,36,0.35)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.85rem' }}>
              <div style={{
                width: '34px', height: '34px',
                background: 'rgba(251,191,36,0.18)',
                border: '1px solid rgba(251,191,36,0.35)',
                borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fbbf24', fontSize: '1.05rem',
              }}>◯</div>
              <h3 style={{ color: '#fbbf24', margin: 0 }}>Abandonner ce suivi&nbsp;?</h3>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', marginBottom: '1rem', lineHeight: 1.55 }}>
              L'impact partiel basé sur vos <strong>{nbResponded}/{tr.nb_periodes}</strong> période{nbResponded > 1 ? 's' : ''} déjà renseignée{nbResponded > 1 ? 's' : ''} sera appliqué à votre objectif. Le suivi sera marqué comme abandonné dans votre historique.
            </p>
            {nbResponded === 0 && (
              <div style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)', borderRadius: 'var(--radius-md)', padding: '0.55rem 0.85rem', marginBottom: '1rem', color: '#fca5a5', fontSize: '0.82rem' }}>
                ⚠ Aucune période renseignée. L'abandon n'appliquera aucun impact. Pour effacer ce dilemme, utilisez plutôt "Supprimer".
              </div>
            )}
            {actionError && (
              <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--radius-md)', padding: '0.55rem 0.85rem', marginBottom: '1rem', color: '#fca5a5', fontSize: '0.82rem' }}>
                {actionError}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                onClick={() => { setShowAbandon(false); setActionError(null) }}
                disabled={actionLoading}
                style={{
                  flex: 1, padding: '0.6rem',
                  background: 'transparent', border: '1px solid var(--border)',
                  color: 'var(--text-muted)', borderRadius: 'var(--radius-md)',
                  cursor: actionLoading ? 'wait' : 'pointer', fontSize: '0.85rem',
                }}
              >
                Retour
              </button>
              <button
                type="button"
                onClick={handleAbandon}
                disabled={actionLoading}
                style={{
                  flex: 1, padding: '0.6rem',
                  background: 'linear-gradient(135deg, #d97706, #f59e0b)',
                  border: 'none', color: 'white', borderRadius: 'var(--radius-md)',
                  cursor: actionLoading ? 'wait' : 'pointer', fontSize: '0.85rem', fontWeight: 600,
                  opacity: actionLoading ? 0.6 : 1,
                }}
              >
                {actionLoading ? 'En cours…' : 'Abandonner et appliquer'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal SUPPRIMER : delete complet */}
      {showDelete && (
        <div
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.75)',
            backdropFilter: 'blur(6px)',
            zIndex: 4000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '1rem',
          }}
          onClick={e => { if (e.target === e.currentTarget) setShowDelete(false) }}
        >
          <div className="card" style={{ maxWidth: '460px', width: '100%', padding: '1.75rem', border: '1px solid rgba(239,68,68,0.35)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.85rem' }}>
              <div style={{
                width: '34px', height: '34px',
                background: 'rgba(239,68,68,0.18)',
                border: '1px solid rgba(239,68,68,0.35)',
                borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#f87171', fontSize: '1.1rem',
              }}>✕</div>
              <h3 style={{ color: '#f87171', margin: 0 }}>Supprimer ce dilemme&nbsp;?</h3>
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', marginBottom: '1rem', lineHeight: 1.55 }}>
              Le dilemme sera <strong>complètement effacé</strong> — aucune trace ne sera conservée dans votre historique. <strong>Aucun impact</strong> ne sera appliqué à votre objectif. Cette action est <strong>irréversible</strong>.
            </p>
            {tr.status === 'validated' && tr.impact_final_jours !== null && (
              <div style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.25)', borderRadius: 'var(--radius-md)', padding: '0.55rem 0.85rem', marginBottom: '1rem', color: '#93c5fd', fontSize: '0.82rem' }}>
                ℹ L'impact de {tr.impact_final_jours.toFixed(1)} j déjà appliqué à votre profil <strong>ne sera pas reversé</strong>. Seul l'enregistrement du dilemme disparaît.
              </div>
            )}
            {actionError && (
              <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--radius-md)', padding: '0.55rem 0.85rem', marginBottom: '1rem', color: '#fca5a5', fontSize: '0.82rem' }}>
                {actionError}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                onClick={() => { setShowDelete(false); setActionError(null) }}
                disabled={actionLoading}
                style={{
                  flex: 1, padding: '0.6rem',
                  background: 'transparent', border: '1px solid var(--border)',
                  color: 'var(--text-muted)', borderRadius: 'var(--radius-md)',
                  cursor: actionLoading ? 'wait' : 'pointer', fontSize: '0.85rem',
                }}
              >
                Retour
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={actionLoading}
                style={{
                  flex: 1, padding: '0.6rem',
                  background: 'linear-gradient(135deg, #dc2626, #ef4444)',
                  border: 'none', color: 'white', borderRadius: 'var(--radius-md)',
                  cursor: actionLoading ? 'wait' : 'pointer', fontSize: '0.85rem', fontWeight: 600,
                  opacity: actionLoading ? 0.6 : 1,
                }}
              >
                {actionLoading ? 'Suppression…' : 'Supprimer définitivement'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
