// Page "Progression des décisions"
//
// Affiche toutes les decisions en attente de confirmation (pending_actions).
// Chaque ligne montre :
//   - description + impact_jours (gain/perte)
//   - jauge horizontale (cree_le → echeance_le, remplie selon le temps ecoule)
//   - marqueur de la prochaine notification push
//   - boutons Oui/Non si la verification est due
//
// Une fois 'completed' ou 'abandoned', la jauge disparait (filtree backend).

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { PendingAction } from '../types'
import { useT } from '../i18n/LanguageContext'

function formatJours(j: number): string {
  const abs = Math.abs(j)
  const sign = j >= 0 ? '+' : '-'
  // < 1h : afficher en minutes (5min, 30min, 45min)
  // < 1j : afficher en heures (1.5h, 6h, 12h)
  // sinon en jours/mois/ans
  const totalHeures = abs * 24
  if (totalHeures < 1) {
    const minutes = Math.max(1, Math.round(totalHeures * 60))
    return `${sign}${minutes} min`
  }
  if (abs < 1) {
    const heures = totalHeures < 10 ? Math.round(totalHeures * 10) / 10 : Math.round(totalHeures)
    return `${sign}${heures} h`
  }
  if (abs < 30) return `${sign}${abs.toFixed(abs < 10 ? 1 : 0)} j`
  if (abs < 365) {
    const mois = Math.round(abs / 30 * 10) / 10
    return `${sign}${mois} mois`
  }
  const ans = Math.round(abs / 365 * 10) / 10
  return `${sign}${ans} ans`
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch {
    return iso
  }
}

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso).getTime()
    const now = Date.now()
    const diffMs = d - now
    const diffH = diffMs / (1000 * 60 * 60)
    const absH = Math.abs(diffH)
    if (absH < 1) {
      const mins = Math.round(absH * 60)
      return diffMs >= 0 ? `dans ${mins} min` : `il y a ${mins} min`
    }
    if (absH < 24) {
      const h = Math.round(absH)
      return diffMs >= 0 ? `dans ${h} h` : `il y a ${h} h`
    }
    const d2 = Math.round(absH / 24)
    return diffMs >= 0 ? `dans ${d2} j` : `il y a ${d2} j`
  } catch {
    return iso
  }
}

