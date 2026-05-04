/**
 * Theme switcher (Sprint 2 — feature 2.8)
 *
 * 3 presets de theme :
 *   - dark   : palette Sylea originale (cyan + indigo + violet, bg #050810)
 *   - cyber  : palette neon dur (cyan electrique + magenta + bg quasi-noir)
 *   - aurora : palette boreale (vert tilleul + violet + cyan doux)
 *
 * Persiste dans localStorage('sylea_theme'). Expose un hook useTheme() qui
 * retourne {theme, setTheme, palette}. Les couleurs s'appliquent aussi via
 * CSS variables (data-theme attribut sur <html>) pour les styles globaux.
 */
import { useEffect, useState, useCallback } from 'react'

export type ThemeId = 'dark' | 'cyber' | 'aurora'

export interface ThemePalette {
  cyan: string
  cyanSoft: string
  blue: string
  indigo: string
  violet: string
  accent: string       // couleur d'accent secondaire
  text: string
  textMute: string
  textDim: string
  border: string
  borderHi: string
  surface: string
  surfaceHi: string
  bg: string
  bgElev: string
  success: string
  warn: string
  error: string
  particleRgb: string  // ex "0, 200, 255" (sans alpha)
  gradient: string     // gradient signature pour boutons/CTA
}

const PALETTES: Record<ThemeId, ThemePalette> = {
  dark: {
    cyan:        '#00c8ff',
    cyanSoft:    '#7ad9ff',
    blue:        '#0090e0',
    indigo:      '#1848d8',
    violet:      '#5520b8',
    accent:      '#7c3aed',
    text:        '#e6f0ff',
    textMute:    'rgba(230, 240, 255, 0.60)',
    textDim:     'rgba(230, 240, 255, 0.35)',
    border:      'rgba(0, 200, 255, 0.12)',
    borderHi:    'rgba(0, 200, 255, 0.25)',
    surface:     'rgba(0, 200, 255, 0.03)',
    surfaceHi:   'rgba(0, 200, 255, 0.06)',
    bg:          '#050810',
    bgElev:      '#070c1a',
    success:     '#10b981',
    warn:        '#f59e0b',
    error:       '#ef4444',
    particleRgb: '0, 200, 255',
    gradient:    'linear-gradient(135deg, #5520b8 0%, #1848d8 40%, #0090e0 75%, #00c8ff 100%)',
  },
  cyber: {
    cyan:        '#00ffe1',
    cyanSoft:    '#7af7ff',
    blue:        '#00bfff',
    indigo:      '#3a00ff',
    violet:      '#ff2cf3',
    accent:      '#ff2cf3',
    text:        '#eafffd',
    textMute:    'rgba(234, 255, 253, 0.62)',
    textDim:     'rgba(234, 255, 253, 0.36)',
    border:      'rgba(0, 255, 225, 0.15)',
    borderHi:    'rgba(0, 255, 225, 0.32)',
    surface:     'rgba(0, 255, 225, 0.04)',
    surfaceHi:   'rgba(255, 44, 243, 0.07)',
    bg:          '#02030a',
    bgElev:      '#06091a',
    success:     '#00ff8a',
    warn:        '#ffae00',
    error:       '#ff003c',
    particleRgb: '0, 255, 225',
    gradient:    'linear-gradient(135deg, #ff2cf3 0%, #3a00ff 50%, #00ffe1 100%)',
  },
  aurora: {
    cyan:        '#48dfd2',
    cyanSoft:    '#a7f0e7',
    blue:        '#5b9af2',
    indigo:      '#7a6df0',
    violet:      '#b06af0',
    accent:      '#b8f5a3',
    text:        '#eef7f5',
    textMute:    'rgba(238, 247, 245, 0.62)',
    textDim:     'rgba(238, 247, 245, 0.36)',
    border:      'rgba(72, 223, 210, 0.15)',
    borderHi:    'rgba(184, 245, 163, 0.30)',
    surface:     'rgba(122, 109, 240, 0.04)',
    surfaceHi:   'rgba(184, 245, 163, 0.06)',
    bg:          '#080d18',
    bgElev:      '#0d1326',
    success:     '#5bd97c',
    warn:        '#ffc857',
    error:       '#ff7e7e',
    particleRgb: '184, 245, 163',
    gradient:    'linear-gradient(135deg, #b06af0 0%, #7a6df0 35%, #48dfd2 70%, #b8f5a3 100%)',
  },
}

const STORAGE_KEY = 'sylea_theme'

export const THEME_LABELS: Record<ThemeId, { name: string; subtitle: string; emoji: string }> = {
  dark:   { name: 'Dark',   subtitle: 'Cyan tech (defaut)',  emoji: '◐' },
  cyber:  { name: 'Cyber',  subtitle: 'Neon electrique',     emoji: '⚡' },
  aurora: { name: 'Aurora', subtitle: 'Boreale verte',       emoji: '✶' },
}

/** Applique le theme aux variables CSS globales sur <html data-theme=...>. */
function applyThemeToRoot(theme: ThemeId) {
  if (typeof document === 'undefined') return
  const p = PALETTES[theme]
  document.documentElement.setAttribute('data-sy-theme', theme)
  const root = document.documentElement.style
  root.setProperty('--sy-cyan', p.cyan)
  root.setProperty('--sy-cyan-soft', p.cyanSoft)
  root.setProperty('--sy-blue', p.blue)
  root.setProperty('--sy-indigo', p.indigo)
  root.setProperty('--sy-violet', p.violet)
  root.setProperty('--sy-accent', p.accent)
  root.setProperty('--sy-text', p.text)
  root.setProperty('--sy-text-mute', p.textMute)
  root.setProperty('--sy-text-dim', p.textDim)
  root.setProperty('--sy-border', p.border)
  root.setProperty('--sy-border-hi', p.borderHi)
  root.setProperty('--sy-surface', p.surface)
  root.setProperty('--sy-surface-hi', p.surfaceHi)
  root.setProperty('--sy-bg', p.bg)
  root.setProperty('--sy-bg-elev', p.bgElev)
  root.setProperty('--sy-success', p.success)
  root.setProperty('--sy-warn', p.warn)
  root.setProperty('--sy-error', p.error)
  root.setProperty('--sy-particle-rgb', p.particleRgb)
  // Met le bg sur le body aussi pour que les zones hors React soient theme-aware
  document.body.style.background = p.bg
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeId>(() => {
    try {
      const v = localStorage.getItem(STORAGE_KEY) as ThemeId | null
      if (v && (v === 'dark' || v === 'cyber' || v === 'aurora')) return v
    } catch {}
    return 'dark'
  })

  useEffect(() => { applyThemeToRoot(theme) }, [theme])

  const setTheme = useCallback((t: ThemeId) => {
    setThemeState(t)
    try { localStorage.setItem(STORAGE_KEY, t) } catch {}
  }, [])

  const cycle = useCallback(() => {
    setThemeState(prev => {
      const order: ThemeId[] = ['dark', 'cyber', 'aurora']
      const idx = order.indexOf(prev)
      const next = order[(idx + 1) % order.length]
      try { localStorage.setItem(STORAGE_KEY, next) } catch {}
      return next
    })
  }, [])

  return { theme, setTheme, cycle, palette: PALETTES[theme] }
}

export const PALETTES_MAP = PALETTES
