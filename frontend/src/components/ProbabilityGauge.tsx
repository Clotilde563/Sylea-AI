// Jauge circulaire SVG — Luxe Futuriste
// Mode "durée estimée" ou mode "pourcentage" selon prop showDuration

import { dureeFromProb } from '../utils/duration'

interface ProbabilityGaugeProps {
  value:        number   // 0 à 100 (probabilité %)
  size?:        number
  label?:       string
  showPercent?: boolean
  /** Si true, affiche la durée estimée au lieu du % */
  showDuration?: boolean
  /** Prob séparée pour calcul durée (si différente de value) */
  durationOverride?: number
}

export function ProbabilityGauge({
  value,
  size         = 180,
  label,
  showPercent  = true,
  showDuration = false,
  durationOverride,
}: ProbabilityGaugeProps) {
  const clamped     = Math.max(0, Math.min(100, value))
  const radius      = size * 0.38
  const cx          = size / 2
  const cy          = size / 2
  const circumference = 2 * Math.PI * radius
  const dashOffset  = circumference * (1 - clamped / 100)

  // Couleur dynamique selon la valeur — palette chrome électrique
  const color =
    clamped >= 50 ? '#22c55e'   /* Vert succès */
    : clamped >= 25 ? '#4090f0' /* Bleu électrique */
    : clamped >= 10 ? '#1a6fd8' /* Bleu cobalt */
    : '#ef4444'                 /* Rouge danger */

  const trackColor = 'rgba(255,255,255,0.06)'

  // Durée estimée si mode activé (utilise durationOverride si fourni)
  const durProb = durationOverride !== undefined ? Math.max(0, Math.min(100, durationOverride)) : clamped
  const duree = showDuration ? dureeFromProb(durProb) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block' }}>
        {/* Track gris */}
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          stroke={trackColor}
          strokeWidth={size * 0.06}
        />
        {/* Arc de progression */}
        <circle
          cx={cx} cy={cy} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={size * 0.06}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{
            filter: `drop-shadow(0 0 6px ${color}80)`,
            transition: 'stroke-dashoffset 0.8s ease, stroke 0.4s',
          }}
        />
        {/* Glow ring interne */}
        <circle
          cx={cx} cy={cy} r={radius * 0.75}
          fill="none"
          stroke="rgba(26,111,216,0.08)"
          strokeWidth="1"
        />

        {/* ── Mode durée estimée ── */}
        {showDuration && duree && (
          <>
            <text
              x={cx}
              y={duree.ligne2 ? cy - size * 0.08 : cy - size * 0.04}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.13}
              fontWeight="700"
              fill={color}
              fontFamily="Inter, system-ui, sans-serif"
              letterSpacing="0.04em"
            >
              {duree.ligne1}
            </text>
            {duree.ligne2 && (
              <text
                x={cx}
                y={cy + size * 0.1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={size * 0.08}
                fill="rgba(232,232,240,0.5)"
                fontFamily="Inter, system-ui, sans-serif"
                letterSpacing="0.04em"
              >
                {duree.ligne2}
              </text>
            )}
          </>
        )}

        {/* ── Mode pourcentage (par défaut) ── */}
        {showPercent && !showDuration && (
          <>
            <text
              x={cx} y={cy - 6}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.17}
              fontWeight="700"
              fill={color}
              fontFamily="Inter, system-ui, sans-serif"
            >
              {clamped.toFixed(1)}
            </text>
            <text
              x={cx} y={cy + size * 0.1}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.09}
              fill="rgba(232,232,240,0.5)"
              fontFamily="Inter, system-ui, sans-serif"
            >
              %
            </text>
          </>
        )}

        {/* Graduations */}
        {[0, 25, 50, 75].map((tick) => {
          const angle = (tick / 100) * 360 - 90
          const rad   = (angle * Math.PI) / 180
          const r1    = radius + size * 0.035
          const r2    = radius + size * 0.055
          return (
            <line
              key={tick}
              x1={cx + r1 * Math.cos(rad)}
              y1={cy + r1 * Math.sin(rad)}
              x2={cx + r2 * Math.cos(rad)}
              y2={cy + r2 * Math.sin(rad)}
              stroke="rgba(232,232,240,0.2)"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          )
        })}
      </svg>
      {label && (
        <p
          style={{
            fontSize: '0.82rem',
            color: 'var(--text-muted)',
            textAlign: 'center',
            maxWidth: size,
            lineHeight: '1.4',
          }}
        >
          {label}
        </p>
      )}
    </div>
  )
}
