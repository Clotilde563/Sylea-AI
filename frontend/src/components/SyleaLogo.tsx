// Logo Syléa.AI — Double-S tube creux, gradient violet→cyan
// Fidèle au nouveau logo officiel

import { useId } from 'react'

interface SyleaLogoProps {
  size?: number
  animated?: boolean
}

// Chemin S dans un viewBox 120×120, centre (60, 54)
// Hauteur 66px, bulges ±28px — proportions identiques au logo
const CX = 60, CY = 54
const S_PATH = `M ${CX} ${CY-33} C ${CX+28} ${CY-33}, ${CX+28} ${CY-9}, ${CX} ${CY} C ${CX-28} ${CY+9}, ${CX-28} ${CY+33}, ${CX} ${CY+33}`
// → M 60 21 C 88 21, 88 45, 60 54 C 32 63, 32 87, 60 87

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
        {/* Gradient violet → cyan (bas → haut) */}
        <linearGradient id={gradId} x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%"   stopColor="#5520b8"/>
          <stop offset="30%"  stopColor="#1848d8"/>
          <stop offset="65%"  stopColor="#0090e0"/>
          <stop offset="100%" stopColor="#00c8ff"/>
        </linearGradient>

        {/* Halo flou */}
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

      {/* Couche 1 — bordure extérieure sombre */}
      <path
        d={S_PATH}
        stroke="rgba(2,4,16,0.97)" strokeWidth="20"
        fill="none" strokeLinecap="round"
      />

      {/* Couche 2 — corps gradient (les deux rails) */}
      <path
        d={S_PATH}
        stroke={`url(#${gradId})`} strokeWidth="16"
        fill="none" strokeLinecap="round"
        style={{
          filter: animated
            ? 'drop-shadow(0 0 3px rgba(0,160,240,0.6))'
            : 'drop-shadow(0 0 2px rgba(0,160,240,0.4))',
        }}
      >
        {animated && (
          <animate
            attributeName="opacity"
            values="0.85;1;0.85"
            dur="2.5s"
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Couche 3 — canal central creux (butt = caps ronds conservés) */}
      <path
        d={S_PATH}
        stroke="#050810" strokeWidth="6"
        fill="none" strokeLinecap="butt"
      />

      {/* Couche 4 — reflet spéculaire */}
      <path
        d={S_PATH}
        stroke="rgba(160,225,255,0.55)" strokeWidth="1.2"
        fill="none" strokeLinecap="round"
      />
    </svg>
  )
}
