// Badge éclair affichant le nombre d'actions restantes aujourd'hui.
//
// Design : éclair construit EXACTEMENT comme le logo Syléa officiel —
// 5 couches superposées sur un path zigzag (au lieu du S), avec gradient
// blanc → bleu fixe (la couleur ne change JAMAIS, indépendamment du
// nombre d'actions restantes).
//
// Le nombre d'actions restantes est affiché à droite de l'éclair :
//   ⚡ 7   (free)
//   ⚡ 23  (advanced)
//   ⚡ ∞   (team / illimité)
//
// Affiché dans :
//   - Dashboard (à côté du logo Syléa, en haut à droite)
//   - Header du chat Agent Syléa 1
//   - Header du chat Agent Syléa 2

import { useEffect, useState, useId } from 'react'
import { API_BASE } from '../api/client'

// ── Types ───────────────────────────────────────────────────────────────────

interface ActionsStatus {
  used: number
  limit: number             // -1 = illimité
  remaining: number
  plan: string              // 'free' | 'advanced' | 'team' | ...
                            // (alias backward-compat 'pro' = 'advanced')
  is_unlimited: boolean
  reset_at: string          // ISO timestamp
}

// ── Hook : fetch + auto-refresh ────────────────────────────────────────────

const ACTIONS_TTL_MS = 30_000  // poll toutes les 30 s
const STORAGE_KEY = 'sylea_actions_status_cache'

/**
 * Charge le statut d'actions de l'utilisateur.
 *
 * Cache localStorage pour éviter le flash au boot, polling 30 s pour
 * rafraîchir, invalidé naturellement à minuit (le backend filtre par date).
 */
export function useActionsStatus(): {
  status: ActionsStatus | null
  refresh: () => void
} {
  const [status, setStatus] = useState<ActionsStatus | null>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) return JSON.parse(raw)
    } catch {
      /* cache invalide */
    }
    return null
  })

  const fetchStatus = async () => {
    try {
      const token = localStorage.getItem('sylea_auth_token')
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const r = await fetch(`${API_BASE}/api/actions/today`, {
        headers,
        credentials: 'include',
      })
      if (!r.ok) return
      const data: ActionsStatus = await r.json()
      setStatus(data)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* quota localStorage */
      }
    } catch {
      /* offline */
    }
  }

  useEffect(() => {
    fetchStatus()
    const id = setInterval(fetchStatus, ACTIONS_TTL_MS)
    return () => clearInterval(id)
  }, [])

  return { status, refresh: fetchStatus }
}

// ── Composant visuel ───────────────────────────────────────────────────────

interface ActionLightningProps {
  /** Taille de l'éclair en px (défaut 22). Le nombre s'adapte automatiquement. */
  size?: number
  /** Override pour les tests / preview */
  status?: ActionsStatus | null
  /** Callback au clic (ouvre /quotas typiquement) */
  onClick?: () => void
  /** Style additionnel pour le conteneur */
  style?: React.CSSProperties
  /** Si true : affiche "X / 10" au lieu de "X" seul */
  showLimit?: boolean
}

export function ActionLightning({
  size = 22,
  status: overrideStatus,
  onClick,
  style = {},
  showLimit = false,
}: ActionLightningProps) {
  const { status: hookStatus } = useActionsStatus()
  const status = overrideStatus ?? hookStatus

  if (!status) {
    // Skeleton minimal pendant le 1er fetch
    return (
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 9px',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 999,
          opacity: 0.5,
          ...style,
        }}
        aria-hidden="true"
      >
        <LightningBolt size={size} />
        <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'rgba(255,255,255,0.5)' }}>—</span>
      </div>
    )
  }

  const label = status.is_unlimited
    ? '∞'
    : showLimit
      ? `${Math.max(0, status.remaining)} / ${status.limit}`
      : `${Math.max(0, status.remaining)}`

  const planLabel = status.plan === 'free' ? 'Free' : 'Avancé'
  const tooltip = status.is_unlimited
    ? `Actions illimitées (plan ${planLabel})`
    : `${status.remaining}/${status.limit} actions restantes (plan ${planLabel}). Reset à minuit UTC.`

  return (
    <button
      onClick={onClick}
      title={tooltip}
      aria-label={`${label} actions restantes aujourd'hui`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px 4px 6px',
        // Fond et bordure neutres : aucun changement selon l'état
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(150,200,255,0.18)',
        borderRadius: 999,
        cursor: onClick ? 'pointer' : 'default',
        color: 'rgba(255,255,255,0.95)',
        fontSize: '0.82rem',
        fontWeight: 700,
        fontFamily: 'inherit',
        transition: 'background 0.2s, border-color 0.2s',
        lineHeight: 1,
        ...style,
      }}
      onMouseEnter={(e) => {
        if (onClick) {
          e.currentTarget.style.background = 'rgba(150,200,255,0.10)'
          e.currentTarget.style.borderColor = 'rgba(150,200,255,0.35)'
        }
      }}
      onMouseLeave={(e) => {
        if (onClick) {
          e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
          e.currentTarget.style.borderColor = 'rgba(150,200,255,0.18)'
        }
      }}
    >
      <LightningBolt size={size} />
      <span>{label}</span>
    </button>
  )
}

