/**
 * Real-time stats HUD (Sprint 2 — feature 2.7)
 *
 * Mini dashboard in-app : 4 metriques en mode HUD tech.
 *   - REQ/MIN  : nombre de requetes WS recues sur la derniere minute
 *   - LATENCY  : latence p50 backend (ms) — observed via fetch round-trip
 *   - TOKENS   : tokens estimes consommes (compteur cumul, formatte)
 *   - ACTIONS  : actions terminees ce session (compteur cumul)
 *
 * Chaque cellule contient un mini sparkline SVG (60 points, scroll auto).
 * Le composant est purement presentationnel : le parent injecte les samples.
 */
import { useMemo } from 'react'
import { CountUp } from './CountUp'

export interface StatsHUDData {
  reqPerMin: number
  reqHistory: number[]   // 60 derniers points (1 par seconde, ou tout autre granularite)
  latencyMs: number
  latencyHistory: number[]
  tokens: number
  tokensHistory: number[]
  actions: number
  actionsHistory: number[]
}

interface StatsHUDProps {
  data: StatsHUDData
  /** Largeur totale du HUD (default 100% du parent) */
  width?: number | string
  /** Theme palette */
  cyan?: string
  textMute?: string
  textDim?: string
  border?: string
  surface?: string
  text?: string
}

export function StatsHUD({
  data,
  width = '100%',
  cyan = '#00c8ff',
  textMute = 'rgba(230, 240, 255, 0.60)',
  textDim = 'rgba(230, 240, 255, 0.35)',
  border = 'rgba(0, 200, 255, 0.12)',
  surface = 'rgba(0, 200, 255, 0.03)',
  text = '#e6f0ff',
}: StatsHUDProps) {
  const cells = [
    {
      label: 'REQ/MIN',
      value: data.reqPerMin,
      format: 'num',
      color: cyan,
      history: data.reqHistory,
    },
    {
      label: 'LATENCY p50',
      value: data.latencyMs,
      format: 'ms',
      color: '#7ad9ff',
      history: data.latencyHistory,
    },
    {
      label: 'TOKENS',
      value: data.tokens,
      format: 'k',
      color: '#a5b4fc',
      history: data.tokensHistory,
    },
    {
      label: 'ACTIONS',
      value: data.actions,
      format: 'num',
      color: '#10b981',
      history: data.actionsHistory,
    },
  ] as const

  return (
    <div
      style={{
        width,
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 6,
        padding: 8,
        background: surface,
        border: `1px solid ${border}`,
        borderRadius: 8,
      }}
    >
      {cells.map(c => (
        <StatCell
          key={c.label}
          label={c.label}
          value={c.value}
          format={c.format}
          color={c.color}
          history={c.history}
          textMute={textMute}
          textDim={textDim}
          border={border}
          text={text}
        />
      ))}
    </div>
  )
}

interface StatCellProps {
  label: string
  value: number
  format: 'num' | 'ms' | 'k'
  color: string
  history: number[]
  textMute: string
  textDim: string
  border: string
  text: string
}

function StatCell({ label, value, format, color, history, textMute, textDim, border, text }: StatCellProps) {
  const formatted = useMemo(() => {
    if (format === 'k') {
      if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + 'M'
      if (value >= 1_000)     return (value / 1_000).toFixed(1) + 'k'
      return String(value)
    }
    if (format === 'ms') return value + 'ms'
    return String(value)
  }, [value, format])

  return (
    <div style={{
      position: 'relative',
      padding: '6px 8px 4px',
      borderRadius: 5,
      border: `1px solid ${border}`,
      background: 'rgba(5, 8, 16, 0.3)',
      display: 'flex', flexDirection: 'column', gap: 2,
      overflow: 'hidden',
    }}>
      {/* Label */}
      <div style={{
        fontFamily: '"JetBrains Mono","Fira Code",monospace',
        fontSize: 8, letterSpacing: '0.16em',
        color: textDim, textTransform: 'uppercase',
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        <span style={{
          width: 4, height: 4, borderRadius: '50%',
          background: color, boxShadow: `0 0 4px ${color}`,
        }} />
        {label}
      </div>

      {/* Value */}
      <div style={{
        fontFamily: '"JetBrains Mono","Fira Code",monospace',
        fontSize: 16, fontWeight: 700,
        color: text,
        lineHeight: 1.1,
      }}>
        {format === 'k' ? formatted : (
          <CountUp
            to={value}
            durationMs={500}
            suffix={format === 'ms' ? 'ms' : ''}
          />
        )}
      </div>

      {/* Sparkline */}
      <div style={{ marginTop: 1, height: 18, position: 'relative' }}>
        <Sparkline values={history} color={color} />
      </div>
    </div>
  )
}

interface SparklineProps {
  values: number[]
  color: string
  width?: number
  height?: number
}

function Sparkline({ values, color, width = 100, height = 18 }: SparklineProps) {
  // Pas de data → ligne plate basse
  if (values.length < 2) {
    return (
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line x1="0" y1={height - 2} x2={width} y2={height - 2}
              stroke={color} strokeOpacity="0.18" strokeWidth="1" />
      </svg>
    )
  }

  // Pad to constant length pour eviter scaling weirdness
  const N = 60
  const padded = values.length >= N ? values.slice(-N) : [...new Array(N - values.length).fill(values[0]), ...values]
  const min = Math.min(...padded)
  const max = Math.max(...padded)
  const range = max - min || 1

  const dx = width / (N - 1)
  const pad = 1
  const usable = height - pad * 2

  const points = padded.map((v, i) => {
    const x = i * dx
    const y = pad + usable - ((v - min) / range) * usable
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  // Aire sous la courbe pour effet glow
  const areaPoints = `0,${height} ${points} ${width},${height}`

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={`spark-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.30" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={areaPoints}
        fill={`url(#spark-${color.replace('#', '')})`}
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1"
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{ filter: `drop-shadow(0 0 2px ${color})` }}
      />
    </svg>
  )
}

/**
 * Hook helper pour maintenir les historiques des stats. A utiliser dans App.tsx.
 * Pousse une nouvelle valeur dans chaque history et plafonne a `cap` points.
 */
export function pushHist(arr: number[], v: number, cap = 60): number[] {
  const next = arr.length >= cap ? arr.slice(-cap + 1) : arr.slice()
  next.push(v)
  return next
}

export default StatsHUD
