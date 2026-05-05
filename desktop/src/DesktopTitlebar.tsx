/**
 * Custom titlebar pour la fenetre frameless (Sprint 1 — feature 1.7)
 *
 * - Bandeau drag draggable (drag la fenetre en glissant)
 * - Boutons systeme : Pill mode / Minimize / Maximize / Close
 * - Logo + nom Sylea Agent a gauche
 *
 * Hauteur fixe : 44px (style Windows 11). Boutons systeme 46x44 type
 * caption-button Windows pour un clic facile et un look natif.
 */
import { useState, useEffect } from 'react'
import { getCurrentWindow } from '@tauri-apps/api/window'

interface Props {
  onTogglePill?: () => void
  isPill?: boolean
  /** Slots optionnels affiches a gauche des boutons systeme */
  extraButtons?: React.ReactNode
  /** Couleur d'accent */
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

  // Hauteur reduite en pill mode (28px) sinon 44px (style Win11)
  const h = isPill ? 28 : 44

  return (
    <div
      data-tauri-drag-region
      style={{
        height: h,
        display: 'flex',
        alignItems: 'stretch', // les boutons remplissent toute la hauteur
        justifyContent: 'space-between',
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
          gap: '0.45rem',
          padding: isPill ? '0 0.6rem' : '0 1rem',
          fontFamily: '"JetBrains Mono","Fira Code",monospace',
          fontSize: isPill ? 10 : 12,
          fontWeight: 700,
          letterSpacing: '0.08em',
          color: '#7ad9ff',
        }}
      >
        <span style={{
          width: 9, height: 9, borderRadius: '50%',
          background: '#00c8ff', boxShadow: '0 0 8px #00c8ff',
          animation: 'sy-pulse 2s ease-in-out infinite',
        }} />
        {!isPill && <span>SYLEA AGENT</span>}
      </div>

      {/* Boutons systeme — style Windows 11 caption buttons */}
      <div style={{ display: 'flex', alignItems: 'stretch', height: '100%' }}>
        {/* Slots extras (eventuels widgets) */}
        {extraButtons}
        {/* Pill toggle */}
        {onTogglePill && (
          <CaptionButton
            onClick={onTogglePill}
            title={isPill ? 'Mode plein' : 'Mode pill compact'}
            color={accent}
            isPill={isPill}
          >
            {isPill ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <rect x="2" y="2" width="12" height="12" stroke="currentColor" strokeWidth="1.4" rx="1.5" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="6" width="10" height="4" stroke="currentColor" strokeWidth="1.4" rx="2" />
              </svg>
            )}
          </CaptionButton>
        )}
        {!isPill && (
          <CaptionButton onClick={onMin} title="Reduire" color={accent} isPill={isPill}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <line x1="3" y1="13" x2="13" y2="13" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          </CaptionButton>
        )}
        {!isPill && (
          <CaptionButton onClick={onMax} title={maximized ? 'Restaurer' : 'Agrandir'} color={accent} isPill={isPill}>
            {maximized ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="5" width="8" height="8" stroke="currentColor" strokeWidth="1.4" />
                <rect x="5" y="3" width="8" height="8" stroke="currentColor" strokeWidth="1.4" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <rect x="3" y="3" width="10" height="10" stroke="currentColor" strokeWidth="1.4" />
              </svg>
            )}
          </CaptionButton>
        )}
        <CaptionButton
          onClick={onClose}
          title="Fermer (revient via tray)"
          color="#fca5a5"
          hoverBg="#e81123"
          hoverColor="#ffffff"
          isPill={isPill}
          isClose
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <line x1="4" y1="4" x2="12" y2="12" stroke="currentColor" strokeWidth="1.4" />
            <line x1="12" y1="4" x2="4" y2="12" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        </CaptionButton>
      </div>
    </div>
  )
}

interface BtnProps {
  onClick: () => void
  title: string
  color: string
  children: React.ReactNode
  isPill?: boolean
  isClose?: boolean
  hoverBg?: string
  hoverColor?: string
}

/**
 * Bouton style "caption" Windows 11 — large rectangulaire (46x44 plein-haut),
 * hover bg cyan discret, close hover bg rouge officiel Microsoft (#e81123).
 */
function CaptionButton({
  onClick, title, color, children,
  isPill = false, isClose = false,
  hoverBg = 'rgba(0,200,255,0.14)',
  hoverColor,
}: BtnProps) {
  // Win11 caption buttons: 46x32+ — on adopte 46x44 (full height titlebar)
  const w = isPill ? 36 : 46

  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: w,
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        borderRadius: 0,
        color,
        cursor: 'pointer',
        transition: 'background 0.12s, color 0.12s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = hoverBg
        if (hoverColor) e.currentTarget.style.color = hoverColor
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
        e.currentTarget.style.color = color
      }}
    >
      {children}
    </button>
  )
}
