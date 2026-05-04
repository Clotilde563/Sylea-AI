/**
 * Live activity feed (Sprint 2 — feature 2.6)
 *
 * Affiche un feed temps-reel des agents qui sont en train d'agir, facon
 * "Sylea 3 ecrit...", "Sylea 2 reflechit...", avec typing dots animes.
 *
 * Recoit une liste d'`activities` (agentId, label, since) et auto-cleanup
 * apres `staleMs` (default 8s) sans update. Le composant ne gere pas le state
 * lui-meme : il consomme un prop. Le parent (App.tsx) maintient la map
 * agent->lastActivity en ecoutant les events WebSocket.
 */
import { useEffect, useState } from 'react'

export interface LiveActivity {
  agentId: string
  agentName: string
  agentColor: string
  /** Verbe d'action : 'ecrit' | 'reflechit' | 'cherche' | 'execute' */
  verb: string
  /** Message court optionnel (ex: nom du fichier, query, ...) */
  detail?: string
  /** timestamp ms (Date.now()) */
  since: number
}

interface LiveActivityFeedProps {
  activities: LiveActivity[]
  /** ms apres lesquelles une activite disparait du feed */
  staleMs?: number
  /** Couleur de bordure / accent par defaut */
  accent?: string
  /** Style du wrapper */
  style?: React.CSSProperties
}

export function LiveActivityFeed({
  activities,
  staleMs = 8000,
  accent = '#00c8ff',
  style,
}: LiveActivityFeedProps) {
  const [now, setNow] = useState(Date.now())

  // Tick chaque seconde pour faire vieillir les activites + animer dots
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [])

  const fresh = activities
    .filter(a => now - a.since < staleMs)
    .slice(-3) // garde les 3 plus recents

  if (fresh.length === 0) {
    return (
      <div
        style={{
          padding: '6px 10px',
          fontFamily: '"JetBrains Mono","Fira Code",monospace',
          fontSize: 10, letterSpacing: '0.16em',
          color: 'rgba(230, 240, 255, 0.35)',
          textTransform: 'uppercase',
          display: 'flex', alignItems: 'center', gap: 8,
          ...style,
        }}
      >
        <span style={{
          width: 5, height: 5, borderRadius: '50%',
          background: 'rgba(230, 240, 255, 0.18)',
        }} />
        <span>idle · waiting for agents</span>
      </div>
    )
  }

  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', gap: 4,
        padding: '4px 0',
        ...style,
      }}
    >
      {fresh.map((a, i) => {
        const age = now - a.since
        const opacity = Math.max(0.45, 1 - age / staleMs)
        return (
          <div
            key={`${a.agentId}-${a.since}-${i}`}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '5px 10px',
              borderLeft: `2px solid ${a.agentColor}`,
              background: `${a.agentColor}0d`,
              borderRadius: '0 4px 4px 0',
              opacity,
              transition: 'opacity 0.4s, background 0.2s',
              animation: 'sy-feed-slide-in 0.35s ease-out',
            }}
          >
            {/* Pulse dot agent color */}
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: a.agentColor,
              boxShadow: `0 0 6px ${a.agentColor}`,
              animation: 'sy-pulse 1.4s ease-in-out infinite',
              flexShrink: 0,
            }} />
            <div style={{
              fontSize: 11, fontFamily: 'inherit',
              color: 'rgba(230, 240, 255, 0.85)',
              flex: 1, minWidth: 0,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              <span style={{ color: a.agentColor, fontWeight: 600 }}>{a.agentName}</span>
              <span style={{ color: 'rgba(230, 240, 255, 0.55)', margin: '0 4px' }}>
                {a.verb}
              </span>
              <TypingDots color={accent} />
              {a.detail && (
                <span style={{
                  marginLeft: 8,
                  fontFamily: '"JetBrains Mono",monospace', fontSize: 10,
                  color: 'rgba(230, 240, 255, 0.45)',
                }}>
                  {a.detail.length > 50 ? a.detail.slice(0, 47) + '…' : a.detail}
                </span>
              )}
            </div>
          </div>
        )
      })}
      <style>{`
        @keyframes sy-feed-slide-in {
          from { opacity: 0; transform: translateX(-8px); }
          to   { opacity: 1; transform: translateX(0); }
        }
        @keyframes sy-typing-dot {
          0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
          40%           { opacity: 1;    transform: translateY(-2px); }
        }
      `}</style>
    </div>
  )
}

interface TypingDotsProps { color: string }

function TypingDots({ color }: TypingDotsProps) {
  const dot: React.CSSProperties = {
    display: 'inline-block',
    width: 3, height: 3, borderRadius: '50%',
    background: color,
    margin: '0 1px',
    animation: 'sy-typing-dot 1.2s infinite',
  }
  return (
    <span style={{ display: 'inline-flex', verticalAlign: 'middle', marginLeft: 2 }}>
      <span style={dot} />
      <span style={{ ...dot, animationDelay: '0.15s' }} />
      <span style={{ ...dot, animationDelay: '0.30s' }} />
    </span>
  )
}

export default LiveActivityFeed
