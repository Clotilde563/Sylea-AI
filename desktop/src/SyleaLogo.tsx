// Logo Syléa — version desktop en retro rose/violet.
// Meme geometrie que le logo officiel web (double-S tube creux, open ended)
// mais palette retro (plum → violet → fuchsia → rose) pour se differencier
// visuellement de la version web (violet → cyan). Les couches et animations
// restent identiques pour preserver la signature de marque.
//
// Exporte aussi AgentSyleaLogo : variante coloree par agent (or / rouge /
// bleu-or anime / violet) — alignee sur les logos des agents dans la page
// web AgentsPage.tsx (source de verite, conservee a l'identique).

import { useId } from 'react'

interface SyleaLogoProps {
  size?: number
  animated?: boolean
}

// Chemin S dans un viewBox 120×120, centre (60, 54)
// Proportions identiques au logo web officiel.
const CX = 60, CY = 54
const S_PATH = `M ${CX} ${CY-33} C ${CX+28} ${CY-33}, ${CX+28} ${CY-9}, ${CX} ${CY} C ${CX-28} ${CY+9}, ${CX-28} ${CY+33}, ${CX} ${CY+33}`

export function SyleaLogo({ size = 40, animated = true }: SyleaLogoProps) {
  const uid = useId().replace(/\W/g, '')
  const gradId = `sld-g-${uid}`
  const haloId = `sld-halo-${uid}`

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      style={{ display: 'block' }}
    >
      <defs>
        {/* Gradient retro rose/violet (bas → haut) — signature desktop
            plum profond → violet electrique → fuchsia → rose chaud.
            Se distingue du gradient web (violet → cyan). */}
        <linearGradient id={gradId} x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%"   stopColor="#3d1461" />
          <stop offset="30%"  stopColor="#7c3aed" />
          <stop offset="65%"  stopColor="#d946ef" />
          <stop offset="100%" stopColor="#ec4899" />
        </linearGradient>

        {/* Halo flou atmospherique */}
        <filter id={haloId}>
          <feGaussianBlur stdDeviation="5" />
        </filter>
      </defs>

      {/* Halo atmospherique */}
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

      {/* Couche 1 — bordure exterieure sombre */}
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
            ? 'drop-shadow(0 0 3px rgba(236,72,153,0.55))'
            : 'drop-shadow(0 0 2px rgba(236,72,153,0.40))',
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

      {/* Couche 3 — canal central creux */}
      <path
        d={S_PATH}
        stroke="#050810" strokeWidth="6"
        fill="none" strokeLinecap="butt"
      />

      {/* Couche 4 — reflet speculaire (rose-blanc doux) */}
      <path
        d={S_PATH}
        stroke="rgba(255,220,240,0.60)" strokeWidth="1.2"
        fill="none" strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * Lockup complet : logo + wordmark "SYLEA AGENT"
 * Conforme au logo officiel fourni par le design.
 */
interface SyleaWordmarkProps {
  logoSize?: number
  fontSize?: number | string
  gap?: number
  agent?: boolean // affiche "SYLEA AGENT" (true) ou juste "SYLEA" (false)
  animated?: boolean
}

export function SyleaWordmark({
  logoSize = 34,
  fontSize = '0.95rem',
  gap = 10,
  agent = true,
  animated = false,
}: SyleaWordmarkProps) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap,
        userSelect: 'none',
      }}
    >
      <SyleaLogo size={logoSize} animated={animated} />
      <span
        style={{
          fontWeight: 800,
          fontSize,
          letterSpacing: '0.14em',
          color: '#fbe4f0',
          textShadow: '0 0 10px rgba(236,72,153,0.25)',
          fontFamily: '"Inter", system-ui, sans-serif',
        }}
      >
        SYLEA
        {agent && (
          <span
            style={{
              marginLeft: '0.35em',
              color: '#f9a8d4',
              textShadow: '0 0 10px rgba(217,70,239,0.40)',
            }}
          >
            AGENT
          </span>
        )}
      </span>
    </div>
  )
}

// ── AgentSyleaLogo ──────────────────────────────────────────────────────────
// Variante coloree du logo officiel, une par agent.
// Reproduit fidelement les logos des cartes agents dans la page web
// frontend/src/pages/AgentsPage.tsx (source de verite) — chaque agent a sa
// palette propre. Utilise la meme geometrie / les memes couches que
// SyleaLogo pour preserver la coherence visuelle.

export type AgentVariant = 'gold' | 'red' | 'agent3' | 'violet'

