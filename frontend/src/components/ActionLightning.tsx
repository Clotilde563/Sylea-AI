// Badge éclair affichant le nombre d'actions restantes aujourd'hui.
//
// Visuel : éclair stylisé dans le même esprit que le logo Syléa (tube double-rail
// avec gradient blanc → bleu, halo lumineux), accompagné du compteur "X / 10"
// ou "X / 30" selon le plan.
//
// Affiché :
//   - Dashboard (en haut à droite, à côté du logo)
//   - Chat Agent 1 (badge ancré dans l'header)
//   - Chat Agent 2 (idem)
//
// Couleur :
//   - Normal (> 30 % restants)         : gradient blanc → bleu clair
//   - Bas (< 30 %, > 0)                : gradient blanc → orange
//   - Épuisé (0)                       : gradient gris → rouge + pulsation
//   - Illimité (plan team / enterprise) : gradient blanc → cyan + symbole ∞

import { useEffect, useState, useId } from 'react'
import { API_BASE } from '../api/client'

// ── Types ───────────────────────────────────────────────────────────────────

interface ActionsStatus {
  used: number
  limit: number             // -1 = illimité
  remaining: number
  plan: string              // 'free' | 'pro' | 'team' | ...
  is_unlimited: boolean
  reset_at: string          // ISO timestamp
}

// ── Hook : fetch + auto-refresh ────────────────────────────────────────────

const ACTIONS_TTL_MS = 30_000  // poll toutes les 30 s pour mettre à jour
const STORAGE_KEY = 'sylea_actions_status_cache'

/**
 * Hook React pour charger le statut d'actions.
 *
 * - Cache localStorage pour éviter le flash au boot
 * - Polling toutes les 30 s
 * - Le hook s'invalide automatiquement à minuit (reset_at)
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
      /* cache invalide, on ignore */
    }
    return null
  })

  const fetchStatus = async () => {
    try {
      const token = localStorage.getItem('sylea_auth_token')
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const r = await fetch(`${API_BASE}/api/actions/today`, { headers })
      if (!r.ok) return
      const data: ActionsStatus = await r.json()
      setStatus(data)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* quota localStorage, on ignore */
      }
    } catch {
      /* offline / API down — on garde le cache */
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
  /** Taille de l'icône en px (défaut 22) */
  size?: number
  /** Variante d'affichage */
  variant?: 'badge' | 'compact' | 'verbose'
  /** Override : force le statut (utile pour les preview / Storybook) */
  status?: ActionsStatus | null
  /** Callback au clic (ouvre habituellement /quotas) */
  onClick?: () => void
  /** Style additionnel pour le conteneur */
  style?: React.CSSProperties
}

export function ActionLightning({
  size = 22,
  variant = 'badge',
  status: overrideStatus,
  onClick,
  style = {},
}: ActionLightningProps) {
  const { status: hookStatus } = useActionsStatus()
  const status = overrideStatus ?? hookStatus

  if (!status) {
    // Skeleton minimal pendant le 1er fetch
    return (
      <div
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '4px 8px',
          background: 'rgba(255,255,255,0.04)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 999,
          opacity: 0.5,
          ...style,
        }}
      >
        <LightningSvg size={size} state="loading" />
      </div>
    )
  }

  // ── Calcul de l'état visuel ──
  const state = computeState(status)
  const labelMain = status.is_unlimited
    ? '∞'
    : `${Math.max(0, status.remaining)}`
  const labelSub = status.is_unlimited
    ? 'illimité'
    : `/ ${status.limit}`

  // ── Couleurs selon état ──
  const colors = STATE_COLORS[state]

  // ── Variantes ──
  if (variant === 'compact') {
    return (
      <button
        onClick={onClick}
        title={tooltipText(status)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          padding: '3px 7px',
          background: 'transparent',
          border: `1px solid ${colors.border}`,
          borderRadius: 999,
          cursor: onClick ? 'pointer' : 'default',
          color: colors.text,
          fontSize: '0.72rem',
          fontWeight: 600,
          fontFamily: 'inherit',
          ...style,
        }}
      >
        <LightningSvg size={size} state={state} />
        <span>{labelMain}</span>
      </button>
    )
  }

  if (variant === 'verbose') {
    return (
      <button
        onClick={onClick}
        title={tooltipText(status)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 12px',
          background: colors.bg,
          border: `1px solid ${colors.border}`,
          borderRadius: 999,
          cursor: onClick ? 'pointer' : 'default',
          color: colors.text,
          fontSize: '0.85rem',
          fontWeight: 600,
          fontFamily: 'inherit',
          transition: 'all 0.2s',
          ...style,
        }}
      >
        <LightningSvg size={size} state={state} />
        <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.15 }}>
          <span style={{ fontWeight: 700 }}>
            {labelMain} <span style={{ opacity: 0.6, fontSize: '0.85em' }}>{labelSub}</span>
          </span>
          <span style={{ fontSize: '0.65rem', opacity: 0.65, fontWeight: 400 }}>
            actions restantes
          </span>
        </span>
      </button>
    )
  }

  // 'badge' (default)
  return (
    <button
      onClick={onClick}
      title={tooltipText(status)}
      aria-label={`${labelMain} actions restantes aujourd'hui`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '4px 10px',
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: 999,
        cursor: onClick ? 'pointer' : 'default',
        color: colors.text,
        fontSize: '0.78rem',
        fontWeight: 600,
        fontFamily: 'inherit',
        transition: 'all 0.2s',
        ...style,
      }}
      onMouseEnter={(e) => {
        if (onClick) e.currentTarget.style.background = colors.bgHover
      }}
      onMouseLeave={(e) => {
        if (onClick) e.currentTarget.style.background = colors.bg
      }}
    >
      <LightningSvg size={size} state={state} />
      <span>
        <span style={{ fontWeight: 700 }}>{labelMain}</span>
        <span style={{ opacity: 0.55, marginLeft: 2 }}>{labelSub}</span>
      </span>
    </button>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

