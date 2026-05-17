/**
 * DesktopStatusBanner — Bandeau en haut du dashboard qui rassure l'utilisateur
 * sur l'etat du pont web -> desktop (phase 2c).
 *
 * 2 etats :
 *   🟢 connecte (vert, discret) : une fine bande verte "Syléa Desktop est pret"
 *   🔴 pas connecte (rouge, visible) : bandeau avec CTA "Telecharger" / "Lancer"
 *
 * Se connecte au backend via `/api/desktop/status` qui verifie si l'utilisateur
 * a une connexion WebSocket active dans `ws_manager`.
 *
 * Philosophie UX : **simple et ludique pour un utilisateur non-tech**.
 * - Pas de jargon technique ("WebSocket", "gateway", "token")
 * - Emoji + couleurs pour l'instinct
 * - Le message change selon le contexte (installe/pas installe)
 * - Un seul CTA clair
 */

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuthStore } from '../auth/authStore'
import { usePlan } from '../hooks/usePlan'

// LocalStorage key : marqueur "j'ai deja telecharge le desktop une fois".
// Pas une verite absolue, mais permet de changer le ton du message.
//
// IMPORTANT : la cle est SCOPEE PAR COMPTE (email). Sinon, sur un meme
// navigateur partage entre plusieurs comptes Google, le marqueur du compte
// A "fuiterait" sur le compte B → la banniere afficherait "Ton app est en
// pause" (😴) sur un compte qui n'a jamais installe le desktop.
const DESKTOP_SEEN_KEY_PREFIX = 'sylea_desktop_seen'

function desktopSeenKey(email: string | null | undefined): string {
  // Sans email (jamais connecte), on n'utilise pas de marqueur persistant.
  // On retourne une cle "anonymous" qui ne sera jamais ecrite.
  return email ? `${DESKTOP_SEEN_KEY_PREFIX}:${email}` : `${DESKTOP_SEEN_KEY_PREFIX}:anonymous`
}

// URL de telechargement du desktop. Pour le MVP on renvoie vers une page
// d'aide avec les liens. A terme -> GitHub Releases ou CDN Syléa.
const DOWNLOAD_URL = '/help#telecharger-desktop'

type Status = 'loading' | 'connected' | 'disconnected'

