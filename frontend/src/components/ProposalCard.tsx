// Carte affichée sous un message d'agent quand celui-ci propose
// d'enregistrer un événement/décision majeure. L'utilisateur valide
// ou refuse via deux boutons cliquables.

import { useState } from 'react'

interface Proposal {
  id: string
  agent_label: string
  type: string
  description: string
  impact_jours: number
  resume: string
  rationale: string
  target_so_hint: string
  statut: 'pending' | 'confirmed' | 'rejected'
}

interface Props {
  proposal: Proposal
  onConfirm: () => void | Promise<void>
  onReject: () => void | Promise<void>
}

function formatImpactJours(jours: number): string {
  const abs = Math.abs(jours)
  if (abs < 7) return `${abs.toFixed(0)} jour${abs >= 2 ? 's' : ''}`
  if (abs < 60) return `${(abs / 7).toFixed(0)} semaines`
  if (abs < 365) return `${(abs / 30).toFixed(0)} mois`
  const y = Math.floor(abs / 365)
  const m = Math.floor((abs % 365) / 30)
  return m > 0 ? `${y} an${y >= 2 ? 's' : ''} ${m}m` : `${y} an${y >= 2 ? 's' : ''}`
}

export function ProposalCard({ proposal, onConfirm, onReject }: Props) {
  const [busy, setBusy] = useState<'confirm' | 'reject' | null>(null)
  const isPositive = proposal.impact_jours >= 0
  const isPending = proposal.statut === 'pending'
  const isConfirmed = proposal.statut === 'confirmed'
  const isRejected = proposal.statut === 'rejected'

  const handleConfirm = async () => {
    if (busy || !isPending) return
    setBusy('confirm')
    try {
      await onConfirm()
    } finally {
      setBusy(null)
    }
  }

  const handleReject = async () => {
    if (busy || !isPending) return
    setBusy('reject')
    try {
      await onReject()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{
      marginTop: '0.5rem',
      padding: '0.85rem 1rem',
      borderRadius: '12px',
      background: isConfirmed
        ? 'rgba(34,197,94,0.08)'
        : isRejected
          ? 'rgba(100,116,139,0.05)'
          : 'linear-gradient(135deg, rgba(34,211,238,0.06), rgba(139,92,246,0.06))',
      border: isConfirmed
        ? '1px solid rgba(34,197,94,0.35)'
        : isRejected
          ? '1px solid rgba(100,116,139,0.2)'
          : '1px solid rgba(139,92,246,0.25)',
      boxShadow: isPending ? '0 0 14px rgba(139,92,246,0.08)' : 'none',
      opacity: isRejected ? 0.55 : 1,
      transition: 'all 0.2s ease',
    }}>
      {/* Label */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        fontSize: '0.65rem', fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.06em',
        color: isConfirmed ? '#22c55e' : isRejected ? '#64748b' : '#a78bfa',
        marginBottom: '0.5rem',
      }}>
        <span>{isConfirmed ? '✓ Enregistré' : isRejected ? '✕ Ignoré' : 'Proposition de l\'agent'}</span>
        <span style={{
          fontSize: '0.6rem',
          padding: '0.05rem 0.4rem',
          borderRadius: '4px',
          background: isPending ? 'rgba(139,92,246,0.15)' : 'transparent',
          color: isPending ? '#c4b5fd' : 'inherit',
        }}>
          {proposal.type === 'decision_majeure' ? 'Décision' : 'Événement'}
        </span>
      </div>

      {/* Description principale */}
      <div style={{
        color: 'var(--text-primary)',
        fontSize: '0.85rem', fontWeight: 600,
        marginBottom: '0.35rem', lineHeight: 1.4,
      }}>
        {proposal.description}
      </div>

      {/* Résumé contextuel */}
      {proposal.resume && (
        <div style={{
          color: 'var(--text-muted)',
          fontSize: '0.74rem', lineHeight: 1.5,
          marginBottom: '0.6rem',
        }}>
          {proposal.resume}
        </div>
      )}

      {/* Impact estimé */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.4rem 0.65rem',
        borderRadius: '8px',
        background: 'rgba(255,255,255,0.03)',
        marginBottom: isPending ? '0.7rem' : 0,
      }}>
        <span style={{
          fontSize: '0.62rem', textTransform: 'uppercase',
          letterSpacing: '0.05em', color: 'var(--text-muted)', fontWeight: 600,
        }}>
          Impact estimé
        </span>
        <span style={{
          fontSize: '0.82rem', fontWeight: 700,
          color: isPositive ? '#22c55e' : '#ef4444',
        }}>
          {isPositive ? '+' : '−'}{formatImpactJours(proposal.impact_jours)} sur l'objectif
        </span>
        {proposal.target_so_hint && (
          <span style={{
            marginLeft: 'auto', fontSize: '0.68rem',
            color: 'var(--text-muted)', fontStyle: 'italic',
          }}>
            via {proposal.target_so_hint}
          </span>
        )}
      </div>

      {/* Buttons */}
      {isPending && (
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            onClick={handleConfirm}
            disabled={busy !== null}
            style={{
              flex: 1,
              padding: '0.5rem 0.9rem',
              borderRadius: '8px',
              border: '1px solid rgba(34,197,94,0.5)',
              background: busy === 'confirm'
                ? 'rgba(34,197,94,0.35)'
                : 'rgba(34,197,94,0.18)',
              color: '#22c55e',
              fontWeight: 600,
              fontSize: '0.78rem',
              cursor: busy ? 'wait' : 'pointer',
              transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.35rem',
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.background = 'rgba(34,197,94,0.28)' }}
            onMouseLeave={e => { if (!busy) e.currentTarget.style.background = 'rgba(34,197,94,0.18)' }}
          >
            {busy === 'confirm' ? '...' : '✓ Confirmer'}
          </button>
          <button
            onClick={handleReject}
            disabled={busy !== null}
            style={{
              flex: 1,
              padding: '0.5rem 0.9rem',
              borderRadius: '8px',
              border: '1px solid rgba(239,68,68,0.4)',
              background: busy === 'reject'
                ? 'rgba(239,68,68,0.25)'
                : 'rgba(239,68,68,0.08)',
              color: '#f87171',
              fontWeight: 600,
              fontSize: '0.78rem',
              cursor: busy ? 'wait' : 'pointer',
              transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.35rem',
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.background = 'rgba(239,68,68,0.16)' }}
            onMouseLeave={e => { if (!busy) e.currentTarget.style.background = 'rgba(239,68,68,0.08)' }}
          >
            {busy === 'reject' ? '...' : '✕ Refuser'}
          </button>
        </div>
      )}
    </div>
  )
}
