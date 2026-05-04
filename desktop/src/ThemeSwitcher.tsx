/**
 * Theme switcher button (Sprint 2 — feature 2.8)
 *
 * Petit bouton pop-up dans la titlebar / le header. Cycle Dark → Cyber → Aurora.
 * Affiche un mini-preview de la palette en hover (3 dots de couleur).
 */
import { useState, useRef, useEffect } from 'react'
import { useTheme, type ThemeId, THEME_LABELS, PALETTES_MAP } from './useTheme'
import { useSound } from './useSound'

interface ThemeSwitcherProps {
  size?: number
}

export function ThemeSwitcher({ size = 22 }: ThemeSwitcherProps) {
  const { theme, setTheme, palette } = useTheme()
  const { play } = useSound()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const handlePick = (t: ThemeId) => {
    setTheme(t)
    play('success')
    setOpen(false)
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        onClick={() => { play('click'); setOpen(o => !o) }}
        title={`Theme : ${THEME_LABELS[theme].name}`}
        style={{
          width: size, height: size,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'transparent', border: 'none', borderRadius: 4,
          color: palette.cyanSoft, cursor: 'pointer',
          transition: 'background 0.15s',
          fontSize: 12,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = palette.surfaceHi }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
      >
        <span style={{ fontSize: size * 0.55, lineHeight: 1 }}>
          {THEME_LABELS[theme].emoji}
        </span>
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: size + 6, right: 0,
            minWidth: 200, padding: 6,
            background: 'rgba(5, 8, 16, 0.97)',
            border: `1px solid ${palette.borderHi}`,
            borderRadius: 8,
            boxShadow: '0 12px 32px rgba(0,0,0,0.6)',
            zIndex: 5000,
            backdropFilter: 'blur(10px)',
            display: 'flex', flexDirection: 'column', gap: 2,
            animation: 'sy-theme-pop 0.18s ease-out',
          }}
        >
          <div style={{
            padding: '6px 8px 4px',
            fontFamily: '"JetBrains Mono","Fira Code",monospace',
            fontSize: 9, letterSpacing: '0.2em',
            color: palette.textDim, textTransform: 'uppercase',
          }}>
            <span style={{ color: palette.cyan }}>▸</span> Theme
          </div>
          {(Object.keys(THEME_LABELS) as ThemeId[]).map(t => {
            const isActive = t === theme
            const tp = PALETTES_MAP[t]
            return (
              <button
                key={t}
                onClick={() => handlePick(t)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '7px 10px', borderRadius: 5,
                  background: isActive ? palette.surfaceHi : 'transparent',
                  border: isActive ? `1px solid ${palette.borderHi}` : '1px solid transparent',
                  color: palette.text, cursor: 'pointer',
                  textAlign: 'left',
                  fontFamily: 'inherit', fontSize: 12,
                  transition: 'background 0.12s',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = palette.surface
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = 'transparent'
                }}
              >
                {/* Mini preview palette : 3 dots */}
                <div style={{ display: 'flex', gap: 3 }}>
                  <span style={{
                    width: 9, height: 9, borderRadius: '50%',
                    background: tp.cyan,
                    boxShadow: `0 0 5px ${tp.cyan}`,
                  }} />
                  <span style={{
                    width: 9, height: 9, borderRadius: '50%',
                    background: tp.indigo,
                  }} />
                  <span style={{
                    width: 9, height: 9, borderRadius: '50%',
                    background: tp.accent,
                  }} />
                </div>
                <div style={{ flex: 1, lineHeight: 1.15 }}>
                  <div style={{ fontWeight: 600, fontSize: 12 }}>
                    {THEME_LABELS[t].name}
                  </div>
                  <div style={{
                    fontSize: 10, color: palette.textMute,
                    fontFamily: '"JetBrains Mono",monospace',
                  }}>
                    {THEME_LABELS[t].subtitle}
                  </div>
                </div>
                {isActive && (
                  <span style={{
                    color: palette.cyan, fontSize: 11,
                    fontFamily: '"JetBrains Mono",monospace',
                  }}>
                    ▸
                  </span>
                )}
              </button>
            )
          })}
          <style>{`
            @keyframes sy-theme-pop {
              from { opacity: 0; transform: translateY(-4px) scale(0.97); }
              to   { opacity: 1; transform: translateY(0)    scale(1); }
            }
          `}</style>
        </div>
      )}
    </div>
  )
}

export default ThemeSwitcher
