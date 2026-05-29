// Modal in-app affiche QUAND une periode tracking arrive a echeance ET que
// l'utilisateur est focus sur l'app. Design tech-addictif aux couleurs Sylea
// (violet #5520b8 -> bleu #1848d8 -> cyan #00c8ff).
//   - Overlay plein ecran avec backdrop blur + grid Tron animee
//   - Card holographique avec border shimmer + glow pulse
//   - Scan lines animees + glow corners
//   - Boutons d'action avec lettre A/B/... et description complete de l'option
//   - "Aucun des deux" discret en bas
//   - Confetti + check SVG draw a la confirmation
//   - "Plus tard" repousse au prochain poll/notif

import { useEffect, useState, useRef } from 'react'
import { api } from '../api/client'

// Palette officielle Sylea (alignee sur TrackingsPage)
const SYLEA = {
  violet: '#5520b8',
  blue: '#1848d8',
  cyan: '#00c8ff',
  cyanGlow: '#00c8ff80',
}

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
  // Separer Aucun des choix principaux pour l'afficher discretement en bas
  const mainActions = payload.actions.filter(a => a.id !== 'none')
  const noneAction = payload.actions.find(a => a.id === 'none')

  return (
    <>
      <style>{`
        @keyframes sylea-modal-grid {
          0% { background-position: 0 0, 0 0; }
          100% { background-position: 50px 50px, 50px 50px; }
        }
        @keyframes sylea-modal-shimmer {
          0% { background-position: -200% 50%; }
          100% { background-position: 200% 50%; }
        }
        @keyframes sylea-modal-scan {
          0%   { transform: translateY(-100%); opacity: 0; }
          50%  { opacity: 0.6; }
          100% { transform: translateY(100vh); opacity: 0; }
        }
        @keyframes sylea-modal-glow {
          0%, 100% { box-shadow: 0 0 24px ${SYLEA.violet}88, 0 0 60px ${SYLEA.cyan}33; }
          50%      { box-shadow: 0 0 40px ${SYLEA.blue}aa, 0 0 100px ${SYLEA.cyan}55; }
        }
        @keyframes sylea-modal-pop {
          0%   { transform: scale(0.85) translateY(20px); opacity: 0; }
          60%  { transform: scale(1.02) translateY(-2px); opacity: 1; }
          100% { transform: scale(1) translateY(0); opacity: 1; }
        }
        @keyframes sylea-modal-confetti {
          0%   { transform: scale(0) rotate(0deg); opacity: 1; }
          50%  { opacity: 1; }
          100% { transform: scale(2) rotate(360deg); opacity: 0; }
        }
        @keyframes sylea-modal-check {
          0%   { stroke-dashoffset: 60; }
          100% { stroke-dashoffset: 0; }
        }
        @keyframes sylea-modal-pulse-dot {
          0%, 100% { opacity: 0.7; transform: scale(1); }
          50%      { opacity: 1;   transform: scale(1.15); }
        }
        @keyframes sylea-modal-scan-h {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(200%); }
        }

        .sylea-modal-card {
          position: relative;
          background: linear-gradient(135deg, rgba(11,14,28,0.94), rgba(20,18,38,0.92), rgba(11,14,28,0.94));
          border: 1px solid ${SYLEA.violet}88;
          border-radius: 18px;
          padding: 1.9rem 1.7rem 1.65rem;
          overflow: hidden;
          backdrop-filter: blur(14px);
        }
        .sylea-modal-card::before {
          content: '';
          position: absolute;
          inset: -1px;
          border-radius: 18px;
          padding: 1px;
          background: linear-gradient(120deg, transparent 25%, ${SYLEA.cyan}, transparent 75%);
          background-size: 200% 100%;
          -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
          -webkit-mask-composite: xor;
                  mask-composite: exclude;
          animation: sylea-modal-shimmer 5s linear infinite;
          pointer-events: none;
        }

        .sylea-modal-action {
          padding: 0.9rem 1rem;
          border-radius: 12px;
          border: 1px solid ${SYLEA.violet}55;
          background: linear-gradient(135deg, ${SYLEA.violet}20, ${SYLEA.blue}15, ${SYLEA.cyan}10);
          color: var(--text-primary);
          cursor: pointer;
          font-size: 0.93rem;
          font-weight: 500;
          text-align: left;
          display: flex;
          align-items: center;
          gap: 0.75rem;
          transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
          position: relative;
          overflow: hidden;
        }
        .sylea-modal-action:hover:not(:disabled) {
          transform: translateY(-2px);
          border-color: ${SYLEA.cyan};
          box-shadow: 0 8px 28px ${SYLEA.cyan}44, inset 0 1px 0 rgba(255,255,255,0.08);
        }
        .sylea-modal-action:hover:not(:disabled)::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
          animation: sylea-modal-scan-h 1.2s linear;
          pointer-events: none;
        }
        .sylea-modal-action[disabled] { opacity: 0.45; cursor: wait; }

        .sylea-modal-action-none {
          padding: 0.65rem 1rem !important;
          background: rgba(148,163,184,0.06) !important;
          border: 1px solid rgba(148,163,184,0.2) !important;
          color: #cbd5e1 !important;
          font-size: 0.85rem !important;
          justify-content: center !important;
        }
        .sylea-modal-action-none:hover:not(:disabled) {
          border-color: rgba(148,163,184,0.4) !important;
          background: rgba(148,163,184,0.1) !important;
          box-shadow: 0 4px 14px rgba(148,163,184,0.2) !important;
        }

        .sylea-modal-letter {
          width: 32px; height: 32px;
          border-radius: 10px;
          background: linear-gradient(135deg, ${SYLEA.violet}, ${SYLEA.blue}, ${SYLEA.cyan});
          color: #fff;
          font-weight: 800;
          font-family: var(--font-mono, ui-monospace, monospace);
          font-size: 0.95rem;
          display: flex; align-items: center; justify-content: center;
          flex-shrink: 0;
          box-shadow: 0 0 14px ${SYLEA.cyan}55, inset 0 1px 0 rgba(255,255,255,0.2);
        }
      `}</style>

      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed', inset: 0,
          zIndex: 9000,
          background: `radial-gradient(ellipse at top, ${SYLEA.violet}33, rgba(2,5,15,0.96))`,
          backdropFilter: 'blur(20px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '1rem',
          overflow: 'hidden',
        }}
      >
        {/* Tron grid background */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: `
            linear-gradient(${SYLEA.cyan}11 1px, transparent 1px),
            linear-gradient(90deg, ${SYLEA.cyan}11 1px, transparent 1px)
          `,
          backgroundSize: '50px 50px',
          animation: 'sylea-modal-grid 20s linear infinite',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 80%)',
          pointerEvents: 'none',
        }} />

        {/* Scan line tech */}
        <div style={{
          position: 'absolute', inset: 0,
          background: `linear-gradient(180deg, transparent, ${SYLEA.cyan}11, transparent)`,
          height: '40%',
          pointerEvents: 'none',
          animation: 'sylea-modal-scan 4.5s linear infinite',
        }} />

        <div
          className="sylea-modal-card"
          style={{
            maxWidth: '560px',
            width: '100%',
            animation: 'sylea-modal-pop 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) backwards, sylea-modal-glow 3.2s ease-in-out infinite',
          }}
        >
          {/* Glow corners */}
          <div style={{ position: 'absolute', top: -50, right: -50, width: 160, height: 160, background: `radial-gradient(circle, ${SYLEA.cyan}33, transparent)`, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', bottom: -50, left: -50, width: 160, height: 160, background: `radial-gradient(circle, ${SYLEA.violet}55, transparent)`, pointerEvents: 'none' }} />

          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', marginBottom: '0.85rem', position: 'relative' }}>
            <div style={{
              width: '42px', height: '42px',
              borderRadius: '12px',
              background: payload.is_retry
                ? 'linear-gradient(135deg, #b91c1c, #ef4444)'
                : `linear-gradient(135deg, ${SYLEA.violet}, ${SYLEA.blue}, ${SYLEA.cyan})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '1.15rem',
              color: 'white',
              fontWeight: 700,
              boxShadow: payload.is_retry
                ? '0 4px 18px rgba(239,68,68,0.45)'
                : `0 4px 18px ${SYLEA.cyan}66, inset 0 1px 0 rgba(255,255,255,0.2)`,
            }}>
              {payload.is_retry ? '⚡' : '◇'}
            </div>
            <div style={{ flex: 1 }}>
              <p style={{
                fontSize: '0.7rem',
                color: payload.is_retry ? '#fca5a5' : SYLEA.cyan,
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: '0.16em',
                fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                margin: 0,
                textShadow: payload.is_retry ? 'none' : `0 0 10px ${SYLEA.cyanGlow}`,
                display: 'flex',
                alignItems: 'center',
                gap: '0.45rem',
              }}>
                <span style={{
                  width: 6, height: 6,
                  borderRadius: '50%',
                  background: payload.is_retry ? '#fca5a5' : SYLEA.cyan,
                  boxShadow: `0 0 8px ${payload.is_retry ? '#fca5a5' : SYLEA.cyan}`,
                  animation: 'sylea-modal-pulse-dot 1.5s ease-in-out infinite',
                }} />
                {payload.is_retry ? 'RAPPEL — PÉRIODE NON RENSEIGNÉE' : 'NOUVELLE PÉRIODE DE SUIVI'}
              </p>
              <p style={{
                fontSize: '0.78rem',
                color: 'var(--text-muted)',
                margin: '0.25rem 0 0 0',
                fontFamily: 'var(--font-mono, ui-monospace, monospace)',
              }}>
                ◢ Période {payload.periode_idx + 1} / {payload.nb_periodes}
              </p>
            </div>
          </div>

          {/* Question */}
          <div style={{
            background: 'rgba(255,255,255,0.02)',
            border: `1px solid ${SYLEA.cyan}22`,
            borderRadius: '12px',
            padding: '0.95rem 1.05rem',
            marginBottom: '1.2rem',
            fontSize: '0.95rem',
            color: 'var(--text-primary)',
            lineHeight: 1.55,
            position: 'relative',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)',
          }}>
            <span style={{
              position: 'absolute', top: '-8px', left: '14px',
              padding: '2px 10px',
              background: 'rgba(11,14,28,0.95)',
              color: SYLEA.cyan,
              fontSize: '0.62rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              borderRadius: '4px',
              border: `1px solid ${SYLEA.cyan}33`,
              fontFamily: 'var(--font-mono, ui-monospace, monospace)',
            }}>
              Qu'avez-vous fait ?
            </span>
            {payload.question}
          </div>

          {/* Confirmation success */}
          {confirmedChoice && (
            <div style={{
              padding: '1.6rem',
              background: 'linear-gradient(135deg, rgba(34,197,94,0.1), rgba(16,185,129,0.05))',
              border: '1px solid rgba(34,197,94,0.45)',
              borderRadius: '14px',
              textAlign: 'center',
              position: 'relative',
              overflow: 'hidden',
            }}>
              {/* Confetti aux couleurs Sylea */}
              {[...Array(14)].map((_, i) => (
                <div key={i} style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  width: '7px', height: '7px',
                  borderRadius: '50%',
                  background: [SYLEA.violet, SYLEA.blue, SYLEA.cyan, '#22c55e', '#fff'][i % 5],
                  transform: `translate(-50%, -50%) rotate(${i * 26}deg) translateY(-${30 + i * 4}px)`,
                  animation: `sylea-modal-confetti 1s ease-out ${i * 0.035}s both`,
                  pointerEvents: 'none',
                  boxShadow: `0 0 6px ${[SYLEA.violet, SYLEA.blue, SYLEA.cyan, '#22c55e', '#fff'][i % 5]}88`,
                }} />
              ))}
              <svg viewBox="0 0 60 60" width="52" height="52" style={{ marginBottom: '0.6rem' }}>
                <circle cx="30" cy="30" r="26" fill="rgba(34,197,94,0.18)" stroke="#22c55e" strokeWidth="2" />
                <path d="M18,30 L27,38 L42,22" fill="none" stroke="#22c55e" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="60" style={{ animation: 'sylea-modal-check 0.5s ease-out 0.1s both' }} />
              </svg>
              <p style={{ color: '#4ade80', fontWeight: 700, fontSize: '0.98rem', margin: 0 }}>
                Réponse enregistrée
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.4rem' }}>
                Sylea continuera à suivre votre engagement.
              </p>
            </div>
          )}

          {/* Actions */}
          {!confirmedChoice && (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem', marginBottom: '0.9rem' }}>
                {mainActions.map((a, idx) => {
                  const isLoading = responding === a.id
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => handleClick(a.id)}
                      disabled={responding !== null}
                      className="sylea-modal-action"
                    >
                      <div className="sylea-modal-letter">
                        {String.fromCharCode(65 + idx)}
                      </div>
                      <span style={{ flex: 1, minWidth: 0, lineHeight: 1.35 }}>
                        {a.label}
                      </span>
                      {isLoading && (
                        <span style={{
                          width: '16px', height: '16px',
                          borderRadius: '50%',
                          border: `2px solid ${SYLEA.cyan}33`,
                          borderTopColor: SYLEA.cyan,
                          animation: 'spin 0.7s linear infinite',
                          flexShrink: 0,
                          boxShadow: `0 0 10px ${SYLEA.cyan}66`,
                        }} />
                      )}
                    </button>
                  )
                })}

                {/* "Aucun des deux" en bas, discret */}
                {noneAction && (
                  <button
                    type="button"
                    onClick={() => handleClick(noneAction.id)}
                    disabled={responding !== null}
                    className="sylea-modal-action sylea-modal-action-none"
                  >
                    — {noneAction.label}
                    {responding === noneAction.id && (
                      <span style={{
                        width: '14px', height: '14px',
                        borderRadius: '50%',
                        border: '2px solid rgba(148,163,184,0.3)',
                        borderTopColor: '#cbd5e1',
                        animation: 'spin 0.7s linear infinite',
                        marginLeft: '0.5rem',
                      }} />
                    )}
                  </button>
                )}
              </div>

              {responseError && (
                <div style={{
                  padding: '0.55rem 0.85rem',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.25)',
                  borderRadius: '8px',
                  color: '#fca5a5',
                  fontSize: '0.78rem',
                  marginBottom: '0.65rem',
                }}>
                  ⚠ {responseError}
                </div>
              )}

              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: '0.7rem',
                color: 'var(--text-muted)',
                paddingTop: '0.7rem',
                borderTop: `1px solid ${SYLEA.cyan}11`,
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono, ui-monospace, monospace)',
                  letterSpacing: '0.06em',
                  color: SYLEA.cyan,
                  textShadow: `0 0 6px ${SYLEA.cyanGlow}`,
                }}>
                  ◢ {elapsed}s
                </span>
                <button
                  type="button"
                  onClick={onClose}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-muted)',
                    fontSize: '0.78rem',
                    cursor: 'pointer',
                    padding: '0.2rem 0.55rem',
                    transition: 'color 0.15s',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#fff' }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--text-muted)' }}
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
