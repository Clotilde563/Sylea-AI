// Logo Sylea S reutilisable pour les pages agents
// Remplace les 4+ copies de S_PATH + AgentSyleaLogo dans les pages

import { useId } from 'react'

const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

interface AgentSyleaLogoProps {
  size?: number
  color?: string
  /** Multi-color gradient stops (for gold logo etc.) */
  gradientColors?: string[]
  animated?: boolean
  /** Show tube/mask effect (used in AgentsPage) */
  tubeEffect?: boolean
}

export function AgentSyleaLogo({
  size = 24,
  color = '#d4a017',
  gradientColors,
  animated = false,
  tubeEffect = false,
}: AgentSyleaLogoProps) {
  const uid = useId().replace(/\W/g, '')
  const colors = gradientColors || [color, color]
  const c0 = colors[0]
  const c1 = colors[Math.min(1, colors.length - 1)]
  const c2 = colors[Math.min(2, colors.length - 1)]

  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id={`${uid}-g`} x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor={c0} />
          {colors.length > 2 && <stop offset="40%" stopColor={c1} />}
          <stop offset="100%" stopColor={c2} stopOpacity={gradientColors ? 1 : 0.7} />
        </linearGradient>
        <filter id={`${uid}-blur`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="20" />
        </filter>
        {tubeEffect && (
          <mask id={`${uid}-tube-mask`}>
            <path d={S_PATH} stroke="white" strokeWidth="46" fill="none" strokeLinecap="round" />
            <path d={S_PATH} stroke="black" strokeWidth="18" fill="none" strokeLinecap="butt" />
          </mask>
        )}
      </defs>
      {/* Halo */}
      <path d={S_PATH} stroke={`url(#${uid}-g)`} strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: `url(#${uid}-blur)`, opacity: 0.18 }}>
        {animated && <animate attributeName="opacity" values="0.12;0.25;0.12" dur="2.5s" repeatCount="indefinite" />}
      </path>
      {/* Corps */}
      {tubeEffect ? (
        <path d={S_PATH} stroke={`url(#${uid}-g)`} strokeWidth="46" fill="none" strokeLinecap="round"
          mask={`url(#${uid}-tube-mask)`} />
      ) : (
        <path d={S_PATH} stroke={`url(#${uid}-g)`} strokeWidth="28" fill="none" strokeLinecap="round" />
      )}
      {/* Reflet */}
      <path d={S_PATH} stroke="rgba(255,230,200,0.4)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export { S_PATH, CX, CY }
