// Banner global qui scanne les trackings actifs et affiche une alerte
// quand au moins une période est due (= notif arrivée à échéance).
//
// Polling toutes les 30s. Design tech-addictive avec compteur de periodes
// dues + accès direct à la page Mes dilemmes.

import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useStore } from '../store/useStore'
import type { TrackingItem } from '../types'

interface DueItem {
  tracking: TrackingItem
  periodeIdx: number
}

export function TrackingNotifBanner() {
  const { pathname } = useLocation()
  const profil = useStore((s) => s.profil)
  const [due, setDue] = useState<DueItem[]>([])
  const [dismissed, setDismissed] = useState(false)

  const refresh = async () => {
    if (!profil) return
    try {
      const [trackingList, awaitingList] = await Promise.all([
        api.trackingList('tracking'),
        api.trackingList('awaiting_validation'),
      ])
      const now = Date.now()
      const items: DueItem[] = []
      // Trackings en cours avec une periode due
      for (const t of trackingList.items || []) {
        if (!t.next_notif_at) continue
        const target = new Date(t.next_notif_at).getTime()
        if (now < target) continue
        const periodeIdx = t.choices.findIndex(c => c.choice === null)
        if (periodeIdx >= 0) items.push({ tracking: t, periodeIdx })
      }
      // Trackings en attente de validation (compte comme une notif)
      for (const t of awaitingList.items || []) {
        items.push({ tracking: t, periodeIdx: -1 /* sentinelle : validation */ })
      }
      setDue(items)
      // Reset dismissed quand de nouvelles notifs arrivent
      setDismissed(prev => prev && items.length === 0)
    } catch {
      // Silent fail : c'est un banner, pas critique
    }
  }

  useEffect(() => {
    if (!profil) return
    refresh()
    const id = setInterval(refresh, 30_000)
    return () => clearInterval(id)
  }, [profil?.id])

  // Pas afficher si :
  // - sur la page tracking déjà (visible naturellement)
  // - sur le wizard profil
  // - dismissed manuellement (réapparaitra dans 30s si toujours pertinent)
  if (
    !profil
    || due.length === 0
    || dismissed
    || pathname.startsWith('/tracking')
    || pathname.startsWith('/profil')
    || pathname.startsWith('/login')
  ) {
    return null
  }

  const nbValidation = due.filter(d => d.periodeIdx < 0).length
  const nbPeriodes = due.length - nbValidation

  return (
    <div
      role="alert"
      className="animate-fade-in"
      style={{
        position: 'sticky',
        top: '3.25rem', // hauteur de la NavBar
        zIndex: 90,
        background: 'linear-gradient(90deg, rgba(245,158,11,0.16), rgba(124,58,237,0.14), rgba(34,197,94,0.10))',
        backdropFilter: 'blur(10px)',
        borderBottom: '1px solid rgba(245,158,11,0.3)',
        padding: '0.65rem 1rem',
      }}
    >
      <div
        className="container container-lg"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: '1 1 auto', minWidth: 0 }}>
          {/* Pulse dot */}
          <div style={{ position: 'relative', width: '12px', height: '12px', flexShrink: 0 }}>
            <div style={{
              position: 'absolute', inset: 0,
              background: '#fbbf24',
              borderRadius: '50%',
              animation: 'pulse 1.4s ease-in-out infinite',
            }} />
            <div style={{
              position: 'absolute', inset: '3px',
              background: '#f59e0b',
              borderRadius: '50%',
            }} />
          </div>

          {/* Message */}
          <div style={{ flex: '1 1 auto', minWidth: 0 }}>
            <p style={{
              fontSize: '0.88rem',
              color: '#fbbf24',
              fontWeight: 600,
              margin: 0,
              lineHeight: 1.4,
            }}>
              {nbPeriodes > 0 && (
                <>
                  {nbPeriodes} période{nbPeriodes > 1 ? 's' : ''} à renseigner
                </>
              )}
              {nbPeriodes > 0 && nbValidation > 0 && ' · '}
              {nbValidation > 0 && (
                <>
                  {nbValidation} récap{nbValidation > 1 ? 's' : ''} à valider
                </>
              )}
            </p>
            <p style={{
              fontSize: '0.74rem',
              color: 'var(--text-muted)',
              margin: '0.1rem 0 0 0',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {due[0].tracking.question.slice(0, 80)}{due[0].tracking.question.length > 80 ? '…' : ''}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexShrink: 0 }}>
          <Link
            to="/tracking"
            style={{
              padding: '0.4rem 0.85rem',
              background: 'linear-gradient(135deg, #d4a017, #f59e0b)',
              color: '#0d0d14',
              fontSize: '0.82rem',
              fontWeight: 700,
              borderRadius: 'var(--radius-md)',
              textDecoration: 'none',
              whiteSpace: 'nowrap',
            }}
          >
            Répondre
          </Link>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            title="Masquer"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: '1.1rem',
              cursor: 'pointer',
              padding: '0.25rem 0.4rem',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>
      </div>
    </div>
  )
}
