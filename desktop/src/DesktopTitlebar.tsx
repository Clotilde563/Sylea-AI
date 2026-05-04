/**
 * Custom titlebar pour la fenetre frameless (Sprint 1 — feature 1.7)
 *
 * - Bandeau drag draggable (drag la fenetre en glissant)
 * - Boutons systeme : Pill mode / Minimize / Maximize / Close
 * - Logo + nom Sylea Agent a gauche
 *
 * Hauteur fixe : 36px. Couleur : bg sombre tech avec border bottom cyan.
 */
import { useState, useEffect } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

interface Props {
  onTogglePill?: () => void
  isPill?: boolean
  /** Slots optionnels affiches a gauche des boutons systeme (theme switcher, sound toggle) */
  extraButtons?: React.ReactNode
  /** Couleur d'accent — depend du theme actif */
  accent?: string
}

export function DesktopTitlebar({
  onTogglePill,
  isPill = false,
  extraButtons,
  accent = '#7ad9ff',
}: Props) {
  const [maximized, setMaximized] = useState(false)
  const win = getCurrentWindow()

  useEffect(() => {
    const refresh = async () => {
      try { setMaximized(await win.isMaximized()) } catch {}
    }
    refresh()
    const unsub = win.onResized(() => { refresh() })
    return () => { unsub.then((fn) => fn()).catch(() => {}) }
  }, [win])

  const onMin = async () => { try { await win.minimize() } catch {} }
  const onMax = async () => { try { await win.toggleMaximize() } catch {} }
  const onClose = async () => { try { await win.hide() } catch {} }

  // Hauteur reduite en pill mode (24px) sinon 36px
  const h = isPill ? 24 : 36

  return (
    <div
      data-tauri-drag-region
      style={{
        height: h,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: isPill ? '0 0.5rem' : '0 0.85rem',
        background: 'rgba(5,8,16,0.95)',
        borderBottom: '1px solid rgba(0,200,255,0.18)',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        backdropFilter: 'blur(8px)',
      }}
    >
      {/* Logo + nom — drag-region */}
      <div
        data-tauri-drag-region
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          fontFamily: '"JetBrains Mono","Fira Code",monospace',
          fontSize: isPill ? 10 : 11,
          fontWeight: 600,
          letterSpacing: '0.06em',
          color: '#7ad9ff',
        }}
      >
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: '#00c8ff', boxShadow: '0 0 8px #00c8ff',
          animation: 'sy-pulse 2s ease-in-out infinite',
        }} />
        {!isPill && <span>SYLEA AGENT</span>}
      </div>

      {/* Boutons systeme */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {/* Slots extras (theme, son, ...) */}
        {extraButtons}
        {/* Pill toggle */}
        {onTogglePill && (
          <TitlebarButton
            onClick={onTogglePill}
            title={isPill ? 'Mode plein' : 'Mode pill compact'}
            color={accent}
          >
            {isPill ? (
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                <rect x="2" y="2" width="12" height="12" stroke="currentColor" strokeWidth="1.2" rx="1.5" />
              </svg>
            ) : (
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="6" width="10" height="4" stroke="currentColor" strokeWidth="1.2" rx="2" />
              </svg>
            )}
          </TitlebarButton>
        )}
        {!isPill && (
          <TitlebarButton onClick={onMin} title="Reduire" color={accent}>
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <line x1="3" y1="13" x2="13" y2="13" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </TitlebarButton>
        )}
        {!isPill && (
          <TitlebarButton onClick={onMax} title={maximized ? 'Restaurer' : 'Agrandir'} color={accent}>
            {maximized ? (
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="5" width="8" height="8" stroke="currentColor" strokeWidth="1.2" />
                <rect x="5" y="3" width="8" height="8" stroke="currentColor" strokeWidth="1.2" />
              </svg>
            ) : (
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="3" width="10" height="10" stroke="currentColor" strokeWidth="1.2" />
              </svg>
            )}
          </TitlebarButton>
        )}
        <TitlebarButton onClick={onClose} title="Cacher (revient via tray)" color="#ef4444">
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
            <line x1="4" y1="4" x2="12" y2="12" stroke="currentColor" strokeWidth="1.2" />
            <line x1="12" y1="4" x2="4" y2="12" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        </TitlebarButton>
      </div>
    </div>
  )
}

interface BtnProps {
  onClick: () => void
  title: string
  color: string
  children: React.ReactNode
}

function TitlebarButton({ onClick, title, color, children }: BtnProps) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: 22,
        height: 22,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        color,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(0,200,255,0.12)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
    >
      {children}
    </button>
  )
}