export function DesktopStatusBanner() {
  const userEmail = useAuthStore((s) => s.user?.email)
  const { isFree, loading: planLoading } = usePlan()
  const [status, setStatus] = useState<Status>('loading')
  const [hasSeenDesktop, setHasSeenDesktop] = useState<boolean>(
    () => typeof window !== 'undefined' && !!localStorage.getItem(desktopSeenKey(userEmail))
  )

  // Re-evalue le marqueur si l'utilisateur change (logout/login d'un autre compte
  // sans recharger la page). Sinon le compte B verrait l'etat "deja vu" du compte A.
  useEffect(() => {
    if (typeof window === 'undefined') return
    // Migration : supprime l'ancienne cle non-scopee qui aurait pu causer la
    // confusion entre comptes. On le fait une seule fois (idempotent).
    if (localStorage.getItem(DESKTOP_SEEN_KEY_PREFIX) !== null) {
      localStorage.removeItem(DESKTOP_SEEN_KEY_PREFIX)
    }
    setHasSeenDesktop(!!localStorage.getItem(desktopSeenKey(userEmail)))
  }, [userEmail])
  const [justConnected, setJustConnected] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const res = await api.checkDesktopStatus()
        if (cancelled) return
        if (res.connected) {
          // Si on passe de disconnected -> connected, afficher l'animation "just connected" 4s
          if (status === 'disconnected') {
            setJustConnected(true)
            setTimeout(() => setJustConnected(false), 4000)
          }
          setStatus('connected')
          if (!hasSeenDesktop && userEmail) {
            // On ne pose le marqueur QUE si on a un email (compte authentifie).
            // Sans email, ne pas polluer le localStorage avec une cle "anonymous".
            localStorage.setItem(desktopSeenKey(userEmail), '1')
            setHasSeenDesktop(true)
          }
        } else {
          setStatus('disconnected')
        }
      } catch {
        // Le backend est down : on reste en 'loading' pour ne pas paniquer
        // l'utilisateur avec un rouge inutile
        if (!cancelled) setStatus('loading')
      }
    }

    poll()
    const interval = setInterval(poll, 15000) // toutes les 15s
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [hasSeenDesktop, status, userEmail])

  // Etat neutre / loading : rien (ne pas flasher au chargement)
  if (status === 'loading') return null
  if (dismissed) return null
  // Sylea Desktop est reserve aux abonnes Avance. Pour les Free, on cache
  // le bandeau (pas de pousse a installer si la fonctionnalite leur est
  // de toute facon inaccessible). On attend que le plan soit charge pour
  // ne pas flasher le bandeau a la 1re render.
  if (planLoading) return null
  if (isFree) return null

  // ── ETAT CONNECTE : bandeau vert fin, discret ────────────────────────────
  if (status === 'connected') {
    // Affichage pulsant les premieres secondes apres connexion, puis normal
    return (
      <div
        style={{
          background: justConnected
            ? 'linear-gradient(90deg, rgba(16,185,129,0.25), rgba(16,185,129,0.10))'
            : 'rgba(16,185,129,0.08)',
          borderBottom: '1px solid rgba(16,185,129,0.25)',
          padding: '6px 20px',
          fontSize: 12.5,
          color: '#10b981',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          fontWeight: 500,
          letterSpacing: '0.02em',
          transition: 'background 0.6s ease',
        }}
        role="status"
        aria-live="polite"
      >
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: '#10b981',
            boxShadow: '0 0 6px rgba(16,185,129,0.7)',
            animation: justConnected ? 'sylea-pulse 1s ease-in-out infinite' : 'none',
          }}
        />
        {justConnected ? (
          <>
            <b>Super !</b> Ton ordinateur est relie a Syléa — il peut maintenant agir
            pour toi 🎉
          </>
        ) : (
          <>Syléa Desktop est pret a agir pour toi</>
        )}
        <style>{`
          @keyframes sylea-pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50%      { transform: scale(1.35); opacity: 0.75; }
          }
        `}</style>
      </div>
    )
  }

  // ── ETAT NON CONNECTE : bandeau rouge avec CTA ──────────────────────────
  return (
    <div
      style={{
        background: 'linear-gradient(135deg, rgba(239,68,68,0.12), rgba(249,115,22,0.10))',
        borderBottom: '1px solid rgba(239,68,68,0.3)',
        padding: '12px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
      }}
      role="status"
      aria-live="polite"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: '1 1 auto', minWidth: 0 }}>
        <div
          style={{
            fontSize: 22,
            lineHeight: 1,
            flexShrink: 0,
          }}
          aria-hidden
        >
          {hasSeenDesktop ? '😴' : '💎'}
        </div>
        <div style={{ fontSize: 13.5, lineHeight: 1.45, color: 'rgba(255,255,255,0.92)' }}>
          {hasSeenDesktop ? (
            <>
              <b>Ton app Syléa Desktop est en pause.</b>{' '}
              <span style={{ opacity: 0.75 }}>
                Lance-la sur ton ordinateur pour que Syléa puisse agir pour toi (emails,
                calendrier, notes...).
              </span>
            </>
          ) : (
            <>
              <b>Active les super-pouvoirs de Syléa.</b>{' '}
              <span style={{ opacity: 0.75 }}>
                Installe l'app Syléa Desktop — elle permet a Syléa d'agir concretement
                dans ta vie (emails, calendrier, notes...).
              </span>
            </>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <a
          href={DOWNLOAD_URL}
          style={{
            background:
              'linear-gradient(135deg, #06b6d4 0%, #6366f1 50%, #8b5cf6 100%)',
            color: 'white',
            padding: '8px 18px',
            borderRadius: 10,
            textDecoration: 'none',
            fontSize: 13,
            fontWeight: 600,
            boxShadow: '0 2px 10px rgba(99,102,241,0.35)',
            whiteSpace: 'nowrap',
          }}
        >
          {hasSeenDesktop ? '🚀 Comment la relancer ?' : '✨ Activer Syléa Desktop'}
        </a>
        <button
          onClick={() => setDismissed(true)}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'rgba(255,255,255,0.5)',
            cursor: 'pointer',
            fontSize: 18,
            padding: '4px 8px',
            lineHeight: 1,
          }}
          aria-label="Fermer"
          title="Masquer ce message pour cette session"
        >
          ×
        </button>
      </div>
    </div>
  )
}

export default DesktopStatusBanner
