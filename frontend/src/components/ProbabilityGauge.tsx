// Jauge circulaire SVG — Luxe Futuriste
// L'arc represente le pourcentage de temps gagne
// Le texte au centre affiche le temps restant

interface ProbabilityGaugeProps {
  value:        number   // 0 a 100 (pourcentage de la jauge)
  size?:        number
  label?:       string
  tempsLigne1?: string   // ex. "2 ans"
  tempsLigne2?: string   // ex. "6 mois"
}

export function ProbabilityGauge({
  value,
  size         = 180,
  label,
  tempsLigne1,
  tempsLigne2,
}: ProbabilityGaugeProps) {
  const radius      = size * 0.38
  const cx          = size / 2
  const cy          = size / 2
  const circumference = 2 * Math.PI * radius

  const arcPercent = Math.max(0, Math.min(100, value))

  // Couleur basee sur le pourcentage
  const arcColor =
    arcPercent >= 50 ? '#22c55e'    /* Vert */
    : arcPercent >= 25 ? '#4090f0'  /* Bleu electrique */
    : arcPercent >= 10 ? '#1a6fd8'  /* Bleu cobalt */
    : '#ef4444'                     /* Rouge */

  const dashOffset = circumference * (1 - arcPercent / 100)
  const trackColor = 'rgba(255,255,255,0.06)'

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
          stroke={arcColor}
          strokeWidth={size * 0.06}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{
            filter: `drop-shadow(0 0 6px ${arcColor}80)`,
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

        {/* Texte temps restant */}
        {tempsLigne1 && (
          <>
            <text
              x={cx}
              y={tempsLigne2 ? cy - size * 0.08 : cy - size * 0.04}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.13}
              fontWeight="700"
              fill={arcColor}
              fontFamily="Inter, system-ui, sans-serif"
              letterSpacing="0.04em"
            >
              {tempsLigne1}
            </text>
            {tempsLigne2 && (
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
                {tempsLigne2}
              </text>
            )}
          </>
        )}

        {/* Fallback: afficher le pourcentage si pas de texte temps */}
        {!tempsLigne1 && (
          <>
            <text
              x={cx} y={cy - 6}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={size * 0.17}
              fontWeight="700"
              fill={arcColor}
              fontFamily="Inter, system-ui, sans-serif"
            >
              {arcPercent.toFixed(1)}
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