type LightningState = 'normal' | 'low' | 'empty' | 'unlimited' | 'loading'

function computeState(s: ActionsStatus): LightningState {
  if (s.is_unlimited) return 'unlimited'
  if (s.limit <= 0) return 'loading'
  if (s.remaining <= 0) return 'empty'
  if (s.remaining / s.limit < 0.3) return 'low'
  return 'normal'
}

function tooltipText(s: ActionsStatus): string {
  if (s.is_unlimited) return 'Actions illimitées sur ton plan'
  if (s.remaining <= 0) {
    return `Tu as utilisé toutes tes ${s.limit} actions du jour. Réinitialisation à minuit UTC.`
  }
  const planLabel = s.plan === 'free' ? 'Free' : 'Avancé'
  return `${s.remaining}/${s.limit} actions restantes (plan ${planLabel}). Reset à minuit UTC.`
}

const STATE_COLORS: Record<LightningState, {
  bg: string; bgHover: string; border: string; text: string;
}> = {
  normal: {
    bg: 'linear-gradient(135deg, rgba(255,255,255,0.04), rgba(0,150,240,0.08))',
    bgHover: 'linear-gradient(135deg, rgba(255,255,255,0.08), rgba(0,150,240,0.14))',
    border: 'rgba(0,180,255,0.35)',
    text: 'rgba(255,255,255,0.95)',
  },
  low: {
    bg: 'linear-gradient(135deg, rgba(255,255,255,0.04), rgba(245,158,11,0.08))',
    bgHover: 'linear-gradient(135deg, rgba(255,255,255,0.08), rgba(245,158,11,0.14))',
    border: 'rgba(245,158,11,0.45)',
    text: 'rgba(255,200,100,0.95)',
  },
  empty: {
    bg: 'linear-gradient(135deg, rgba(150,150,150,0.08), rgba(239,68,68,0.12))',
    bgHover: 'linear-gradient(135deg, rgba(150,150,150,0.12), rgba(239,68,68,0.18))',
    border: 'rgba(239,68,68,0.5)',
    text: 'rgba(255,150,150,0.95)',
  },
  unlimited: {
    bg: 'linear-gradient(135deg, rgba(255,255,255,0.06), rgba(0,200,255,0.10))',
    bgHover: 'linear-gradient(135deg, rgba(255,255,255,0.10), rgba(0,200,255,0.18))',
    border: 'rgba(0,200,255,0.45)',
    text: 'rgba(180,230,255,0.95)',
  },
  loading: {
    bg: 'transparent',
    bgHover: 'transparent',
    border: 'rgba(255,255,255,0.10)',
    text: 'rgba(255,255,255,0.5)',
  },
}

// ── L'éclair SVG (gradient blanc → bleu, même esprit que le logo Syléa) ────

interface LightningSvgProps {
  size: number
  state: LightningState
}

function LightningSvg({ size, state }: LightningSvgProps) {
  // ID unique pour éviter les collisions de gradient quand plusieurs éclairs
  // sont sur la même page (Dashboard + chat Agent 1 par ex)
  const uid = useId().replace(/\W/g, '')
  const gradId = `lt-g-${uid}`
  const haloId = `lt-h-${uid}`

  // Gradient selon l'état
  const stops = state === 'empty'
    ? [{ off: '0%', color: '#fff' }, { off: '100%', color: '#ef4444' }]
    : state === 'low'
      ? [{ off: '0%', color: '#fff' }, { off: '100%', color: '#f59e0b' }]
      : state === 'unlimited'
        ? [{ off: '0%', color: '#fff' }, { off: '50%', color: '#a0e1ff' }, { off: '100%', color: '#00c8ff' }]
        : [{ off: '0%', color: '#ffffff' }, { off: '50%', color: '#a0d8ff' }, { off: '100%', color: '#1890ff' }]

  // Eclair stylisé : bolt simple mais avec rails / canal central comme le logo
  // viewBox 24×24, l'éclair traverse en diagonale haut-droite → bas-gauche
  // Path de l'éclair principal (forme classique zigzag) :
  const BOLT = 'M 14 2 L 5 13 L 11 13 L 9 22 L 18 11 L 12 11 Z'

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ display: 'block', flexShrink: 0 }}
    >
      <defs>
        <linearGradient id={gradId} x1="50%" y1="0%" x2="50%" y2="100%">
          {stops.map((s, i) => (
            <stop key={i} offset={s.off} stopColor={s.color} />
          ))}
        </linearGradient>
        <filter id={haloId} x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="0.8" />
        </filter>
      </defs>

      {/* Halo lumineux derrière */}
      <path
        d={BOLT}
        fill={`url(#${gradId})`}
        opacity={0.4}
        style={{ filter: `url(#${haloId})` }}
      />

      {/* Corps de l'éclair (gradient blanc → bleu) */}
      <path
        d={BOLT}
        fill={`url(#${gradId})`}
        stroke="rgba(255,255,255,0.55)"
        strokeWidth="0.4"
        strokeLinejoin="round"
      >
        {state === 'empty' && (
          <animate
            attributeName="opacity"
            values="0.45;1;0.45"
            dur="1.6s"
            repeatCount="indefinite"
          />
        )}
      </path>
    </svg>
  )
}