// ── L'éclair SVG (même technique multi-couches que SyleaLogo) ──────────────

interface LightningBoltProps {
  size: number
}

/**
 * Éclair stylisé : 5 couches superposées sur un path zigzag — exactement
 * la même technique que le logo Syléa officiel (cf. SyleaLogo.tsx) :
 *
 *   Couche 1 — Halo flou (gradient + filter blur, opacité 25 %)
 *   Couche 2 — Bordure extérieure sombre (donne la profondeur du "tube")
 *   Couche 3 — Corps gradient blanc → bleu (les deux rails du tube)
 *   Couche 4 — Canal central creux (sombre, butt linecap → ne déborde
 *              pas aux extrémités donc les caps restent solides)
 *   Couche 5 — Reflet spéculaire fin (brillance blanche-cyan)
 *
 * Path : zigzag stylisé top-droit → milieu-gauche → milieu-droit
 *        (jog horizontal court) → bas-gauche.
 */
function LightningBolt({ size }: LightningBoltProps) {
  // ID unique : évite les collisions quand plusieurs éclairs sont sur la
  // même page (Dashboard + chat Agent 1 par ex.)
  const uid = useId().replace(/\W/g, '')
  const gradId = `lt-g-${uid}`
  const haloId = `lt-h-${uid}`

  // Path zigzag dans un viewBox 120×120 (même échelle que SyleaLogo).
  // Le `Z` final ferme légèrement la pointe basse pour éviter un cap trop épais.
  const BOLT = 'M 78 15 L 36 64 L 64 64 L 24 105'

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <defs>
        {/* Gradient blanc → bleu (fixe — ne change JAMAIS selon l'état) */}
        <linearGradient id={gradId} x1="50%" y1="0%" x2="50%" y2="100%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="40%" stopColor="#b8dcff" />
          <stop offset="100%" stopColor="#1890ff" />
        </linearGradient>

        {/* Halo flou — région étendue pour éviter le clipping rectangulaire */}
        <filter
          id={haloId}
          x="-100%" y="-100%" width="300%" height="300%"
          filterUnits="objectBoundingBox"
        >
          <feGaussianBlur stdDeviation="5" />
        </filter>
      </defs>

      {/* Couche 1 — Halo atmosphérique */}
      <path
        d={BOLT}
        stroke={`url(#${gradId})`}
        strokeWidth="30"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          filter: `url(#${haloId})`,
          opacity: 0.28,
        }}
      />

      {/* Couche 2 — Bordure extérieure sombre (tube profondeur) */}
      <path
        d={BOLT}
        stroke="rgba(2,4,16,0.97)"
        strokeWidth="20"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Couche 3 — Corps gradient (les deux rails du tube) */}
      <path
        d={BOLT}
        stroke={`url(#${gradId})`}
        strokeWidth="16"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          filter: 'drop-shadow(0 0 2px rgba(120,180,255,0.5))',
        }}
      />

      {/* Couche 4 — Canal central creux (butt linecap → caps gradient solides) */}
      <path
        d={BOLT}
        stroke="#050810"
        strokeWidth="6"
        fill="none"
        strokeLinecap="butt"
        strokeLinejoin="miter"
      />

      {/* Couche 5 — Reflet spéculaire (brillance) */}
      <path
        d={BOLT}
        stroke="rgba(220,240,255,0.65)"
        strokeWidth="1.2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
