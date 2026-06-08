// Bandeau sticky en haut du dashboard pour les vérifications dues.
//
// Affiche la 1re pending_action dont prochaine_verification_le <= now.
// L'utilisateur peut répondre Oui/Non directement → le pending bascule en
// completed/abandoned et le bandeau passe à la suivante (ou disparaît).

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { PendingAction } from '../types'

function formatJours(j: number): string {
  const abs = Math.abs(j)
  const sign = j >= 0 ? '+' : '-'
  const totalHeures = abs * 24
  if (totalHeures < 1) {
    const minutes = Math.max(1, Math.round(totalHeures * 60))
    return `${sign}${minutes}min`
  }
  if (abs < 1) {
    const heures = totalHeures < 10 ? Math.round(totalHeures * 10) / 10 : Math.round(totalHeures)
    return `${sign}${heures}h`
  }
  if (abs < 30) return `${sign}${abs.toFixed(abs < 10 ? 1 : 0)}j`
  if (abs < 365) {
    const mois = Math.round(abs / 30 * 10) / 10
    return `${sign}${mois}m`
  }
  const ans = Math.round(abs / 365 * 10) / 10
  return `${sign}${ans}a`
}

export function PendingVerificationBanner() {
  const navigate = useNavigate()
  const [due, setDue] = useState<PendingAction[]>([])
  const [responding, setResponding] = useState(false)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const fetchDue = useCallback(async () => {
    try {
      const list = await api.listPendingDue()
      setDue(list)
    } catch {
      // 401/network : on ignore silencieusement
    }
  }, [])

  useEffect(() => {
    fetchDue()
    const interval = setInterval(fetchDue, 30_000)
    return () => clearInterval(interval)
  }, [fetchDue])

  // Premier pending non-dismiss
  const current = due.find(p => !dismissed.has(p.id))
  if (!current) return null

  const isPositive = current.impact_jours >= 0
  const accentColor = isPositive ? '#4ade80' : '#fbbf24'
  const accentBg = isPositive
    ? 'linear-gradient(135deg, rgba(34,197,94,0.10), rgba(245,158,11,0.08))'
    : 'linear-gradient(135deg, rgba(245,158,11,0.12), rgba(239,68,68,0.08))'

  const question = current.is_final_check
    ? 'Tu as bien réalisé intégralement cette action ?'
    : current.is_long_terme
      ? 'Es-tu toujours en train de réaliser cette action ?'
      : 'Tu as bien réalisé cette action ?'

  const handleRespond = async (response: boolean) => {
    setResponding(true)
    try {
      await api.respondPending(current.id, response)
      await fetchDue()
    } catch {
      // En cas d'erreur, on dismiss localement pour ne pas bloquer
      setDismissed(prev => new Set(prev).add(current.id))
    } finally {
      setResponding(false)
    }
  }

  return (
    <div style={{
      background: accentBg,
      borderBottom: `1px solid ${accentColor}55`,
      padding: '14px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 16,
      flexWrap: 'wrap',
      position: 'sticky',
      top: 0,
      zIndex: 90,
      backdropFilter: 'blur(12px)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ fontSize: 22, lineHeight: 1, flexShrink: 0 }} aria-hidden>
          {current.is_final_check ? '🎯' : '⏰'}
        </div>
        <div style={{ flex: 1, minWidth: 0, fontSize: 13.5, lineHeight: 1.45, color: 'rgba(255,255,255,0.92)' }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>
            {question}
          </div>
          <div style={{ opacity: 0.78, fontSize: 12.5 }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              color: accentColor,
              fontWeight: 700,
              marginRight: 8,
            }}>
              {formatJours(current.impact_jours)}
            </span>
            {current.description}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <button
          onClick={() => handleRespond(false)}
          disabled={responding}
          style={{
            padding: '7px 14px',
            borderRadius: 8,
            border: '1px solid rgba(239,68,68,0.4)',
            background: 'transparent',
            color: '#f87171',
            fontSize: 13,
            fontWeight: 600,
            cursor: responding ? 'wait' : 'pointer',
            opacity: responding ? 0.5 : 1,
          }}
        >
          Non
        </button>
        <button
          onClick={() => handleRespond(true)}
          disabled={responding}
          style={{
            padding: '7px 16px',
            borderRadius: 8,
            border: 'none',
            background: current.is_final_check
              ? 'linear-gradient(135deg, #10b981, #059669)'
              : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
            color: 'white',
            fontSize: 13,
            fontWeight: 600,
            cursor: responding ? 'wait' : 'pointer',
            boxShadow: '0 2px 8px rgba(99,102,241,0.3)',
            opacity: responding ? 0.5 : 1,
          }}
        >
          {current.is_final_check ? 'Oui ✓' : 'Oui'}
        </button>
        <button
          onClick={() => navigate('/progression-decisions')}
          title="Voir toutes les décisions en attente"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'rgba(255,255,255,0.5)',
            cursor: 'pointer',
            fontSize: 16,
            padding: '4px 8px',
            lineHeight: 1,
          }}
        >
          ↗
        </button>
      </div>
    </div>
  )
}

export default PendingVerificationBanner
