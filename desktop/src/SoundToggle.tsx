/**
 * Bouton toggle ON/OFF pour les sons UI (Sprint 2 — feature 2.3)
 *
 * Petit bouton speaker dans la titlebar. Cycle muted ↔ enabled.
 * Joue un "click" en se reactivant (feedback que ca marche).
 */
import { useSound } from './useSound'

interface Props {
  size?: number
  color?: string
}

export function SoundToggle({ size = 22, color = '#7ad9ff' }: Props) {
  const { enabled, toggle, play } = useSound()

  const onClick = () => {
    if (!enabled) {
      // On enable: play feedback after toggling state
      toggle()
      // Short delay so ref updates first
      setTimeout(() => play('click'), 30)
    } else {
      play('click')
      toggle()
    }
  }

  return (
    <button
      onClick={onClick}
      title={enabled ? 'Desactiver les sons UI' : 'Activer les sons UI'}
      style={{
        width: size, height: size,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'transparent', border: 'none', borderRadius: 4,
        color: enabled ? color : 'rgba(230, 240, 255, 0.30)',
        cursor: 'pointer',
        transition: 'background 0.15s, color 0.2s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(0, 200, 255, 0.10)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
    >
      {enabled ? (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <line x1="23" y1="9" x2="17" y2="15"/>
          <line x1="17" y1="9" x2="23" y2="15"/>
        </svg>
      )}
    </button>
  )
}

export default SoundToggle