// Gradients statiques (gold / red / violet) — meme forme que le gradient
// officiel (bas → haut), couleurs alignees sur AgentsPage.tsx.
const VARIANT_GRADIENTS: Record<Exclude<AgentVariant, 'agent3'>, Array<[string, string]>> = {
  // Agent 1 — or / miel chaud
  gold: [
    ['0%',   '#d4a017'],
    ['40%',  '#f59e0b'],
    ['100%', '#fbbf24'],
  ],
  // Agent 2 — rouge
  red: [
    ['0%',   '#b91c1c'],
    ['40%',  '#ef4444'],
    ['100%', '#f87171'],
  ],
  // Super Agent (locked) — violet
  violet: [
    ['0%',   '#5b21b6'],
    ['40%',  '#8b5cf6'],
    ['100%', '#c4b5fd'],
  ],
}

// Couleur du reflet speculaire (couche 4), adaptee a chaque palette
const SPECULAR_COLORS: Record<AgentVariant, string> = {
  gold:   'rgba(255,230,150,0.55)',
  red:    'rgba(255,170,170,0.55)',
  agent3: 'rgba(220,230,255,0.55)',
  violet: 'rgba(210,195,255,0.55)',
}

// Couleur du drop-shadow du corps (couche 2), adaptee a chaque palette
const GLOW_COLORS: Record<AgentVariant, string> = {
  gold:   'rgba(245,158,11,0.55)',
  red:    'rgba(239,68,68,0.55)',
  agent3: 'rgba(56,189,248,0.55)',
  violet: 'rgba(139,92,246,0.55)',
}

interface AgentSyleaLogoProps {
  size?: number
  variant: AgentVariant
  animated?: boolean
}

export function AgentSyleaLogo({ size = 22, variant, animated = true }: AgentSyleaLogoProps) {
  const uid    = useId().replace(/\W/g, '')
  const gradId = `asl-${variant}-${uid}`
  const haloId = `asl-halo-${uid}`

  // Gradient — anime pour agent3 (bleu <-> or qui oscille), statique sinon
  const defsGradient =
    variant === 'agent3' ? (
      <linearGradient id={gradId} x1="0%" y1="100%" x2="100%" y2="0%">
        <stop offset="0%">
          <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
        </stop>
        <stop offset="35%">
          <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
        </stop>
        <stop offset="65%">
          <animate attributeName="stop-color" values="#d4a017;#2563eb;#d4a017" dur="3s" repeatCount="indefinite" />
        </stop>
        <stop offset="100%">
          <animate attributeName="stop-color" values="#fbbf24;#1e3a5f;#fbbf24" dur="3s" repeatCount="indefinite" />
        </stop>
      </linearGradient>
    ) : (
      <linearGradient id={gradId} x1="50%" y1="100%" x2="50%" y2="0%">
        {VARIANT_GRADIENTS[variant].map(([offset, color]) => (
          <stop key={offset} offset={offset} stopColor={color} />
        ))}
      </linearGradient>
    )

  const glow = GLOW_COLORS[variant]
  const specular = SPECULAR_COLORS[variant]

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      style={{ display: 'block' }}
    >
      <defs>
        {defsGradient}
        <filter id={haloId}>
          <feGaussianBlur stdDeviation="5" />
        </filter>
      </defs>

      {/* Halo atmospherique */}
      <path
        d={S_PATH}
        stroke={`url(#${gradId})`} strokeWidth="30"
        fill="none" strokeLinecap="round"
        style={{
          filter: `url(#${haloId})`,
          opacity: animated ? 0.22 : 0.15,
        }}
      >
        {animated && variant !== 'agent3' && (
          <animate
            attributeName="opacity"
            values="0.15;0.28;0.15"
            dur="3s"
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Couche 1 — bordure exterieure sombre */}
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
            ? `drop-shadow(0 0 3px ${glow})`
            : `drop-shadow(0 0 2px ${glow})`,
        }}
      >
        {animated && variant !== 'agent3' && (
          <animate
            attributeName="opacity"
            values="0.85;1;0.85"
            dur="2.5s"
            repeatCount="indefinite"
          />
        )}
      </path>

      {/* Couche 3 — canal central creux */}
      <path
        d={S_PATH}
        stroke="#050810" strokeWidth="6"
        fill="none" strokeLinecap="butt"
      />

      {/* Couche 4 — reflet speculaire */}
      <path
        d={S_PATH}
        stroke={specular} strokeWidth="1.2"
        fill="none" strokeLinecap="round"
      />
    </svg>
  )
}

export default SyleaLogo
