// Modal in-app affiche QUAND une periode tracking arrive a echeance ET que
// l'utilisateur est focus sur l'app. Design "tech & addictif" :
//   - Overlay plein ecran avec backdrop blur
//   - Card animee avec gradient anime, scan line tech
//   - Pulse glow sur le countdown
//   - Boutons d'action grossis, micro-interactions au hover
//   - Confetti / animation de validation au clic
//   - "Skip" pour repousser au prochain poll/notif (pas ignore)

import { useEffect, useState, useRef } from 'react'
import { api } from '../api/client'

export interface TrackingPeriodPayload {
  tracking_id: string
  periode_idx: number
  question: string
  actions: { id: string; label: string }[]
  is_retry: boolean
  nb_periodes: number
}

interface Props {
  payload: TrackingPeriodPayload | null
  onClose: () => void
  onResponded?: () => void
}

export function TrackingPeriodModal({ payload, onClose, onResponded }: Props) {
  const [responding, setResponding] = useState<string | null>(null)
  const [responseError, setResponseError] = useState<string | null>(null)
  const [confirmedChoice, setConfirmedChoice] = useState<string | null>(null)
  const startTime = useRef(Date.now())

  // Auto-close apres confirmation (apres 1.6s d'animation)
  useEffect(() => {
    if (confirmedChoice) {
      const id = setTimeout(() => {
        onClose()
        onResponded?.()
      }, 1600)
      return () => clearTimeout(id)
    }
  }, [confirmedChoice, onClose, onResponded])

  if (!payload) return null

  const handleClick = async (choice: string) => {
    if (responding) return
    setResponding(choice)
    setResponseError(null)
    try {
      await api.trackingRespond(payload.tracking_id, payload.periode_idx, choice)
      setConfirmedChoice(choice)
    } catch (e: unknown) {
      setResponseError(e instanceof Error ? e.message : 'Erreur')
      setResponding(null)
    }
  }

  const elapsed = Math.floor((Date.now() - startTime.current) / 1000)

  return (
    <>
      <style>{`
        @keyframes sylea-scan {
          0% { transform: translateY(-100%); opacity: 0; }
          50% { opacity: 0.5; }
          100% { transform: translateY(100vh); opacity: 0; }
        }
        @keyframes sylea-glow-pulse {
          0%, 100% { box-shadow: 0 0 24px rgba(124,58,237,0.4), 0 0 48px rgba(212,160,23,0.15); }
          50%      { box-shadow: 0 0 36px rgba(124,58,237,0.7), 0 0 72px rgba(212,160,23,0.35); }
        }
        @keyframes sylea-pop {
          0%   { transform: scale(0.85) translateY(20px); opacity: 0; }
          60%  { transform: scale(1.02) translateY(-2px); opacity: 1; }
          100% { transform: scale(1) translateY(0); opacity: 1; }
        }
        @keyframes sylea-gradient-shift {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes sylea-confetti-burst {
          0%   { transform: scale(0) rotate(0deg); opacity: 1; }
          50%  { opacity: 1; }
          100% { transform: scale(2) rotate(360deg); opacity: 0; }
        }
        @keyframes sylea-check-draw {
          0%   { stroke-dashoffset: 60; }
          100% { stroke-dashoffset: 0; }
        }
      `}</style>
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed', inset: 0,
          zIndex: 9000,
          background: 'radial-gradient(ellipse at top, rgba(124,58,237,0.18), rgba(0,0,0,0.95))',
          backdropFilter: 'blur(20px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '1rem',
          overflow: 'hidden',
        }}
      >
        {/* Scan line tech */}
        <div style={{
          position: 'absolute', inset: 0,
          background: 'linear-gradient(180deg, transparent, rgba(124,58,237,0.08), transparent)',
          height: '40%',
          pointerEvents: 'none',
          animation: 'sylea-scan 4s linear infinite',
        }} />

        <div
          className="animate-fade-in"
          style={{
            maxWidth: '560px',
            width: '100%',
            background: 'linear-gradient(135deg, rgba(11,11,19,0.96), rgba(20,18,38,0.94), rgba(11,11,19,0.96))',
            backgroundSize: '200% 200%',
            animation: 'sylea-pop 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) backwards, sylea-glow-pulse 3.2s ease-in-out infinite, sylea-gradient-shift 12s ease infinite',
            border: '1px solid rgba(124,58,237,0.45)',
            borderRadius: '16px',
            padding: '1.85rem 1.65rem 1.65rem',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {/* Glow corners */}
          <div style={{ position: 'absolute', top: -40, right: -40, width: 140, height: 140, background: 'radial-gradient(circle, rgba(212,160,23,0.35), transparent)', pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', bottom: -40, left: -40, width: 140, height: 140, background: 'radial-gradient(circle, rgba(124,58,237,0.3), transparent)', pointerEvents: 'none' }} />

          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.65rem', position: 'relative' }}>
            <div style={{
              width: '38px', height: '38px',
              borderRadius: '10px',
              background: payload.is_retry
                ? 'linear-gradient(135deg, #b91c1c, #ef4444)'
                : 'linear-gradient(135deg, #7c3aed, #d4a017)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '1.05rem',
              color: 'white',
              fontWeight: 700,
              boxShadow: '0 4px 16px rgba(124,58,237,0.4)',
            }}>
              {payload.is_retry ? '⚡' : '◇'}
            </div>
            <div style={{ flex: 1 }}>
              <p style={{
                fontSize: '0.7rem',
                color: payload.is_retry ? '#fca5a5' : '#fbbf24',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
                margin: 0,
              }}>
                {payload.is_retry ? '⏰ RAPPEL — PÉRIODE NON RENSEIGNÉE' : 'NOUVELLE PÉRIODE DE SUIVI'}
              </p>
              <p style={{
                fontSize: '0.78rem',
                color: 'var(--text-muted)',
                margin: '0.15rem 0 0 0',
              }}>
                Période {payload.periode_idx + 1} / {payload.nb_periodes}
              </p>
            </div>
          </div>

          {/* Question */}
          <div style={{
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
            marginBottom: '1.1rem',
            fontSize: '0.94rem',
            color: 'var(--text-primary)',
            lineHeight: 1.5,
            position: 'relative',
          }}>
            <span style={{
              position: 'absolute', top: '-6px', left: '12px',
              padding: '2px 8px',
              background: 'var(--bg-surface)',
              color: 'var(--text-muted)',
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              borderRadius: '4px',
            }}>
              Qu'avez-vous fait ?
            </span>
            {payload.question}
          </div>

          {/* Confirmation success */}
          {confirmedChoice && (
            <div style={{
              padding: '1.5rem',
              background: 'rgba(34,197,94,0.08)',
              border: '1px solid rgba(34,197,94,0.4)',
              borderRadius: '12px',
              textAlign: 'center',
              position: 'relative',
            }}>
              {/* Confetti */}
              {[...Array(12)].map((_, i) => (
                <div key={i} style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  width: '6px', height: '6px',
                  borderRadius: '50%',
                  background: ['#7c3aed', '#d4a017', '#10b981', '#3b82f6'][i % 4],
                  transform: `translate(-50%, -50%) rotate(${i * 30}deg) translateY(-${30 + i * 4}px)`,
                  animation: `sylea-confetti-burst 1s ease-out ${i * 0.04}s both`,
                  pointerEvents: 'none',
                }} />
              ))}
              <svg viewBox="0 0 60 60" width="48" height="48" style={{ marginBottom: '0.5rem' }}>
                <circle cx="30" cy="30" r="26" fill="rgba(34,197,94,0.18)" stroke="#22c55e" strokeWidth="2" />
                <path d="M18,30 L27,38 L42,22" fill="none" stroke="#22c55e" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="60" style={{ animation: 'sylea-check-draw 0.5s ease-out 0.1s both' }} />
              </svg>
              <p style={{ color: '#4ade80', fontWeight: 600, fontSize: '0.92rem', margin: 0 }}>
                Réponse enregistrée
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: '0.35rem' }}>
                Merci. Sylea continuera à suivre.
              </p>
            </div>
          )}

          {/* Actions */}
          {!confirmedChoice && (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '0.85rem' }}>
                {payload.actions.map((a, idx) => {
                  const isNone = a.id === 'none'
                  const isLoading = responding === a.id
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => handleClick(a.id)}
                      disabled={responding !== null}
                      style={{
                        padding: '0.85rem 1rem',
                        background: isNone
                          ? 'rgba(148,163,184,0.08)'
                          : `linear-gradient(135deg, rgba(124,58,237,${0.1 + idx * 0.04}), rgba(212,160,23,0.05))`,
                        border: isNone
                          ? '1px solid rgba(148,163,184,0.22)'
                          : '1px solid rgba(124,58,237,0.35)',
                        borderRadius: '10px',
                        color: isNone ? '#cbd5e1' : 'var(--text-primary)',
                        cursor: responding !== null ? 'wait' : 'pointer',
                        fontSize: '0.92rem',
                        fontWeight: 500,
                        textAlign: 'left',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.65rem',
                        transition: 'transform 0.15s, box-shadow 0.15s',
                        opacity: responding !== null && !isLoading ? 0.45 : 1,
                      }}
                      onMouseEnter={(e) => {
                        if (responding === null) {
                          (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)'
                          ;(e.currentTarget as HTMLElement).style.boxShadow = '0 6px 20px rgba(124,58,237,0.25)'
                        }
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLElement).style.transform = 'translateY(0)'
                        ;(e.currentTarget as HTMLElement).style.boxShadow = 'none'
                      }}
                    >
                      <div style={{
                        width: '28px', height: '28px',
                        borderRadius: '50%',
                        background: isNone
                          ? 'rgba(148,163,184,0.15)'
                          : 'linear-gradient(135deg, var(--accent-violet), var(--accent-gold))',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        color: isNone ? '#94a3b8' : 'white',
                        flexShrink: 0,
                      }}>
                        {isNone ? '—' : String.fromCharCode(65 + idx)}
                      </div>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        {a.label}
                      </span>
                      {isLoading && (
                        <span style={{
                          width: '14px', height: '14px',
                          borderRadius: '50%',
                          border: '2px solid rgba(255,255,255,0.2)',
                          borderTopColor: 'white',
                          animation: 'spin 0.8s linear infinite',
                          flexShrink: 0,
                        }} />
                      )}
                    </button>
                  )
                })}
              </div>

              {responseError && (
                <div style={{ padding: '0.5rem 0.75rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: '6px', color: '#fca5a5', fontSize: '0.78rem', marginBottom: '0.65rem' }}>
                  ⚠ {responseError}
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}>
                  ◢ {elapsed}s elapsed
                </span>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-muted)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    padding: '0.2rem 0.5rem',
                  }}
                >
                  Plus tard ›
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
