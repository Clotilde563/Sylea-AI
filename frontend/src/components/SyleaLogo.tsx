// Logo Syléa.AI — S plein, gradient violet→cyan
// Pas de tube creux (pas de fond opaque)

import { useId } from 'react'

interface SyleaLogoProps {
  size?: number
  animated?: boolean
}

const CX = 60, CY = 54
const S_PATH = `M ${CX} ${CY-33} C ${CX+28} ${CY-33}, ${CX+28} ${CY-9}, ${CX} ${CY} C ${CX-28} ${CY+9}, ${CX-28} ${CY+33}, ${CX} ${CY+33}`

export function SyleaLogo({ size = 40, animated = true }: SyleaLogoProps) {
  const uid    = useId().replace(/\W/g, '')
  const gradId = `sl-g-${uid}`
  const haloId = `sl-halo-${uid}`

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      style={{ display: 'block' }}
    >
      <defs>
        <linearGradient id={gradId} x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%"   stopColor="#5520b8"/>
          <stop offset="30%"  stopColor="#1848d8"/>
          <stop offset="65%"  stopColor="#0090e0"/>
          <stop offset="100%" stopColor="#00c8ff"/>
        </linearGradient>
        <filter id={haloId}>
          <feGaussianBlur stdDeviation="5"/>
        </filter>
      </defs>

      {/* Halo atmosphérique */}
      <path
        d={S_PATH}
        stroke={`url(#${gradId})`} strokeWidth="30"
        fill="none" strokeLinecap="round"
        style={{
          filter: `url(#${haloId})`,
          opacity: animated ? 0.20 : 0.15,
        }}
      >
        {animated && (
          <animate
            attributeName="opacity"
            values="0.15;0.28;0.15"
            dur="3s"
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Corps gradient — S plein */}
      <path
        d={S_PATH}
        stroke={`url(#${gradId})`} strokeWidth="16"
        fill="none" strokeLinecap="round"
        style={{
          filter: animated
            ? 'drop-shadow(0 0 4px rgba(0,160,240,0.6))'
            : 'drop-shadow(0 0 2px rgba(0,160,240,0.4))',
        }}
      >
        {animated && (
          <animate
            attributeName="opacity"
            values="0.9;1;0.9"
            dur="2.5s"
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Ligne intérieure claire pour profondeur */}
      <path
        d={S_PATH}
        stroke="rgba(100,200,255,0.2)" strokeWidth="6"
        fill="none" strokeLinecap="round"
      />

      {/* Reflet spéculaire */}
      <path
        d={S_PATH}
        stroke="rgba(200,240,255,0.45)" strokeWidth="1.5"
        fill="none" strokeLinecap="round"
      />
    </svg>
  )
}
