interface Props {
  level: number  // 0-100
  size?: number
}

export default function SecurityGauge({ level, size = 140 }: Props) {
  const cx = size / 2
  const cy = size / 2 + 10
  const r = size / 2 - 16
  // Semi-circle arc (180 degrees)
  const circumference = Math.PI * r
  const filled = (level / 100) * circumference

  const color = level === 0 ? '#ef4444'
    : level < 40 ? '#f59e0b'
    : level < 70 ? '#3b82f6'
    : '#22c55e'

  const label = level === 0 ? 'Aucun'
    : level < 40 ? 'Faible'
    : level < 70 ? 'Moyen'
    : level < 90 ? 'Bon'
    : 'Excellent'

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width={size} height={size / 2 + 30} viewBox={`0 0 ${size} ${size / 2 + 30}`}>
        {/* Background arc */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={10}
          strokeLinecap="round"
        />
        {/* Filled arc */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          style={{
            transition: 'stroke-dasharray 0.5s ease, stroke 0.3s',
            filter: `drop-shadow(0 0 6px ${color}80)`,
          }}
        />
        {/* Percentage text */}
        <text x={cx} y={cy - 10} textAnchor="middle" fill={color}
          fontSize={size / 5} fontWeight={700}
          fontFamily="Inter, system-ui, sans-serif">
          {level}%
        </text>
        {/* Label */}
        <text x={cx} y={cy + 12} textAnchor="middle"
          fill="rgba(232,232,240,0.5)" fontSize={11} fontWeight={500}
          fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.06em">
          {label}
        </text>
      </svg>
    </div>
  )
}