export function ProgressionDecisionsPage() {
  const navigate = useNavigate()
  const t = useT()
  const [pendings, setPendings] = useState<PendingAction[]>([])
  const [loading, setLoading] = useState(true)
  const [respondingId, setRespondingId] = useState<string | null>(null)

  const fetchPendings = async () => {
    try {
      const list = await api.listPending()
      setPendings(list)
    } catch {
      setPendings([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPendings()
    // Refresh toutes les 30s pour capter les transitions de statut + nouveaux pendings
    const interval = setInterval(fetchPendings, 30_000)
    return () => clearInterval(interval)
  }, [])

  const handleRespond = async (pendingId: string, response: boolean) => {
    setRespondingId(pendingId)
    try {
      await api.respondPending(pendingId, response)
      await fetchPendings()
    } catch {
      // En cas d'erreur (auth, network), on laisse la pending visible
    } finally {
      setRespondingId(null)
    }
  }

  if (loading) {
    return (
      <div className="page animate-fade-in">
        <div className="container page-content" style={{ textAlign: 'center', padding: '4rem 0', color: 'var(--text-muted)' }}>
          {t('common.chargement') || 'Chargement…'}
        </div>
      </div>
    )
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">
        <button
          onClick={() => navigate('/')}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', fontSize: '0.88rem', padding: '0.25rem 0',
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            marginBottom: '0.75rem',
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          {(t('common.retour_dashboard') || '← Retour au tableau de bord').replace('← ', '')}
        </button>

        <div style={{ marginBottom: 'var(--space-8)' }}>
          <h1 style={{
            fontSize: 'var(--fs-3xl)',
            fontWeight: 700,
            letterSpacing: 'var(--tracking-tight)',
            color: 'var(--text-primary)',
            marginBottom: 'var(--space-2)',
            lineHeight: 1.15,
          }}>
            {t('progression.titre') || 'Progression des décisions'}
          </h1>
          <p style={{
            color: 'var(--text-muted)',
            fontSize: 'var(--fs-md)',
            lineHeight: 1.55,
            maxWidth: 720,
          }}>
            {t('progression.description') ||
              'Vos décisions en attente de confirmation. Chaque jauge se remplit jusqu\'à l\'échéance, puis Syléa vous demande si vous l\'avez réalisée. L\'impact est appliqué à votre objectif uniquement après confirmation.'}
          </p>
        </div>

        {pendings.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
            <div style={{ fontSize: '2.5rem', marginBottom: '0.75rem', opacity: 0.5 }}>📋</div>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', margin: 0 }}>
              {t('progression.aucune') ||
                'Aucune décision en attente. Analysez un évènement ou choisissez une option de dilemme pour démarrer.'}
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {pendings.map((p) => (
              <PendingActionCard
                key={p.id}
                pending={p}
                isResponding={respondingId === p.id}
                onRespond={handleRespond}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


function PendingActionCard({
  pending,
  isResponding,
  onRespond,
}: {
  pending: PendingAction
  isResponding: boolean
  onRespond: (id: string, response: boolean) => void
}) {
  const t = useT()
  const created = new Date(pending.cree_le).getTime()
  const echeance = new Date(pending.echeance_le).getTime()
  const nextCheck = new Date(pending.prochaine_verification_le).getTime()
  const now = Date.now()

  const totalDur = Math.max(1, echeance - created)
  const elapsed = Math.max(0, Math.min(totalDur, now - created))
  const elapsedPct = Math.round((elapsed / totalDur) * 100)
  const nextCheckPct = Math.max(0, Math.min(100, ((nextCheck - created) / totalDur) * 100))

  const isDue = now >= nextCheck
  const isPositive = pending.impact_jours >= 0
  const impactColor = isPositive ? '#4ade80' : '#f87171'
  const impactBg = isPositive ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)'
  const impactBorder = isPositive ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'

  // Pour les long-terme, calcul des ticks mensuels intermediaires
  const ticks: number[] = []
  if (pending.is_long_terme) {
    const monthMs = 30 * 24 * 60 * 60 * 1000
    let t0 = created + monthMs
    while (t0 < echeance) {
      const pct = ((t0 - created) / totalDur) * 100
      if (pct > 0 && pct < 100) ticks.push(pct)
      t0 += monthMs
    }
  }

  return (
    <div
      className="card"
      style={{
        padding: '1.25rem',
        borderColor: isDue ? 'var(--accent-gold)' : 'var(--border)',
        boxShadow: isDue ? '0 0 16px rgba(245,158,11,0.15)' : undefined,
        transition: 'all 0.3s',
      }}
    >
      {/* Header : description + impact_jours */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '0.875rem', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            margin: 0, marginBottom: '0.25rem',
            fontSize: '0.95rem', fontWeight: 500,
            color: 'var(--text-primary)', lineHeight: 1.45,
          }}>
            {pending.description}
          </p>
          <p style={{
            margin: 0, fontSize: '0.72rem', color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.04em',
          }}>
            {pending.source_type === 'event' ? '◈ Évènement' : '◈ Choix de dilemme'}
            {pending.is_long_terme && ' · Long terme'}
          </p>
        </div>
        <div style={{
          padding: '0.4rem 0.85rem',
          borderRadius: '999px',
          background: impactBg,
          border: `1px solid ${impactBorder}`,
          color: impactColor,
          fontFamily: 'var(--font-mono)',
          fontSize: '0.95rem',
          fontWeight: 700,
          flexShrink: 0,
        }}>
          {formatJours(pending.impact_jours)}
        </div>
      </div>

      {/* Jauge horizontale */}
      <div style={{ position: 'relative', marginBottom: '0.75rem' }}>
        {/* Bar de fond */}
        <div style={{
          width: '100%', height: '12px',
          background: 'rgba(148,163,184,0.12)',
          borderRadius: '999px',
          overflow: 'hidden',
          position: 'relative',
        }}>
          {/* Bar remplie (temps ecoule) */}
          <div style={{
            width: `${elapsedPct}%`, height: '100%',
            background: isDue
              ? 'linear-gradient(90deg, var(--accent-gold), #fbbf24)'
              : 'linear-gradient(90deg, var(--accent-violet), var(--accent-violet-light))',
            transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s',
            borderRadius: '999px',
            boxShadow: isDue ? '0 0 10px rgba(245,158,11,0.5)' : undefined,
          }} />

          {/* Ticks mensuels intermediaires (long terme) */}
          {ticks.map((pct, i) => (
            <div key={i} style={{
              position: 'absolute',
              left: `${pct}%`,
              top: 0, bottom: 0,
              width: 2,
              background: 'rgba(255,255,255,0.25)',
              transform: 'translateX(-1px)',
            }} />
          ))}
        </div>

        {/* Marker de la prochaine notification */}
        <div
          title={`Prochaine vérification : ${formatDate(pending.prochaine_verification_le)}`}
          style={{
            position: 'absolute',
            left: `${nextCheckPct}%`,
            top: '-4px',
            width: 20, height: 20,
            transform: 'translateX(-10px)',
            borderRadius: '50%',
            background: isDue ? 'var(--accent-gold)' : 'var(--accent-violet)',
            border: '2px solid var(--bg-base, #0a0e1a)',
            boxShadow: isDue
              ? '0 0 14px rgba(245,158,11,0.7)'
              : '0 0 8px rgba(124,58,237,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'help',
          }}
        >
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: 'white',
          }} />
        </div>
      </div>

      {/* Footer : dates + actions Oui/Non si due */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          <span>Créée {formatRelative(pending.cree_le)}</span>
          <span style={{ color: isDue ? 'var(--accent-gold)' : 'var(--accent-violet-light)', fontWeight: 600 }}>
            {isDue ? '⏰ Vérification disponible' : `Prochaine notif ${formatRelative(pending.prochaine_verification_le)}`}
          </span>
          <span>Échéance {formatDate(pending.echeance_le)}</span>
        </div>

        {isDue && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={() => onRespond(pending.id, false)}
              disabled={isResponding}
              className="btn btn-outline btn-sm"
              style={{
                borderColor: 'rgba(239,68,68,0.4)',
                color: '#f87171',
              }}
            >
              {t('progression.non_abandonner') || 'Non, abandon'}
            </button>
            <button
              onClick={() => onRespond(pending.id, true)}
              disabled={isResponding}
              className="btn btn-primary btn-sm"
              style={{
                background: pending.is_final_check
                  ? 'linear-gradient(135deg, #10b981, #059669)'
                  : undefined,
              }}
            >
              {pending.is_final_check
                ? (t('progression.oui_termine') || 'Oui, terminé ✓')
                : (t('progression.oui_continue') || 'Oui, en cours')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default ProgressionDecisionsPage
