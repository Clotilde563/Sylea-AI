import { useState, useEffect, useRef, useCallback } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import OpenClawOnboarding from './OpenClawOnboarding'
import { SyleaLogo, SyleaWordmark, AgentSyleaLogo, type AgentVariant } from './SyleaLogo'
import { DesktopTitlebar } from './DesktopTitlebar'
import { useDragDrop, type DroppedFile } from './useDragDrop'
import { SplashScreen } from './SplashScreen'
import { BackgroundParticles } from './BackgroundParticles'
import { LiveActivityFeed, type LiveActivity } from './LiveActivityFeed'
import { StatsHUD, type StatsHUDData, pushHist } from './StatsHUD'
import { CountUp } from './CountUp'
import { SlideIn } from './Motion'
import { EcouteActive } from './EcouteActive'
import { apiFetch } from './apiClient'

// API backend URL. En dev : localhost. En prod : configurable via VITE_API_BASE
// (au build Tauri) ou via window.localStorage 'sylea_api_base' (modifiable user).
const API_BASE = (
  (typeof window !== 'undefined' && window.localStorage?.getItem('sylea_api_base')) ||
  (import.meta.env as any)?.VITE_API_BASE ||
  'http://localhost:8000'
)

// ── Palette officielle tech ────────────────────────────────────────────────
// Source de verite : desktop/index.html (variables CSS --sy-*)
const SY = {
  cyan:     '#00c8ff',
  cyanSoft: '#7ad9ff',
  blue:     '#0090e0',
  indigo:   '#1848d8',
  violet:   '#5520b8',
  text:     '#e6f0ff',
  textMute: 'rgba(230, 240, 255, 0.60)',
  textDim:  'rgba(230, 240, 255, 0.35)',
  border:   'rgba(0, 200, 255, 0.12)',
  borderHi: 'rgba(0, 200, 255, 0.25)',
  surface:  'rgba(0, 200, 255, 0.03)',
  surfaceHi:'rgba(0, 200, 255, 0.06)',
  bg:       '#050810',
  bgElev:   '#070c1a',
  success:  '#10b981',
  warn:     '#f59e0b',
  error:    '#ef4444',
  mono:     '"JetBrains Mono","Fira Code","Cascadia Code","Consolas",monospace',
}

interface ActionStep {
  id: string
  action: string
  status: 'pending' | 'running' | 'done' | 'error'
  detail: string
  time: string
  agent?: string  // 'agent2' | 'agent3' — source agent
}

interface AgentInfo {
  id: string
  name: string
  color: string
  colorLight: string
  logoVariant: AgentVariant
  status: 'active' | 'inactive' | 'locked'
  unread: number
}

// Agents & couleurs alignees sur frontend/src/pages/AgentsPage.tsx (source de
// verite web). Chaque agent a son logo colore + sa couleur d'accent :
//   Agent 1  — or (assistant personnel du quotidien)
//   Agent 2  — rouge (emails / rappels / voix)
//   Agent 3  — bleu-or anime (agent d'elite, OpenClaw)
//   Super Agent — violet (verrouille)
//
// IMPORTANT : status n'est PAS hardcode ici. Il est derive dynamiquement de
// `lastActivityByAgent` : 'active' si le backend a envoye un message pour cet
// agent dans les dernieres 30s, sinon 'inactive'. agent4 reste 'locked'.
const AGENTS_BASE: Omit<AgentInfo, 'status' | 'unread'>[] = [
  { id: 'agent1', name: 'Syléa 1',   color: '#f59e0b', colorLight: '#fbbf24', logoVariant: 'gold' },
  { id: 'agent2', name: 'Syléa 2',   color: '#ef4444', colorLight: '#f87171', logoVariant: 'red' },
  { id: 'agent3', name: 'Syléa 3',   color: '#38bdf8', colorLight: '#a5b4fc', logoVariant: 'agent3' },
  { id: 'agent4', name: 'Super Agent', color: '#8b5cf6', colorLight: '#c4b5fd', logoVariant: 'violet' },
]
const ACTIVITY_TTL_MS = 30_000  // au-dela, l'agent passe en 'inactive'

// Agent 3 conserve sa signature visuelle (cyan -> indigo) pour rester reperable
const AGENT3_CYAN   = '#38bdf8'
const AGENT3_INDIGO = '#818cf8'

// ── Helpers UI tech ─────────────────────────────────────────────────────────

/** Coin techniques ┌ ┐ ┘ └ — decorent les cartes */
function CornerBrackets({ color = SY.cyan, size = 10 }: { color?: string; size?: number }) {
  const s: React.CSSProperties = {
    position: 'absolute', width: size, height: size,
    borderColor: color, pointerEvents: 'none',
  }
  return (
    <>
      <span style={{ ...s, top: 4, left: 4, borderTop: `1px solid ${color}`, borderLeft: `1px solid ${color}` }} />
      <span style={{ ...s, top: 4, right: 4, borderTop: `1px solid ${color}`, borderRight: `1px solid ${color}` }} />
      <span style={{ ...s, bottom: 4, left: 4, borderBottom: `1px solid ${color}`, borderLeft: `1px solid ${color}` }} />
      <span style={{ ...s, bottom: 4, right: 4, borderBottom: `1px solid ${color}`, borderRight: `1px solid ${color}` }} />
    </>
  )
}

/** Label technique en mono caps */
function TechLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.16em',
      color: SY.textMute, marginBottom: 6,
      textTransform: 'uppercase',
    }}>
      {children}
    </div>
  )
}

/** Input technique — bord cyan discret, focus glow */
function TechInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      style={{
        width: '100%', padding: '10px 12px',
        borderRadius: 6,
        border: `1px solid ${SY.border}`,
        background: 'rgba(5, 8, 16, 0.6)',
        color: SY.text,
        fontSize: 13,
        fontFamily: 'inherit',
        transition: 'all 0.15s',
      }}
      onFocus={e => {
        e.currentTarget.style.borderColor = SY.cyan
        e.currentTarget.style.boxShadow = `0 0 0 2px rgba(0,200,255,0.1)`
      }}
      onBlur={e => {
        e.currentTarget.style.borderColor = SY.border
        e.currentTarget.style.boxShadow = 'none'
      }}
    />
  )
}

/** Pastille de statut — cyan/vert/orange/rouge selon l'etat */
function StatusDot({ color, pulsing = false, size = 7 }: { color: string; pulsing?: boolean; size?: number }) {
  return (
    <span
      style={{
        display: 'inline-block', width: size, height: size, borderRadius: '50%',
        background: color,
        boxShadow: `0 0 ${size}px ${color}, 0 0 2px ${color}`,
        animation: pulsing ? 'sy-pulse 1.5s ease-in-out infinite' : 'none',
        flexShrink: 0,
      }}
    />
  )
}

function App() {
  // Ecoute active — Sprint dev cours universite/prepa.
  // Ouvert quand le web frontend declenche start_lecture via WS, OU
  // depuis le bouton sidebar (Agent 2 only).
  const [ecouteActiveOpen, setEcouteActiveOpen] = useState(false)

  // Sign in with Apple — deep-link callback handler.
  // Quand l'utilisateur clique "Continuer avec Apple" depuis le desktop, on
  // ouvre le navigateur systeme vers sylea.ai. Apres auth, le backend
  // redirige vers sylea://auth/callback?token=<JWT>. macOS/Windows reconnait
  // le scheme et lance Sylea Agent qui emet l'event 'deep-link:received'.
  useEffect(() => {
    const unsub = listen<string>('deep-link:received', (event) => {
      try {
        const url = new URL(event.payload)
        if (url.protocol !== 'sylea:') return
        // Chemin /auth/callback : extrait le token JWT, stocke localStorage
        // et notifie le web (qui se reconnecte automatiquement via WS).
        if (url.pathname === '/auth/callback' || url.hostname === 'auth') {
          const token = url.searchParams.get('token')
          if (token) {
            localStorage.setItem('sylea_auth_token', token)
            // Le web app sera notifie via storage event au refresh
            // Notification UI minimale pour confirmer
            console.log('[deep-link] Apple Sign-In token reçu, longueur:', token.length)
          }
        }
      } catch (e) {
        console.warn('[deep-link] URL invalide:', e)
      }
    })
    return () => {
      unsub.then((fn) => fn()).catch(() => {})
    }
  }, [])

  // Sprint 2.1 — Splash screen au premier mount (1.4s). Une seule fois par
  // session, pas re-affiche apres login/logout.
  const [splashDone, setSplashDone] = useState(false)
  const finishSplash = useCallback(() => setSplashDone(true), [])
  // Safety net : meme si le splash bug, force la fin a 4s (1.4s normal + 2.6s safety)
  useEffect(() => {
    if (splashDone) return
    const safety = setTimeout(() => setSplashDone(true), 4000)
    return () => clearTimeout(safety)
  }, [splashDone])

  // Sprint 2.6 — Live activity feed : map agentId → derniere activite
  const [liveActivities, setLiveActivities] = useState<LiveActivity[]>([])
  // Map agentId → timestamp ms de la derniere activite WS observee.
  // Sert a derive 'active'/'inactive' pour la sidebar (au-dela de TTL = inactive)
  // ET a auto-selectionner l'agent le plus actif au boot.
  const [lastActivityByAgent, setLastActivityByAgent] = useState<Record<string, number>>({})
  // Etat d'activation explicite des agents (toggle "Activer cet agent" du web).
  // Source de verite : POST /api/desktop/agents-activation depuis le frontend.
  // Receved via WS event {type:'agents_activation', active:{agent2,agent3}}
  // OU initial fetch sur GET /api/desktop/agents-activation au boot.
  const [activatedAgents, setActivatedAgents] = useState<Record<string, boolean>>({})
  // Tick toutes les 5s pour faire vieillir les statuts active → inactive
  const [, setNowTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setNowTick(t => t + 1), 5000)
    return () => clearInterval(id)
  }, [])

  const pushActivity = useCallback((activity: Omit<LiveActivity, 'since'>) => {
    setLiveActivities(prev => {
      const next = prev.filter(a => a.agentId !== activity.agentId)
      next.push({ ...activity, since: Date.now() })
      return next.slice(-5)
    })
    // Track activity per agent → drives 'active' status in sidebar
    setLastActivityByAgent(prev => ({ ...prev, [activity.agentId]: Date.now() }))
  }, [])

  // AGENTS derive : status calcule a partir de DEUX signaux
  //  1. activatedAgents (source de verite : toggle "Activer cet agent" du web)
  //  2. lastActivityByAgent (recent WS message → agent en train d'agir)
  // Un agent est 'active' s'il est ACTIVE dans le web OU s'il a recemment agi.
  // agent4 est toujours 'locked' (Super Agent — bientot disponible).
  const AGENTS: AgentInfo[] = AGENTS_BASE.map(base => {
    if (base.id === 'agent4') {
      return { ...base, status: 'locked', unread: 0 }
    }
    const explicitlyActivated = activatedAgents[base.id] === true
    const last = lastActivityByAgent[base.id]
    const recentlyActive = last !== undefined && (Date.now() - last) < ACTIVITY_TTL_MS
    const isActive = explicitlyActivated || recentlyActive
    return {
      ...base,
      status: isActive ? 'active' : 'inactive',
      unread: 0,
    }
  })

  // Sprint 2.7 — Stats HUD : compteurs + historiques pour sparklines
  const [stats, setStats] = useState<StatsHUDData>({
    reqPerMin: 0,
    reqHistory: [],
    latencyMs: 0,
    latencyHistory: [],
    tokens: 0,
    tokensHistory: [],
    actions: 0,
    actionsHistory: [],
  })
  // Compteur de requetes (incremente a chaque WS message), reset toutes les 60s
  const reqCountRef = useRef(0)
  useEffect(() => {
    const id = setInterval(() => {
      setStats(prev => {
        const reqMin = reqCountRef.current
        reqCountRef.current = 0
        return {
          ...prev,
          reqPerMin: reqMin,
          reqHistory: pushHist(prev.reqHistory, reqMin),
          latencyHistory: pushHist(prev.latencyHistory, prev.latencyMs),
          tokensHistory: pushHist(prev.tokensHistory, prev.tokens),
          actionsHistory: pushHist(prev.actionsHistory, prev.actions),
        }
      })
    }, 1000) // 1 sample / seconde
    return () => clearInterval(id)
  }, [])

  // Phase 2b — Onboarding OpenClaw au 1er lancement.
  // null = verification en cours, false = afficher wizard, true = passer au login.
  // On verifie le flag ~/.sylea-agent/onboarded.json via la commande Rust
  // `is_onboarded`. Si Tauri n'est pas disponible (dev web), on considere
  // l'onboarding comme deja fait pour ne pas bloquer le developpement.
  const [isOnboarded, setIsOnboarded] = useState<boolean | null>(null)

  useEffect(() => {
    (async () => {
      try {
        const done = await invoke<boolean>('is_onboarded')
        setIsOnboarded(done)
      } catch {
        // Tauri indisponible (mode dev hors-Tauri) → ne pas bloquer
        setIsOnboarded(true)
      }
    })()
  }, [])

  const [token, setToken] = useState<string | null>(localStorage.getItem('sylea_desktop_token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  // Plan de l'utilisateur — null = pas encore chargé, 'free' = bloqué, autre = OK
  const [userPlan, setUserPlan] = useState<string | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [wsConnected, setWsConnected] = useState(false)
  // Agent selectionne. null = "auto" : suit l'agent le plus recemment actif.
  // Si l'utilisateur clique sur un agent dans la sidebar, on bascule en mode
  // manuel (pinned) pour ne plus changer automatiquement.
  const [selectedAgent, setSelectedAgentRaw] = useState<string>('agent3')
  const [agentPinned, setAgentPinned] = useState(false)
  const setSelectedAgent = useCallback((id: string) => {
    setSelectedAgentRaw(id)
    setAgentPinned(true)
  }, [])
  // Auto-suit l'agent le plus actif tant qu'aucun pin manuel
  useEffect(() => {
    if (agentPinned) return
    const entries = Object.entries(lastActivityByAgent)
    if (entries.length === 0) return
    const [latestId] = entries.sort((a, b) => b[1] - a[1])[0]
    if (latestId && latestId !== selectedAgent) {
      setSelectedAgentRaw(latestId)
    }
  }, [lastActivityByAgent, agentPinned, selectedAgent])
  const [steps, setSteps] = useState<ActionStep[]>([])
  const [plan, setPlan] = useState<Array<{ step: string; status: 'pending' | 'done' | 'running'; agent?: string }>>([])
  const [openclawConnected, setOpenclawConnected] = useState(false)
  // Agent 3 streaming log (like Claude Code)
  const [agent3Logs, setAgent3Logs] = useState<Array<{ text: string; type: string; time: string }>>([])
  const [agent3StreamSteps, setAgent3StreamSteps] = useState<Array<{ id: string; label: string; status: string; detail: string }>>([])
  const agent3LogEndRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const stepsEndRef = useRef<HTMLDivElement>(null)

  // Sprint 1 — Pill compact mode + notifs pause + drag-drop
  const [pillMode, setPillMode] = useState(false)
  const [notifsPaused, setNotifsPaused] = useState(false)
  const notifsPausedRef = useRef(false)
  useEffect(() => { notifsPausedRef.current = notifsPaused }, [notifsPaused])

  const onDropFiles = useCallback(async (files: DroppedFile[]) => {
    // Inline addStep (la fonction `addStep` est definie plus bas)
    const append = (action: string, detail: string, status: ActionStep['status']) => {
      const id = Math.random().toString(36).slice(2, 9)
      setSteps(prev => [...prev, {
        id, action, status, detail,
        time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
      }])
    }
    append('FILE_DROP', `${files.length} fichier(s) dropped depuis l'OS`, 'running')
    for (const f of files) {
      append('FILE_DROP', `📄 ${f.name} (${(f.size/1024).toFixed(1)} KB)`, 'done')
    }
  }, [])
  const { hovering: dragHover } = useDragDrop(onDropFiles)

  const togglePill = useCallback(async () => {
    const next = !pillMode
    try { await invoke('toggle_pill_mode', { pill: next }) } catch {}
    setPillMode(next)
  }, [pillMode])

  useEffect(() => {
    let unsub: (() => void) | undefined
    listen<boolean>('tray:notifs', (evt) => {
      setNotifsPaused(!evt.payload)
    }).then(fn => { unsub = fn }).catch(() => {})
    return () => { try { unsub?.() } catch {} }
  }, [])

  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps])

  // Login — passe par apiFetch pour avoir credentials:'include' + le cookie
  // CSRF auto-fetché si nécessaire (le backend l'exige sur tous les POST
  // depuis le commit b2fe000 "sécurité niveau pro").
  const handleLogin = async () => {
    setError('')
    try {
      const res = await apiFetch(API_BASE, '/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      }, { withAuth: false })  // pas de Bearer pour login (on l'a pas encore)
      const data = await res.json()
      if (data.access_token) {
        setToken(data.access_token)
        localStorage.setItem('sylea_desktop_token', data.access_token)
      } else {
        setError(data.detail || 'Identifiants incorrects')
      }
    } catch (e) {
      setError(`Serveur inaccessible (${API_BASE}) : ${e instanceof Error ? e.message : ''}`)
    }
  }

  // Listener deep-link OAuth — RESERVE pour Apple Sign-In (et tout flow
  // OAuth qui passerait par le navigateur systeme en fallback). Google
  // utilise maintenant la popup Tauri native (cf. bouton onClick plus bas),
  // PAS le deep-link, donc ce listener ne fire JAMAIS pour Google en flow
  // normal — il reste juste pour Apple qui dépend du navigateur (Apple
  // n'autorise pas l'OAuth dans une WebView embarquee).
  //
  // Securite : on verifie le nonce contre celui stocke en localStorage avant
  // de setToken — empeche un attaquant qui devine l'URL deep-link de forger
  // un login.
  //
  // Tolerance UX :
  //   - Pas de nonce stocke → silence (peut etre un attaquant ou un test
  //     externe ; rien de bon a montrer a l'user, on ignore juste).
  //   - Nonce mismatch → erreur friendly (sans le mot "forge" qui fait peur).
  //   - Succes → setToken + suppression du nonce (idempotent : si l'event
  //     fire 2x, le second find expectedNonce='' et silence proprement).
  useEffect(() => {
    let unsub: (() => void) | undefined

    // Handler factorise (memes regles pour event recu live et URL "pending"
    // recuperee au boot via take_pending_deep_link).
    const handleDeepLinkUrl = (urlStr: string) => {
      try {
        console.log('[deep-link] received in JS:', urlStr.substring(0, 60) + '...')
        if (!urlStr.startsWith('sylea://auth/callback')) {
          console.log('[deep-link] ignored (not /auth/callback path)')
          return
        }
        // Parser l'URL — URL ne sait pas parser sylea:// directement, on
        // convertit en http:// le temps de l'analyse.
        const httpUrl = urlStr.replace(/^sylea:\/\//, 'http://')
        const parsed = new URL(httpUrl)
        const token = parsed.searchParams.get('token') || ''
        const nonce = parsed.searchParams.get('nonce') || ''
        console.log('[deep-link] token present:', !!token, 'nonce present:', !!nonce)
        if (!token) {
          // Cas rare : sylea://auth/callback sans token. On ignore.
          console.warn('[deep-link] no token in payload, ignoring')
          return
        }
        // Verifie le nonce contre celui stocke quand l'user a clique sur
        // "Continuer avec Google".
        const expectedNonce = (() => {
          try { return localStorage.getItem('sylea_desktop_oauth_nonce') || '' }
          catch { return '' }
        })()
        if (!expectedNonce) {
          // Pas de flow OAuth en cours → on ignore silencieusement.
          // Ca evite de scarer l'user avec un message d'erreur si :
          //   - Un test envoie un deep-link bidon
          //   - Un attaquant forge un deep-link
          //   - Le user lance l'app directement par un lien sylea:// stale
          console.warn('[deep-link] no OAuth in progress, ignoring (no nonce stored)')
          return
        }
        if (expectedNonce !== nonce) {
          // Nonce stocke mais ne matche pas — possiblement double-click sur
          // le bouton (le 2e click a regenere un nouveau nonce, et la 1ere
          // reponse OAuth arrive avec l'ancien). On affiche un message friendly.
          console.warn('[deep-link] nonce mismatch (expected vs received differ)')
          setError('Connexion Google échouée. Réessaie en cliquant sur le bouton.')
          // On nettoie pour permettre un retry propre
          try { localStorage.removeItem('sylea_desktop_oauth_nonce') } catch {}
          return
        }
        // OK — on consume le nonce et on setToken
        console.log('[deep-link] login OK, setting token')
        try { localStorage.removeItem('sylea_desktop_oauth_nonce') } catch {}
        localStorage.setItem('sylea_desktop_token', token)
        setToken(token)
        setError('')
      } catch (e) {
        console.error('[deep-link] parse error:', e)
        setError(`Erreur deep-link : ${e instanceof Error ? e.message : ''}`)
      }
    }

    // Listener temps-reel : deep-link recu pendant que l'app tourne
    listen<string>('deep-link:received', (event) => {
      handleDeepLinkUrl(event.payload || '')
    }).then((fn) => { unsub = fn }).catch(() => {})

    // Cold-start : si l'app vient d'etre lancee VIA un sylea://, le handler
    // Rust a fire avant que ce listener soit attache. On rattrape via la
    // commande Tauri take_pending_deep_link() qui consomme l'URL cachee.
    invoke<string | null>('take_pending_deep_link')
      .then((url) => {
        if (url) {
          console.log('[deep-link] cold-start URL detected, processing')
          handleDeepLinkUrl(url)
        }
      })
      .catch(() => {})

    return () => { try { unsub?.() } catch {} }
  }, [])

  // Plan check — charge le plan utilisateur apres login.
  // Le desktop Syléa Agent est reserve aux abonnes payants (Avance / Pro / Team).
  // Les comptes "free" voient un ecran de proposition d'upgrade au lieu de l'app.
  useEffect(() => {
    if (!token) {
      setUserPlan(null)
      return
    }
    setPlanLoading(true)
    apiFetch(API_BASE, '/api/agent3/plan')
      .then(r => r.json())
      .then(data => {
        // Le backend renvoie {"plan": {"name": "free"|"advanced"|"pro"|"team", ...}, "usage": {...}}
        // (cf. api/routers/agent3_openclaw.py @router.get("/plan"))
        const planObj = data?.plan || data  // fallback si format change
        const name = (planObj?.name || planObj?.plan_name || 'free').toLowerCase()
        setUserPlan(name)
      })
      .catch(() => {
        // En cas d'erreur, on suppose free par defaut (securite : ne pas
        // ouvrir le desktop si on n'arrive pas a confirmer le tier).
        setUserPlan('free')
      })
      .finally(() => setPlanLoading(false))
  }, [token])

  // Request notification permission on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // Reminder checker — polls every 30s and fires desktop notifications
  useEffect(() => {
    if (!token) return
    // (headers Bearer + CSRF gérés automatiquement par apiFetch)
    const firedReminders = new Set<number>()

    const checkReminders = async () => {
      try {
        const res = await apiFetch(API_BASE, '/api/agent2/reminders')
        const reminders = await res.json()
        const now = new Date()
        for (const r of reminders) {
          if (firedReminders.has(r.id)) continue
          const reminderTime = new Date(`${r.date}T${r.time}`)
          if (Math.abs(now.getTime() - reminderTime.getTime()) < 60000 && !r.completed) {
            firedReminders.add(r.id)
            addStep('REMINDER', `⏰ RAPPEL : ${r.message}`, 'done')
            if (!notifsPausedRef.current && 'Notification' in window && Notification.permission === 'granted') {
              new Notification('⏰ Sylea Agent — Rappel', { body: r.message })
            }
            // Mark as completed (POST → apiFetch ajoute X-CSRF-Token auto)
            apiFetch(API_BASE, `/api/agent2/reminders/${r.id}/complete`, {
              method: 'POST',
            }).catch(() => {})
          }
        }
      } catch { /* silent */ }
    }

    const interval = setInterval(checkReminders, 30000)
    checkReminders() // Check immediately
    return () => clearInterval(interval)
  }, [token])

  // Fetch initial agents activation state au boot/login (snapshot)
  useEffect(() => {
    if (!token) return
    apiFetch(API_BASE, '/api/desktop/agents-activation')
      .then(r => r.json())
      .then(data => {
        if (data?.active) setActivatedAgents(data.active)
      })
      .catch(() => { /* silent */ })
  }, [token])

  // OpenClaw Gateway health check — polls every 45s
  useEffect(() => {
    if (!token) return
    const checkOpenClaw = async () => {
      try {
        const res = await apiFetch(API_BASE, '/api/agent3/status')
        const data = await res.json()
        setOpenclawConnected(data.openclaw_connected === true)
      } catch {
        setOpenclawConnected(false)
      }
    }
    checkOpenClaw()
    const interval = setInterval(checkOpenClaw, 45000)
    return () => clearInterval(interval)
  }, [token])

  // WebSocket
  useEffect(() => {
    if (!token) return
    let isCleaningUp = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let reconnectAttempts = 0
    let hasConnected = false

    const connect = () => {
      if (isCleaningUp) return
      // WS URL derive de API_BASE : http:// -> ws://, https:// -> wss://
      const wsBase = API_BASE.replace(/^http/, 'ws')
      const ws = new WebSocket(`${wsBase}/ws/agent?token=${token}`)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        reconnectAttempts = 0
        if (!hasConnected) {
          hasConnected = true
          addStep('info', 'Connecte au serveur Sylea.AI', 'done')
        }
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 30000)
        ws.addEventListener('close', () => clearInterval(ping))
      }

      ws.onmessage = async (event) => {
        if (event.data === 'pong') return
        // Stats: count incoming WS messages (Sprint 2.7)
        reqCountRef.current += 1
        try {
          const data = JSON.parse(event.data)
          const sourceAgent = data.agent || 'agent2'  // Default to agent2 for backward compat
          const agentLabel = sourceAgent === 'agent3' ? '[Agent 3]' : '[Agent 2]'

          // Handle "connected" welcome event from backend (api/main.py:182)
          // C'etait la cause des #004/#006/.../"[Agent 2] Desktop connecte"
          // qui restaient bloques en RUNNING : on l'ignore desormais (deja
          // affiche par addStep('info', 'Connecte au serveur Sylea.AI') dans
          // ws.onopen avec status='done').
          if (data.type === 'connected') {
            return
          }

          // Etat d'activation des agents change cote web (toggle "Activer
          // cet agent"). Met a jour la sidebar + bascule selectedAgent vers
          // le 1er agent active si l'utilisateur n'a pas pinned manuellement.
          // Ecoute active — declenche depuis le web (bouton sur Agent 2)
          if (data.type === 'start_lecture') {
            setEcouteActiveOpen(true)
            addStep('LECTURE', `[Agent 2] Ecoute active demandee depuis le web`, 'done', 'agent2')
            return
          }

          if (data.type === 'agents_activation' && data.active) {
            const next = data.active as Record<string, boolean>
            setActivatedAgents(next)
            // Auto-select le 1er agent active (priorite agent3 > agent2 > agent1)
            if (!agentPinned) {
              if (next.agent3)      setSelectedAgentRaw('agent3')
              else if (next.agent2) setSelectedAgentRaw('agent2')
              else if (next.agent1) setSelectedAgentRaw('agent1')
            }
            // Step info pour traçabilité
            const activeList = Object.entries(next).filter(([, v]) => v).map(([k]) => k.replace('agent', 'Sylea '))
            addStep('info', `Etat agents synchronise depuis le web : ${activeList.join(', ') || 'aucun'} actif`, 'done')
            return
          }

          // Sprint 2.6 — Push activite dans le live feed
          const agentInfo = AGENTS.find(a => a.id === sourceAgent)
          if (agentInfo && (data.message || data.type === 'agent3_log')) {
            const verb =
              data.type === 'agent3_log' && data.log_type === 'tool'    ? 'execute'   :
              data.type === 'agent3_log' && data.log_type === 'success' ? 'a termine' :
              data.type === 'agent3_steps'                              ? 'planifie'  :
              data.type === 'agent3_step_update'                        ? 'avance'    :
                                                                          'ecrit'
            pushActivity({
              agentId: sourceAgent,
              agentName: agentInfo.name,
              agentColor: agentInfo.color,
              verb,
              detail: (data.message || data.text || '').slice(0, 60),
            })
          }

          // Sprint 2.7 — Estimation tokens (heuristique : 1 token ~ 4 chars)
          if (data.message) {
            setStats(prev => ({
              ...prev,
              tokens: prev.tokens + Math.ceil((data.message?.length || 0) / 4),
            }))
          }
          if (data.text) {
            setStats(prev => ({
              ...prev,
              tokens: prev.tokens + Math.ceil((data.text?.length || 0) / 4),
            }))
          }

          // Handle Gmail open command — open Gmail compose in browser
          if (data.type === 'open_gmail' && data.url) {
            addStep('EMAIL', `${agentLabel} Ouverture Gmail → ${data.to}`, 'running', sourceAgent)
            window.open(data.url, '_blank')
            addStep('EMAIL', `${agentLabel} Gmail ouvert — mail pret pour ${data.to} (${data.subject})`, 'done', sourceAgent)
            return
          }

          // Handle file_read_request from server
          if (data.type === 'file_read_request') {
            try {
              const { invoke } = await import('@tauri-apps/api/core')
              const content = await invoke('read_file', { path: data.path })
              // Send content back to server (CSRF auto-géré par apiFetch)
              await apiFetch(API_BASE, '/api/agent3/file-response', {
                method: 'POST',
                body: JSON.stringify({ request_id: data.request_id, content, path: data.path }),
              })
            } catch (err) {
              console.error('File read error:', err)
            }
            return
          }

          // Handle Agent 3 streaming events
          if (data.type === 'agent3_steps') {
            setAgent3StreamSteps(data.steps || [])
            setPlan((data.steps || []).map((s: any) => ({
              step: s.label, status: s.status, agent: 'agent3',
            })))
            return
          }
          if (data.type === 'agent3_step_update') {
            setAgent3StreamSteps(prev => prev.map(s => s.id === data.step_id ? { ...s, status: data.status } : s))
            setPlan(prev => prev.map((p, i) => {
              const matchStep = agent3StreamSteps[i]
              if (matchStep?.id === data.step_id) return { ...p, status: data.status }
              return p
            }))
            return
          }
          if (data.type === 'agent3_log') {
            const now = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            setAgent3Logs(prev => [...prev, { text: data.text, type: data.log_type || 'info', time: now }])
            addStep(data.log_type === 'tool' ? 'SEARCH' : 'info', `[Agent 3] ${data.text}`, data.log_type === 'success' ? 'done' : 'running', 'agent3')
            return
          }

          if (data.message) {
            addStep(data.type || 'action', `${agentLabel} ${data.message}`, 'running', sourceAgent)
          }
          if (data.actions?.length > 0) {
            // Build plan from actions
            setPlan(data.actions.map((a: any) => ({
              step: `${a.type}: ${a.data?.title || a.data?.to || a.data?.label || a.data?.message || a.data?.query || ''}`,
              status: 'pending' as const,
              agent: sourceAgent,
            })))
            data.actions.forEach((action: any, idx: number) => {
              setTimeout(() => handleAction(action, idx, sourceAgent), idx * 2000)
            })
          }

          // Desktop notification for Agent 3 actions
          if (sourceAgent === 'agent3' && data.message && 'Notification' in window && Notification.permission === 'granted') {
            new Notification('Sylea Agent 3 — Action', { body: data.message.slice(0, 100) })
          }
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        setWsConnected(false)
        if (isCleaningUp) return
        reconnectAttempts++
        const delay = Math.min(5000 * Math.pow(2, reconnectAttempts - 1), 60000)
        reconnectTimer = setTimeout(connect, delay)
      }

      ws.onerror = () => setWsConnected(false)
    }

    connect()
    return () => {
      isCleaningUp = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [token])

  const addStep = (action: string, detail: string, status: ActionStep['status'], agent?: string) => {
    setSteps(prev => [...prev, {
      id: `${Date.now()}-${Math.random()}`,
      action, detail, status, agent,
      time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    }])
    // Sprint 2.7 — Counter actions terminees pour le HUD
    if (status === 'done') {
      setStats(prev => ({ ...prev, actions: prev.actions + 1 }))
    }
  }

  const updatePlan = (idx: number, status: 'done' | 'running' | 'pending') => {
    setPlan(prev => prev.map((p, i) => i === idx ? { ...p, status } : p))
  }

  const handleAction = async (action: any, planIdx: number, sourceAgent = 'agent2') => {
    updatePlan(planIdx, 'running')
    const tag = sourceAgent === 'agent3' ? '[Agent 3] ' : ''
    switch (action.type) {
      case 'EMAIL': {
        addStep('EMAIL', `${tag}Preparation mail pour ${action.data.to}...`, 'running', sourceAgent)
        try {
          const res = await apiFetch(API_BASE, '/api/agent2/send-email', {
            method: 'POST',
            body: JSON.stringify(action.data),
          })
          const result = await res.json()
          if (result.gmail_url) {
            window.open(result.gmail_url, '_blank')
            addStep('EMAIL', `${tag}Gmail ouvert — mail pret pour ${action.data.to}`, 'done', sourceAgent)
          } else {
            addStep('EMAIL', `${tag}Erreur preparation mail`, 'error', sourceAgent)
          }
          updatePlan(planIdx, 'done')
        } catch {
          addStep('EMAIL', `${tag}Erreur ouverture Gmail`, 'error', sourceAgent)
        }
        break
      }
      case 'TEXT': {
        addStep('TEXT', `${tag}Generation: ${action.data.title}...`, 'running', sourceAgent)
        const content = (action.data.content || '').replace(/\n/g, '<br>')
        const agentCredit = sourceAgent === 'agent3' ? 'Sylea Agent 3 (OpenClaw)' : 'Sylea Agent'
        const htmlDoc = `<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>${action.data.title || 'Document'}</title>
<style>body{font-family:'Segoe UI',Tahoma,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#1a1a2e;line-height:1.6}h1{color:#16213e;border-bottom:2px solid #0f3460;padding-bottom:10px}</style>
</head><body>
<h1>${action.data.title || 'Document'}</h1>
<div>${content}</div>
<hr style="margin-top:40px;border:1px solid #eee">
<p style="color:#999;font-size:12px;">Genere par ${agentCredit} — ${new Date().toLocaleDateString('fr-FR')}</p>
</body></html>`
        const blob = new Blob([htmlDoc], { type: 'text/html;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${action.data.title || 'document'}.html`; a.click()
        URL.revokeObjectURL(url)
        addStep('TEXT', `${tag}Document telecharge: ${action.data.title}.html`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'LINK':
        addStep('LINK', `${tag}Ouverture: ${action.data.label || action.data.url}`, 'running', sourceAgent)
        window.open(action.data.url, '_blank')
        addStep('LINK', `${tag}Lien ouvert`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      case 'COPY':
        addStep('COPY', `${tag}Copie presse-papier...`, 'running', sourceAgent)
        try {
          await navigator.clipboard.writeText(action.data.text)
          addStep('COPY', `${tag}Copie dans le presse-papier`, 'done', sourceAgent)
          updatePlan(planIdx, 'done')
        } catch {
          addStep('COPY', `${tag}Erreur copie`, 'error', sourceAgent)
        }
        break
      case 'REMINDER':
        addStep('REMINDER', `${tag}Creation rappel: ${action.data.message} a ${action.data.time}...`, 'running', sourceAgent)
        try {
          await apiFetch(API_BASE, '/api/agent2/create-reminder', {
            method: 'POST',
            body: JSON.stringify({ time: action.data.time, date: action.data.date, message: action.data.message }),
          })
          addStep('REMINDER', `${tag}Rappel cree: ${action.data.message} — ${action.data.date} a ${action.data.time}`, 'done', sourceAgent)
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(`${sourceAgent === 'agent3' ? 'Sylea Agent 3' : 'Sylea Agent'} — Rappel cree`, {
              body: `${action.data.message}\n${action.data.date} a ${action.data.time}`,
            })
          }
        } catch {
          addStep('REMINDER', `${tag}Erreur creation rappel`, 'error', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      // ── Agent 3 specific action types ──
      case 'SEARCH': {
        const query = action.data?.query || action.data?.title || 'Recherche'
        addStep('SEARCH', `${tag}Recherche: ${query}...`, 'running', sourceAgent)
        // Search results are displayed as an HTML report
        const searchContent = (action.data?.results || action.data?.content || query).replace(/\n/g, '<br>')
        const searchHtml = `<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Recherche — ${query}</title>
<style>body{font-family:'Segoe UI',Tahoma,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1a1a2e;line-height:1.6}h1{color:#1e3a5f;border-bottom:2px solid #3b82f6;padding-bottom:10px}.source{color:#3b82f6;font-size:13px;margin:4px 0}</style>
</head><body>
<h1>Recherche : ${query}</h1>
<div>${searchContent}</div>
<hr style="margin-top:40px;border:1px solid #eee">
<p style="color:#999;font-size:12px;">Recherche par Sylea Agent 3 (OpenClaw) — ${new Date().toLocaleDateString('fr-FR')}</p>
</body></html>`
        const searchBlob = new Blob([searchHtml], { type: 'text/html;charset=utf-8' })
        const searchUrl = URL.createObjectURL(searchBlob)
        const searchLink = document.createElement('a')
        searchLink.href = searchUrl; searchLink.download = `recherche-${query.slice(0, 30).replace(/\s+/g, '-')}.html`; searchLink.click()
        URL.revokeObjectURL(searchUrl)
        addStep('SEARCH', `${tag}Recherche terminee: ${query}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'ANALYSIS': {
        const topic = action.data?.title || action.data?.topic || 'Analyse'
        addStep('ANALYSIS', `${tag}Analyse: ${topic}...`, 'running', sourceAgent)
        const analysisContent = (action.data?.content || action.data?.results || topic).replace(/\n/g, '<br>')
        const analysisHtml = `<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Analyse — ${topic}</title>
<style>body{font-family:'Segoe UI',Tahoma,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1a1a2e;line-height:1.6}h1{color:#1e3a5f;border-bottom:3px solid linear-gradient(90deg,#3b82f6,#f59e0b);padding-bottom:10px}h2{color:#374151;border-left:3px solid #3b82f6;padding-left:10px}.highlight{background:rgba(59,130,246,0.05);padding:12px;border-radius:8px;border-left:3px solid #f59e0b}</style>
</head><body>
<h1>Analyse : ${topic}</h1>
<div>${analysisContent}</div>
<hr style="margin-top:40px;border:1px solid #eee">
<p style="color:#999;font-size:12px;">Analyse par Sylea Agent 3 (OpenClaw) — ${new Date().toLocaleDateString('fr-FR')}</p>
</body></html>`
        const analysisBlob = new Blob([analysisHtml], { type: 'text/html;charset=utf-8' })
        const analysisUrl = URL.createObjectURL(analysisBlob)
        const analysisLink = document.createElement('a')
        analysisLink.href = analysisUrl; analysisLink.download = `analyse-${topic.slice(0, 30).replace(/\s+/g, '-')}.html`; analysisLink.click()
        URL.revokeObjectURL(analysisUrl)
        addStep('ANALYSIS', `${tag}Analyse terminee: ${topic}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      // ── File operations via Tauri commands ──
      case 'FILE_CREATE':
      case 'FILE_WRITE': {
        const filename = action.data?.filename || action.data?.path || 'fichier.txt'
        const fileContent = action.data?.content || ''
        addStep('FILE', `${tag}Creation fichier: ${filename}...`, 'running', sourceAgent)
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          // Determiner le dossier de destination
          let targetDir = ''
          try {
            targetDir = await invoke('get_documents_dir') as string
          } catch {
            targetDir = ''
          }
          const targetPath = targetDir ? `${targetDir}/Sylea/${filename}` : filename
          // Creer le dossier Sylea dans Documents
          try { await invoke('create_directory', { path: `${targetDir}/Sylea` }) } catch {}
          await invoke('write_file', { path: targetPath, content: fileContent })
          addStep('FILE', `${tag}Fichier cree: ${targetPath}`, 'done', sourceAgent)
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Sylea Agent 3 — Fichier cree', { body: targetPath })
          }
        } catch (err: any) {
          addStep('FILE', `${tag}Erreur: ${err?.message || err}`, 'error', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'FILE_READ': {
        const readPath = action.data?.path || ''
        addStep('FILE', `${tag}Lecture fichier: ${readPath}...`, 'running', sourceAgent)
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          const content = await invoke('read_file', { path: readPath }) as string
          addStep('FILE', `${tag}Fichier lu (${content.length} caracteres)`, 'done', sourceAgent)
          // Envoyer le contenu au backend pour que l'agent l'analyse
          try {
            await apiFetch(API_BASE, '/api/agent3/chat', {
              method: 'POST',
              body: JSON.stringify({
                messages: [{ role: 'user', content: `Voici le contenu du fichier "${readPath}":\n\n${content.substring(0, 10000)}` }],
              }),
            })
          } catch {}
        } catch (err: any) {
          addStep('FILE', `${tag}Erreur lecture: ${err?.message || err}`, 'error', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'FILE_DELETE': {
        const deletePath = action.data?.path || ''
        addStep('FILE', `${tag}Suppression: ${deletePath}...`, 'running', sourceAgent)
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          await invoke('delete_file', { path: deletePath })
          addStep('FILE', `${tag}Fichier supprime: ${deletePath}`, 'done', sourceAgent)
        } catch (err: any) {
          addStep('FILE', `${tag}Erreur suppression: ${err?.message || err}`, 'error', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'FILE_DOWNLOAD': {
        // Telecharger un fichier depuis le backend vers le PC local
        const downloadUrl = action.data?.url || ''
        const downloadName = action.data?.filename || 'download'
        addStep('FILE', `${tag}Telechargement: ${downloadName}...`, 'running', sourceAgent)
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          // GET binaire : apiFetch ajoute Authorization Bearer + credentials:include.
          // Le Content-Type:application/json sur le request n'a pas d'effet en GET sans body.
          const response = await apiFetch(API_BASE, downloadUrl)
          const blob = await response.blob()
          const buffer = await blob.arrayBuffer()
          const bytes = new Uint8Array(buffer)
          // Convertir en base64
          let binary = ''
          for (let i = 0; i < bytes.length; i++) { binary += String.fromCharCode(bytes[i]) }
          const b64 = btoa(binary)
          let targetDir = ''
          try { targetDir = await invoke('get_downloads_dir') as string } catch { targetDir = '' }
          const targetPath = targetDir ? `${targetDir}/${downloadName}` : downloadName
          await invoke('write_file_binary', { path: targetPath, dataBase64: b64 })
          addStep('FILE', `${tag}Telecharge: ${targetPath}`, 'done', sourceAgent)
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Sylea Agent 3 — Fichier telecharge', { body: targetPath })
          }
        } catch (err: any) {
          // Fallback: download via browser
          const a = document.createElement('a')
          a.href = `${API_BASE}${downloadUrl}`; a.download = downloadName; a.click()
          addStep('FILE', `${tag}Telecharge via navigateur: ${downloadName}`, 'done', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'CRON': {
        addStep('CRON', `${tag}Tache planifiee: ${action.data?.label || 'Tache'}`, 'running', sourceAgent)
        addStep('CRON', `${tag}${action.data?.label} — ${action.data?.cron_expr || 'programmee'}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'MEMORY': {
        addStep('MEMORY', `${tag}Memorise: ${action.data?.key}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'PDF': {
        const pdfName = action.data?.pdf_filename || action.data?.title || 'rapport.pdf'
        const pdfUrl = action.data?.pdf_url || `/api/agent3/pdf/${pdfName}`
        addStep('PDF', `${tag}PDF genere: ${action.data?.title || pdfName}`, 'running', sourceAgent)
        // Auto-download le PDF sur le PC
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          // GET binaire PDF (Bearer + credentials gérés par apiFetch)
          const response = await apiFetch(API_BASE, pdfUrl)
          if (response.ok) {
            const blob = await response.blob()
            const buffer = await blob.arrayBuffer()
            const bytes = new Uint8Array(buffer)
            let binary = ''
            for (let i = 0; i < bytes.length; i++) { binary += String.fromCharCode(bytes[i]) }
            const b64 = btoa(binary)
            let targetDir = ''
            try { targetDir = await invoke('get_downloads_dir') as string } catch { targetDir = '' }
            const targetPath = targetDir ? `${targetDir}/${pdfName}` : pdfName
            await invoke('write_file_binary', { path: targetPath, dataBase64: b64 })
            addStep('PDF', `${tag}PDF sauvegarde: ${targetPath}`, 'done', sourceAgent)
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('Sylea Agent 3 — PDF pret', { body: targetPath })
            }
          } else {
            addStep('PDF', `${tag}PDF disponible en ligne`, 'done', sourceAgent)
          }
        } catch {
          // Fallback browser download
          window.open(`${API_BASE}${pdfUrl}`, '_blank')
          addStep('PDF', `${tag}PDF ouvert dans le navigateur`, 'done', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'CODE': {
        const codeName = action.data?.filename || `script.${action.data?.language || 'txt'}`
        const codeContent = action.data?.content || ''
        addStep('CODE', `${tag}Code genere: ${codeName}`, 'running', sourceAgent)
        try {
          const { invoke } = await import('@tauri-apps/api/core')
          let targetDir = ''
          try { targetDir = await invoke('get_documents_dir') as string } catch { targetDir = '' }
          const targetPath = targetDir ? `${targetDir}/Sylea/scripts/${codeName}` : codeName
          try { await invoke('create_directory', { path: `${targetDir}/Sylea/scripts` }) } catch {}
          await invoke('write_file', { path: targetPath, content: codeContent })
          addStep('CODE', `${tag}Script sauvegarde: ${targetPath}`, 'done', sourceAgent)
        } catch {
          // Fallback: copy to clipboard
          try { await navigator.clipboard.writeText(codeContent) } catch {}
          addStep('CODE', `${tag}Code copie dans le presse-papier`, 'done', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'EXEC_RESULT': {
        const cmd = action.data?.command || 'commande'
        const exitCode = action.data?.exit_code
        addStep('EXEC', `${tag}Execution: ${cmd}`, 'running', sourceAgent)
        if (exitCode === 0) {
          addStep('EXEC', `${tag}Commande reussie: ${cmd}`, 'done', sourceAgent)
        } else {
          addStep('EXEC', `${tag}Commande terminee (code ${exitCode}): ${cmd}`, exitCode === 0 ? 'done' : 'error', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'SCREENSHOT': {
        addStep('SCREENSHOT', `${tag}Capture: ${action.data?.title || action.data?.url || 'page web'}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'IMAGE': {
        addStep('IMAGE', `${tag}Image: ${action.data?.title || action.data?.prompt?.substring(0, 50) || 'generee'}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'CANVAS': {
        addStep('CANVAS', `${tag}Visualisation: ${action.data?.title || 'Canvas'}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'SPAWN_AGENT': {
        const agentLabel = action.data?.label || action.data?.agent_id || 'sous-agent'
        addStep('AGENT', `${tag}Sous-agent lance: ${agentLabel}`, 'running', sourceAgent)
        if (action.data?.spawn_success) {
          addStep('AGENT', `${tag}Sous-agent ${agentLabel} actif`, 'done', sourceAgent)
        } else {
          addStep('AGENT', `${tag}Sous-agent ${agentLabel} en attente`, 'done', sourceAgent)
        }
        updatePlan(planIdx, 'done')
        break
      }
      case 'WEBPAGE': {
        addStep('WEBPAGE', `${tag}Page: ${action.data?.title || action.data?.url || 'web'}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      case 'X_SEARCH': {
        const xPosts = action.data?.posts?.length || 0
        addStep('X_SEARCH', `${tag}Recherche X/Twitter: ${action.data?.query || ''} (${xPosts} posts)`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
        break
      }
      default:
        addStep('ACTION', `${tag}${action.type}: ${JSON.stringify(action.data).substring(0, 100)}`, 'done', sourceAgent)
        updatePlan(planIdx, 'done')
    }
  }

  const handleLogout = () => {
    wsRef.current?.close()
    setToken(null)
    localStorage.removeItem('sylea_desktop_token')
    setSteps([])
    setPlan([])
    setWsConnected(false)
  }

  // ── SPLASH SCREEN (Sprint 2.1) ──
  // Affiche logo Sylea + particules + barre "INITIALIZING SYSTEM" pendant 1.4s.
  // Une seule fois au boot de l'app, avant tout le reste (incl. onboarding).
  // On rend la titlebar PAR-DESSUS le splash pour que les croix close/min
  // soient toujours accessibles (sinon impossible de fermer la fenetre frameless).
  if (!splashDone) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', height: '100vh',
        background: '#050810', overflow: 'hidden',
      }}>
        <DesktopTitlebar accent={SY.cyanSoft} />
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <SplashScreen onComplete={finishSplash} />
        </div>
      </div>
    )
  }

  // ── ONBOARDING OPENCLAW (Phase 2b) ──
  // Affichage bloquant au 1er lancement : wizard qui installe OpenClaw,
  // genere le token gateway et propose 5 skills ClawHub pre-coches.
  // NB : tous les ecrans en dehors du dashboard rendent DesktopTitlebar
  // explicitement (la fenetre est frameless `decorations: false`) — sinon
  // l'utilisateur n'a aucun moyen de fermer/reduire/maximiser la fenetre.
  if (isOnboarded === null) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <DesktopTitlebar accent={SY.cyanSoft} />
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 18,
        }}>
          <SyleaLogo size={48} animated />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
              background: SY.cyan,
              boxShadow: `0 0 10px ${SY.cyan}`,
              animation: 'sy-pulse 1.2s ease-in-out infinite',
            }} />
            <span style={{
              fontFamily: SY.mono, fontSize: 11, letterSpacing: '0.18em',
              color: SY.textMute, textTransform: 'uppercase',
            }}>
              Initialisation du systeme
            </span>
          </div>
        </div>
      </div>
    )
  }
  if (isOnboarded === false) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <DesktopTitlebar accent={SY.cyanSoft} />
        <div style={{ flex: 1, overflow: 'auto' }}>
          <OpenClawOnboarding onComplete={() => setIsOnboarded(true)} />
        </div>
      </div>
    )
  }

  // ── LOGIN ──
  // ─── Gate plan free ─────────────────────────────────────────────────────
  // Le desktop Syléa Agent est reserve aux abonnes payants. Un user free
  // qui se connecte voit un ecran "Upgrade" avec lien vers /quotas, et un
  // bouton pour se deconnecter.
  if (token && userPlan === 'free' && !planLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <DesktopTitlebar accent={SY.cyanSoft} />
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: '2rem',
          overflow: 'auto',
        }}>
        <SyleaWordmark logoSize={48} fontSize={20} gap={14} animated hover3d />
        <div style={{
          marginTop: 32,
          background: SY.surface,
          border: `1px solid ${SY.border}`,
          borderRadius: 10,
          padding: '32px 28px',
          maxWidth: 440, width: '100%',
          position: 'relative',
          backdropFilter: 'blur(8px)',
          boxShadow: `0 0 0 1px ${SY.border} inset, 0 8px 30px rgba(0,0,0,0.45)`,
          textAlign: 'center',
        }}>
          <CornerBrackets color={SY.cyan} />
          <div style={{
            fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.2em',
            color: SY.cyan, marginBottom: 18, textTransform: 'uppercase',
          }}>
            <span style={{ opacity: 0.6 }}>[</span> upgrade requis <span style={{ opacity: 0.6 }}>]</span>
          </div>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🔒</div>
          <h2 style={{
            fontSize: 18, fontWeight: 700, marginBottom: 14,
            color: SY.text, fontFamily: SY.mono, letterSpacing: '0.05em',
          }}>
            Syléa Desktop n'est pas inclus<br/>dans le plan Free
          </h2>
          <p style={{
            fontSize: 13, color: SY.textDim, lineHeight: 1.55,
            marginBottom: 22, fontFamily: SY.mono,
          }}>
            Le desktop est reserve aux abonnes <strong style={{ color: SY.cyan }}>Avancé</strong>.<br/>
            Mets à niveau ton compte pour debloquer :
          </p>
          <div style={{
            fontSize: 12, color: SY.text, fontFamily: SY.mono,
            background: 'rgba(0,200,255,0.04)',
            border: `1px solid rgba(0,200,255,0.15)`,
            borderRadius: 8, padding: '12px 14px',
            marginBottom: 22, textAlign: 'left', lineHeight: 1.7,
          }}>
            <div>✓ Agent Syléa 2 (assistant exécutant)</div>
            <div>✓ Skills OpenClaw (email, calendrier, notes…)</div>
            <div>✓ Plan "Que faire ?" quotidien IA</div>
            <div>✓ 30 actions/jour (vs 10 en Free)</div>
            <div>✓ Notifications & rappels intelligents</div>
          </div>
          <button
            onClick={() => invoke('open_url', { url: 'https://sylea.ai/quotas' }).catch(() => {})}
            style={{
              width: '100%', padding: '11px 14px', borderRadius: 8,
              background: `linear-gradient(135deg, ${SY.violet} 0%, ${SY.indigo} 40%, ${SY.blue} 75%, ${SY.cyan} 100%)`,
              color: '#fff',
              fontWeight: 700, fontSize: 13, letterSpacing: '0.12em',
              textTransform: 'uppercase',
              cursor: 'pointer',
              boxShadow: `0 0 0 1px rgba(0,200,255,0.3), 0 6px 20px rgba(0,200,255,0.18)`,
              fontFamily: SY.mono,
              border: 'none',
            }}
          >
            ▸ Passer à Sylea Avancé
          </button>
          <button
            onClick={() => {
              setToken(null)
              localStorage.removeItem('sylea_desktop_token')
              setUserPlan(null)
            }}
            style={{
              marginTop: 14, width: '100%', padding: '9px 14px', borderRadius: 8,
              background: 'transparent',
              border: `1px solid ${SY.border}`,
              color: SY.textDim,
              fontWeight: 500, fontSize: 12, letterSpacing: '0.1em',
              cursor: 'pointer',
              fontFamily: SY.mono,
            }}
          >
            Se déconnecter
          </button>
        </div>
        </div>
      </div>
    )
  }

  if (!token) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <DesktopTitlebar accent={SY.cyanSoft} />
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: '2rem',
          overflow: 'auto',
        }}>
        {/* Logo officiel + wordmark — 3D hover (Sprint 2.10) */}
        <SyleaWordmark logoSize={48} fontSize={20} gap={14} animated hover3d />

        {/* Sous-titre mono */}
        <div style={{
          marginTop: 10,
          fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.28em',
          color: SY.textDim, textTransform: 'uppercase',
        }}>
          <span style={{ color: SY.cyan }}>▸</span> Desktop runtime · v1.0
        </div>

        {/* Carte login */}
        <div style={{
          marginTop: 32,
          background: SY.surface,
          border: `1px solid ${SY.border}`,
          borderRadius: 10,
          padding: '28px 26px 22px',
          width: '100%', maxWidth: 360,
          position: 'relative',
          backdropFilter: 'blur(8px)',
          boxShadow: `0 0 0 1px ${SY.border} inset, 0 8px 30px rgba(0,0,0,0.45)`,
        }}>
          {/* Corners techniques */}
          <CornerBrackets color={SY.cyan} />

          {/* Label section */}
          <div style={{
            fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.2em',
            color: SY.cyan, marginBottom: 20, textTransform: 'uppercase',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ opacity: 0.6 }}>[</span>
            authentification
            <span style={{ opacity: 0.6 }}>]</span>
          </div>

          {error && (
            <div style={{
              color: '#fca5a5', fontSize: 12, marginBottom: 16, padding: '8px 10px',
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: 6,
              fontFamily: SY.mono,
            }}>
              <span style={{ color: SY.error }}>✗</span> {error}
            </div>
          )}

          <TechLabel>Email</TechLabel>
          <TechInput
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="votre@email.com"
          />

          <div style={{ height: 12 }} />

          <TechLabel>Mot de passe</TechLabel>
          <TechInput
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
          />

          <button onClick={handleLogin} style={{
            marginTop: 22, width: '100%',
            padding: '11px 14px', borderRadius: 8,
            background: `linear-gradient(135deg, ${SY.violet} 0%, ${SY.indigo} 40%, ${SY.blue} 75%, ${SY.cyan} 100%)`,
            color: '#fff',
            fontWeight: 700, fontSize: 13, letterSpacing: '0.12em',
            textTransform: 'uppercase',
            cursor: 'pointer',
            boxShadow: `0 0 0 1px rgba(0,200,255,0.3), 0 6px 20px rgba(0,200,255,0.18)`,
            fontFamily: SY.mono,
            border: 'none',
          }}>
            ▸ Connexion
          </button>

          {/* Divider OU */}
          <div style={{
            margin: '18px 0 14px', display: 'flex', alignItems: 'center', gap: 10,
            color: SY.textDim, fontSize: 10, fontFamily: SY.mono, letterSpacing: '0.15em',
          }}>
            <div style={{ flex: 1, height: 1, background: SY.border }} />
            <span>OU</span>
            <div style={{ flex: 1, height: 1, background: SY.border }} />
          </div>

          {/* Bouton Continuer avec Google — OAuth NATIF popup Tauri.
              Flow 100% in-app (pas de navigateur externe) :
                1. Backend retourne l'URL Google OAuth
                2. Rust ouvre une mini-fenetre Tauri (500x700) sur cette URL
                3. L'user se connecte a Google DANS la popup
                4. Google redirige vers /auth/callback?code=... — Rust intercepte
                   AVANT chargement et extrait le code, ferme la popup
                5. Le code est emit en event "google-oauth:code"
                6. On l'echange contre un JWT via POST /api/auth/oauth/google
                7. setToken(jwt) → user connecte. Tout reste dans l'app.
              Cookies persistes : le profil WebView2 est partage avec la
              fenetre principale, donc Google se souvient de l'user. */}
          <button
            onClick={async () => {
              setError('')
              const webBase = API_BASE.includes('localhost')
                ? 'http://localhost:5173'
                : 'https://sylea.ai'
              const redirectUri = `${webBase}/auth/callback`
              let codeUnsub: (() => void) | undefined
              let errorUnsub: (() => void) | undefined
              let cancelUnsub: (() => void) | undefined
              const cleanup = () => {
                try { codeUnsub?.() } catch {}
                try { errorUnsub?.() } catch {}
                try { cancelUnsub?.() } catch {}
              }
              try {
                // 1. Demande l'URL Google OAuth au backend (state=desktop_native
                //    distingue ce flow des autres pour le tracking eventuel ;
                //    le backend ne s'en sert pas pour la logique).
                const urlRes = await apiFetch(
                  API_BASE,
                  `/api/auth/oauth/google/url?redirect_uri=${encodeURIComponent(redirectUri)}&state=desktop_native`,
                  {},
                  { withAuth: false },
                )
                if (!urlRes.ok) throw new Error("Backend n'a pas retourne l'URL Google")
                const { url: oauthUrl } = await urlRes.json()

                // 2. Setup race promise : code (succes) | error (Google) | cancelled (close)
                const codePromise = new Promise<string>((resolve, reject) => {
                  const timeout = setTimeout(() => {
                    cleanup()
                    reject(new Error('Timeout (3 minutes)'))
                  }, 180_000)

                  listen<string>('google-oauth:code', (event) => {
                    clearTimeout(timeout); cleanup()
                    console.log('[oauth-button] code received')
                    resolve(event.payload)
                  }).then((fn) => { codeUnsub = fn }).catch(() => {})

                  listen<string>('google-oauth:error', (event) => {
                    clearTimeout(timeout); cleanup()
                    reject(new Error(`Google : ${event.payload}`))
                  }).then((fn) => { errorUnsub = fn }).catch(() => {})

                  listen('google-oauth:cancelled', () => {
                    clearTimeout(timeout); cleanup()
                    reject(new Error('cancelled'))
                  }).then((fn) => { cancelUnsub = fn }).catch(() => {})
                })

                // 3. Lance la popup
                await invoke('open_google_oauth_popup', { oauthUrl })

                // 4. Attend que l'user se connecte (ou annule)
                const code = await codePromise

                // 5. Echange le code contre un JWT (meme endpoint que le web).
                //    On reutilise apiFetch pour avoir le CSRF auto.
                const jwtRes = await apiFetch(
                  API_BASE,
                  '/api/auth/oauth/google',
                  {
                    method: 'POST',
                    body: JSON.stringify({ code, redirect_uri: redirectUri }),
                  },
                  { withAuth: false },
                )
                if (!jwtRes.ok) {
                  const errData = await jwtRes.json().catch(() => ({}))
                  throw new Error(errData.detail || 'Echange du code Google a echoue')
                }
                const { access_token } = await jwtRes.json()

                // 6. Connecte l'user, comme apres un login email/mdp
                localStorage.setItem('sylea_desktop_token', access_token)
                setToken(access_token)
              } catch (e) {
                cleanup()
                const msg = e instanceof Error ? e.message : 'erreur'
                if (msg === 'cancelled') {
                  // L'user a juste ferme la popup, pas d'erreur a montrer
                  console.log('[oauth-button] cancelled by user')
                } else {
                  console.error('[oauth-button] failed:', msg)
                  setError(`Connexion Google : ${msg}`)
                }
              }
            }}
            style={{
              width: '100%', padding: '10px 14px', borderRadius: 8,
              background: '#fff',
              color: '#1f2937',
              fontWeight: 600, fontSize: 13, letterSpacing: '0.05em',
              cursor: 'pointer',
              border: 'none',
              fontFamily: SY.mono,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
              transition: 'transform 0.15s, box-shadow 0.15s',
              boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-1px)' }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)' }}
            title="Ouvre le navigateur, fais ton OAuth Google, et tu reviens automatiquement loggé sur le desktop."
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
            </svg>
            Continuer avec Google
          </button>

          <div style={{
            marginTop: 16, fontSize: 10, fontFamily: SY.mono,
            color: SY.textDim, textAlign: 'center', letterSpacing: '0.1em',
          }}>
            Secure · End-to-end · <span style={{ color: SY.cyan }}>{API_BASE.replace(/^https?:\/\//, '')}</span>
          </div>
        </div>
        </div>
      </div>
    )
  }

  // ── DASHBOARD 3 COLONNES ──
  const wsColor = wsConnected ? SY.success : SY.error

  // En mode pill compact, on affiche un mini-display ambient (Sprint 1.4)
  if (pillMode) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', height: '100vh',
        background: 'rgba(5,8,16,0.92)', backdropFilter: 'blur(12px)',
        borderRadius: 12, overflow: 'hidden',
        border: `1px solid ${SY.borderHi}`,
        boxShadow: `0 8px 24px rgba(0,200,255,0.18)`,
      }}>
        <DesktopTitlebar onTogglePill={togglePill} isPill accent={SY.cyanSoft} />
        <div
          data-tauri-drag-region
          onDoubleClick={togglePill}
          style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 0.6rem', gap: 8, cursor: 'pointer',
            fontFamily: SY.mono,
          }}
          title="Double-clic = mode plein"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: wsConnected ? SY.success : SY.error,
              boxShadow: `0 0 8px ${wsConnected ? SY.success : SY.error}`,
              animation: 'sy-pulse 2s ease-in-out infinite',
            }} />
            <span style={{ fontSize: 10, color: SY.text, fontWeight: 600, letterSpacing: '0.04em' }}>
              {wsConnected ? 'CONNECTÉ' : 'OFFLINE'}
            </span>
          </div>
          <span style={{ fontSize: 9, color: SY.textMute }}>
            {steps.filter(s => s.status === 'done').length} act.
          </span>
        </div>
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100vh',
      background: SY.bg, overflow: 'hidden',
      position: 'relative',
    }}>
      {/* Ecoute active — overlay plein-ecran si declenche (cours universite/prepa) */}
      {ecouteActiveOpen && (
        <EcouteActive
          onClose={() => setEcouteActiveOpen(false)}
          authToken={token || undefined}
          apiBase={API_BASE}
        />
      )}

      {/* Sprint 2.2 — Particules de fond (canvas plein-ecran derriere tout) */}
      <BackgroundParticles count={50} color="0, 200, 255" />

      <DesktopTitlebar
        onTogglePill={togglePill}
        isPill={false}
        accent={SY.cyanSoft}
      />

      {/* Drag overlay (Sprint 1.6) */}
      {dragHover && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9000,
          background: 'rgba(0,200,255,0.12)',
          backdropFilter: 'blur(2px)',
          border: `2px dashed ${SY.cyan}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
          fontFamily: SY.mono, fontSize: 14, fontWeight: 600,
          color: SY.cyan, letterSpacing: '0.08em',
        }}>
          ↓ DROP ICI POUR ANALYSER ↓
        </div>
      )}

      {/* Notifs pause indicator */}
      {notifsPaused && (
        <div style={{
          position: 'absolute', top: 40, right: 12, zIndex: 100,
          padding: '4px 8px', borderRadius: 6,
          background: 'rgba(245,158,11,0.16)',
          border: '1px solid rgba(245,158,11,0.4)',
          fontSize: 10, fontFamily: SY.mono, color: SY.warn,
          letterSpacing: '0.06em',
        }}>
          🔕 NOTIFS EN PAUSE
        </div>
      )}

    <div style={{
      display: 'flex', flex: 1, overflow: 'hidden',
      position: 'relative',
    }}>

      {/* Animations tech */}
      <style>{`
        @keyframes a3-flow {
          0%   { background-position: 0% 50%; }
          50%  { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes a3-border {
          0%, 100% {
            border-color: rgba(56,189,248,0.3);
            box-shadow: 0 0 10px rgba(56,189,248,0.15), inset 0 0 6px rgba(129,140,248,0.05);
          }
          50% {
            border-color: rgba(129,140,248,0.4);
            box-shadow: 0 0 14px rgba(129,140,248,0.2), inset 0 0 10px rgba(56,189,248,0.07);
          }
        }
        .agent3-name-shimmer {
          background: linear-gradient(90deg, ${AGENT3_CYAN}, ${AGENT3_INDIGO}, ${SY.cyan}, ${AGENT3_CYAN});
          background-size: 300% 100%;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          animation: a3-flow 3s ease-in-out infinite;
        }
        .agent3-status-shimmer {
          animation: a3-status 3s ease-in-out infinite;
        }
        @keyframes a3-status {
          0%, 100% { color: ${AGENT3_CYAN}; opacity: 0.7; }
          50%      { color: ${AGENT3_INDIGO}; opacity: 0.9; }
        }
        @keyframes scan-line {
          0%   { top: 0;    opacity: 0; }
          10%  { opacity: 0.6; }
          90%  { opacity: 0.6; }
          100% { top: 100%; opacity: 0; }
        }
        .tech-card {
          position: relative;
          background: ${SY.surface};
          border: 1px solid ${SY.border};
          border-radius: 8px;
        }
        .tech-btn-hover {
          transition: all 0.15s;
        }
        .tech-btn-hover:hover {
          border-color: ${SY.borderHi} !important;
          background: ${SY.surfaceHi} !important;
        }

        /* ── Sprint 2.4 — Glow + pulse animations sur agents actifs ── */
        @keyframes sy-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes sy-glow-pulse {
          0%, 100% {
            box-shadow:
              0 0 6px var(--sy-glow, rgba(0,200,255,0.45)),
              0 0 14px var(--sy-glow, rgba(0,200,255,0.18));
          }
          50% {
            box-shadow:
              0 0 12px var(--sy-glow, rgba(0,200,255,0.65)),
              0 0 26px var(--sy-glow, rgba(0,200,255,0.32));
          }
        }
        @keyframes sy-halo-rotate {
          0%   { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        /* Halo conique tournant autour d'un agent actif (utilisable en pseudo-element) */
        .sy-agent-active {
          position: relative;
        }
        .sy-agent-active::before {
          content: '';
          position: absolute;
          inset: -3px;
          border-radius: inherit;
          padding: 1px;
          background: conic-gradient(
            from var(--sy-glow-angle, 0deg),
            var(--sy-glow-color, ${SY.cyan}) 0deg,
            transparent 90deg,
            var(--sy-glow-color, ${SY.cyan}) 180deg,
            transparent 270deg
          );
          -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
                  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
          -webkit-mask-composite: xor;
                  mask-composite: exclude;
          opacity: 0.55;
          animation: sy-halo-rotate 4s linear infinite;
          pointer-events: none;
        }
        .sy-agent-active::after {
          content: '';
          position: absolute;
          inset: 0;
          border-radius: inherit;
          animation: sy-glow-pulse 2.4s ease-in-out infinite;
          pointer-events: none;
        }
        /* Petite anim de tilt sur clic d'un bouton agent */
        @keyframes sy-tap {
          0%   { transform: scale(1); }
          50%  { transform: scale(0.97); }
          100% { transform: scale(1); }
        }
        .sy-tap:active { animation: sy-tap 0.15s ease-out; }
      `}</style>

      {/* ── SIDEBAR GAUCHE : Agents ── */}
      <div style={{
        width: 220, borderRight: `1px solid ${SY.border}`,
        display: 'flex', flexDirection: 'column',
        background: 'rgba(7, 12, 26, 0.45)',
        backdropFilter: 'blur(10px)',
        position: 'relative', zIndex: 2,
      }}>
        {/* Header sidebar : logo officiel + wordmark + point connexion */}
        <div style={{
          padding: '14px 14px 12px',
          borderBottom: `1px solid ${SY.border}`,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <SyleaLogo size={22} animated={false} hover3d />
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.1 }}>
            <div style={{
              fontSize: 11, fontWeight: 800, letterSpacing: '0.14em',
              color: SY.text,
            }}>
              SYLEA <span style={{ color: SY.cyanSoft, textShadow: `0 0 6px rgba(0,200,255,0.4)` }}>AGENT</span>
            </div>
            <div style={{
              fontSize: 8, fontFamily: SY.mono, letterSpacing: '0.18em',
              color: SY.textDim, marginTop: 2, textTransform: 'uppercase',
            }}>
              Desktop · v1.0
            </div>
          </div>
          <StatusDot color={wsColor} pulsing={!wsConnected} size={7} />
        </div>

        {/* Label section agents */}
        <div style={{
          padding: '12px 14px 6px',
          fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.2em',
          color: SY.textDim, textTransform: 'uppercase',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ color: SY.cyan }}>▸</span> Agents
          <div style={{ flex: 1, height: 1, background: SY.border }} />
          <span style={{ fontFamily: SY.mono }}>{AGENTS.filter(a => a.status !== 'locked').length}/{AGENTS.length}</span>
        </div>

        {/* Agent list */}
        <div style={{ flex: 1, padding: '4px 10px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {AGENTS.map(agent => {
            const isAgent3 = agent.id === 'agent3'
            const isSelected = selectedAgent === agent.id
            const statusSymbol =
              agent.status === 'active'   ? '●' :
              agent.status === 'locked'   ? '■' : '○'
            const statusLabel =
              agent.status === 'active'   ? 'ACTIF' :
              agent.status === 'locked'   ? 'LOCK'  : 'IDLE'
            return (
              <button
                key={agent.id}
                onClick={() => {
                  if (agent.status === 'locked') return
                  setSelectedAgent(agent.id)
                }}
                className={`tech-btn-hover sy-tap ${
                  isSelected && agent.status === 'active' ? 'sy-agent-active' : ''
                }`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 10px', borderRadius: 6,
                  background: isSelected
                    ? (isAgent3
                      ? `linear-gradient(135deg, rgba(56,189,248,0.08), rgba(129,140,248,0.05), transparent)`
                      : `${agent.color}14`)
                    : 'transparent',
                  border: isSelected
                    ? (isAgent3 ? `1px solid ${AGENT3_CYAN}40` : `1px solid ${agent.color}40`)
                    : '1px solid transparent',
                  cursor: agent.status === 'locked' ? 'not-allowed' : 'pointer',
                  opacity: agent.status === 'locked' ? 0.35 : 1,
                  width: '100%', textAlign: 'left',
                  position: 'relative',
                  // CSS vars pour le glow halo (Sprint 2.4)
                  ['--sy-glow-color' as any]: agent.color,
                  ['--sy-glow' as any]: `${agent.color}55`,
                  ...(isAgent3 && isSelected ? { animation: 'a3-border 3s ease-in-out infinite' } : {}),
                }}
              >
                {/* Barre verticale gauche active */}
                {isSelected && (
                  <span style={{
                    position: 'absolute', left: -10, top: 6, bottom: 6,
                    width: 2, borderRadius: 2,
                    background: isAgent3
                      ? `linear-gradient(to bottom, ${AGENT3_CYAN}, ${AGENT3_INDIGO})`
                      : agent.color,
                    boxShadow: `0 0 8px ${isAgent3 ? AGENT3_CYAN : agent.color}`,
                  }} />
                )}

                {/* Logo colore par agent — meme geometrie que le logo officiel,
                    gradient adapte (or / rouge / bleu-or anime / violet) */}
                <div style={{
                  width: 26, height: 26, borderRadius: 5,
                  background: isSelected ? `${agent.color}18` : 'rgba(0, 200, 255, 0.04)',
                  border: `1px solid ${isSelected ? agent.color + '50' : SY.border}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  <AgentSyleaLogo
                    size={18}
                    variant={agent.logoVariant}
                    animated={isSelected || isAgent3}
                  />
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  {isAgent3 ? (
                    <div
                      className={isSelected ? 'agent3-name-shimmer' : undefined}
                      style={{
                        fontSize: 12, fontWeight: 700,
                        ...(isSelected ? {} : { color: SY.textMute }),
                      }}>
                      {agent.name}
                    </div>
                  ) : (
                    <div style={{
                      fontSize: 12, fontWeight: 600,
                      color: isSelected ? agent.colorLight : SY.textMute,
                    }}>
                      {agent.name}
                    </div>
                  )}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    fontFamily: SY.mono, fontSize: 8.5, letterSpacing: '0.12em',
                    color: isAgent3
                      ? undefined
                      : (agent.status === 'active' ? SY.success : SY.textDim),
                    marginTop: 2,
                  }}
                  className={isAgent3 && !isSelected ? 'agent3-status-shimmer' : undefined}
                  >
                    <span>{statusSymbol}</span>
                    <span>{statusLabel}</span>
                    {/* Mini badge OpenClaw — texte explicite "CLAW" au lieu d'un dot
                        qui pouvait etre confondu avec un indicateur "actif".
                        Cyan = connecte, jaune = fallback Claude (offline). */}
                    {isAgent3 && (
                      <span
                        title={openclawConnected ? 'OpenClaw connecte' : 'OpenClaw — fallback Claude'}
                        style={{
                          marginLeft: 4, padding: '0 4px',
                          fontSize: 7, lineHeight: '11px',
                          letterSpacing: '0.08em',
                          borderRadius: 2,
                          color: openclawConnected ? SY.cyan : SY.warn,
                          background: openclawConnected ? 'rgba(0,200,255,0.10)' : 'rgba(245,158,11,0.10)',
                          border: `1px solid ${openclawConnected ? 'rgba(0,200,255,0.35)' : 'rgba(245,158,11,0.35)'}`,
                          fontWeight: 700,
                        }}
                      >
                        {openclawConnected ? 'CLAW' : 'CLAW✗'}
                      </span>
                    )}
                  </div>
                </div>

                {agent.unread > 0 && (
                  <span style={{
                    minWidth: 16, height: 16, padding: '0 4px', borderRadius: 8,
                    background: agent.color, color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 10, fontWeight: 700, fontFamily: SY.mono,
                  }}>{agent.unread}</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Footer sidebar */}
        <div style={{
          padding: '10px 12px', borderTop: `1px solid ${SY.border}`,
          display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {/* Ecoute active — bouton vedette pour cours univ/prepa.
              Disponible uniquement si Agent 2 est actif. */}
          {(activatedAgents.agent2 || lastActivityByAgent.agent2) && (
            <button
              onClick={() => setEcouteActiveOpen(true)}
              title="Enregistre un cours, l'agent en fait la fiche (univ/prepa)"
              style={{
                width: '100%', padding: '10px 12px', borderRadius: 7,
                background: 'linear-gradient(135deg, rgba(239,68,68,0.12), rgba(248,113,113,0.05))',
                border: '1px solid rgba(239,68,68,0.35)',
                color: '#fca5a5', fontSize: 11, fontFamily: SY.mono,
                letterSpacing: '0.1em', textTransform: 'uppercase',
                cursor: 'pointer', transition: 'all 0.18s',
                display: 'flex', alignItems: 'center', gap: 8,
                fontWeight: 700,
                boxShadow: '0 2px 10px rgba(239,68,68,0.10)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'linear-gradient(135deg, rgba(239,68,68,0.20), rgba(248,113,113,0.08))'
                e.currentTarget.style.boxShadow = '0 4px 14px rgba(239,68,68,0.25)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'linear-gradient(135deg, rgba(239,68,68,0.12), rgba(248,113,113,0.05))'
                e.currentTarget.style.boxShadow = '0 2px 10px rgba(239,68,68,0.10)'
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              </svg>
              <span style={{ flex: 1, textAlign: 'left' }}>Ecoute active</span>
            </button>
          )}

          {/* Mini status system */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.14em',
            color: SY.textDim, textTransform: 'uppercase',
            padding: '4px 2px',
          }}>
            <StatusDot color={wsColor} pulsing={!wsConnected} size={5} />
            <span>WS {wsConnected ? 'OK' : 'OFF'}</span>
            <span style={{ opacity: 0.4 }}>·</span>
            <StatusDot color={openclawConnected ? SY.success : SY.warn} size={5} />
            <span>CLAW</span>
          </div>
          <button onClick={handleLogout} style={{
            width: '100%', padding: '7px 10px', borderRadius: 6,
            background: 'transparent', border: `1px solid ${SY.border}`,
            color: SY.textMute, fontSize: 10, fontFamily: SY.mono,
            letterSpacing: '0.16em', textTransform: 'uppercase',
            cursor: 'pointer', transition: 'all 0.15s',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)'
            e.currentTarget.style.color = SY.error
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = SY.border
            e.currentTarget.style.color = SY.textMute
          }}
          >
            ▸ Deconnexion
          </button>
        </div>
      </div>

      {/* ── CENTRE : Actions en cours / Agent 3 Log ── */}
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        borderRight: `1px solid ${SY.border}`,
        position: 'relative', zIndex: 2,
      }}>
        {/* Header centre */}
        <div style={{
          padding: '12px 18px',
          borderBottom: `1px solid ${SY.border}`,
          display: 'flex', alignItems: 'center', gap: 10,
          background: 'rgba(7, 12, 26, 0.35)',
        }}>
          {selectedAgent === 'agent3' && agent3Logs.length > 0 ? (
            <>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.18em',
                color: SY.cyan, textTransform: 'uppercase',
              }}>▸ STREAM</span>
              <span className="agent3-name-shimmer" style={{
                fontSize: 13, fontWeight: 700, letterSpacing: '0.04em',
              }}>
                Agent 3 — Execution
              </span>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.1em',
                color: AGENT3_CYAN, background: 'rgba(56,189,248,0.08)',
                padding: '2px 8px', borderRadius: 4,
                border: `1px solid ${AGENT3_CYAN}30`,
              }}>
                {agent3Logs.length} log{agent3Logs.length > 1 ? 's' : ''}
              </span>
              <div style={{ flex: 1 }} />
              <button onClick={() => setAgent3Logs([])} style={{
                background: 'transparent', border: `1px solid ${SY.border}`,
                color: SY.textMute, fontSize: 10, fontFamily: SY.mono,
                padding: '4px 8px', borderRadius: 4,
                letterSpacing: '0.14em', textTransform: 'uppercase',
                cursor: 'pointer',
              }}>Effacer</button>
            </>
          ) : (
            <>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.18em',
                color: SY.cyan, textTransform: 'uppercase',
              }}>▸ ACTIONS</span>
              <span style={{
                fontSize: 13, fontWeight: 700, letterSpacing: '0.04em',
                color: SY.text,
              }}>
                Flux en temps reel
              </span>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.1em',
                color: SY.textMute, background: SY.surface,
                padding: '2px 8px', borderRadius: 4,
                border: `1px solid ${SY.border}`,
              }}>
                <CountUp to={steps.length} durationMs={400} /> etape{steps.length > 1 ? 's' : ''}
              </span>
            </>
          )}
        </div>

        {/* Sprint 2.6 — Live activity feed sous le header */}
        <LiveActivityFeed
          activities={liveActivities}
          accent={SY.cyan}
          style={{ padding: '4px 14px 0' }}
        />

        {/* Agent 3 Claude Code-like log panel */}
        {selectedAgent === 'agent3' && agent3Logs.length > 0 && (
          <div style={{
            flex: 1, overflow: 'auto', padding: '8px 14px',
            background: 'rgba(0, 4, 12, 0.55)',
            fontFamily: SY.mono,
            position: 'relative',
          }}>
            {agent3Logs.map((log, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                padding: '4px 8px', borderRadius: 4,
                fontSize: 12, lineHeight: 1.55,
                background:
                  log.type === 'tool'    ? 'rgba(56,189,248,0.04)' :
                  log.type === 'success' ? 'rgba(16,185,129,0.04)' :
                  log.type === 'error'   ? 'rgba(239,68,68,0.05)' :
                  'transparent',
                borderLeft:
                  log.type === 'tool'    ? `2px solid ${AGENT3_CYAN}` :
                  log.type === 'success' ? `2px solid ${SY.success}` :
                  log.type === 'error'   ? `2px solid ${SY.error}` :
                  '2px solid transparent',
              }}>
                <span style={{
                  color: SY.textDim, flexShrink: 0,
                  fontSize: 10, minWidth: '5.2rem',
                }}>
                  {log.time}
                </span>
                <span style={{
                  color:
                    log.type === 'success' ? SY.success :
                    log.type === 'tool'    ? AGENT3_CYAN :
                    log.type === 'warning' ? SY.warn :
                    log.type === 'error'   ? SY.error :
                    SY.textMute,
                }}>
                  {log.type === 'tool'    && <span style={{ color: AGENT3_CYAN, marginRight: 6 }}>▸</span>}
                  {log.type === 'success' && <span style={{ color: SY.success, marginRight: 6 }}>✓</span>}
                  {log.type === 'error'   && <span style={{ color: SY.error,   marginRight: 6 }}>✗</span>}
                  {log.text}
                </span>
              </div>
            ))}
            <div ref={agent3LogEndRef} />
          </div>
        )}

        {/* Steps list — hidden when Agent 3 log is shown */}
        <div style={{
          flex: 1, overflow: 'auto', padding: 14,
          display: (selectedAgent === 'agent3' && agent3Logs.length > 0) ? 'none' : 'block',
        }}>
          {steps.length === 0 ? (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              height: '100%', gap: 14, position: 'relative',
            }}>
              {/* Halo logo */}
              <div style={{
                position: 'relative',
                width: 120, height: 120,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <div style={{
                  position: 'absolute', inset: 0, borderRadius: '50%',
                  background: 'radial-gradient(circle, rgba(0,200,255,0.08), transparent 60%)',
                }} />
                <div style={{ opacity: 0.55 }}>
                  <SyleaLogo size={80} animated hover3d />
                </div>
              </div>
              <div style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.2em',
                color: SY.textDim, textTransform: 'uppercase',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <StatusDot color={SY.cyan} pulsing size={5} />
                Standby — En attente d'instructions
              </div>
              <p style={{
                fontSize: 12, color: SY.textDim, margin: 0,
                maxWidth: 360, textAlign: 'center', lineHeight: 1.5,
              }}>
                Envoie une commande depuis la version web de Syléa.
                L'agent executera les actions sur cet ordinateur en temps reel.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {steps.map((step, idx) => {
                const icons: Record<string, string> = {
                  EMAIL: '✉', TEXT: '▤', LINK: '↗', COPY: '⎘', REMINDER: '◷',
                  SEARCH: '⌕', X_SEARCH: '𝕏', ANALYSIS: '◫', FILE: '⬚',
                  PDF: '▥', CODE: '⌁', EXEC: '>_', AGENT: '◈', WEBPAGE: '◉',
                  IMAGE: '▣', SCREENSHOT: '▢', CANVAS: '◧', CRON: '◑',
                  MEMORY: '◊', ACTION: '▸', info: 'ℹ', action: '▸',
                }
                const statusColors: Record<string, string> = {
                  done: SY.success, running: SY.warn, error: SY.error, pending: SY.textDim,
                }
                const statusGlyphs: Record<string, string> = {
                  done: '✓', running: '◐', error: '✗', pending: '○',
                }
                const isA3 = step.agent === 'agent3'
                const accent = isA3 ? AGENT3_CYAN : SY.cyan

                return (
                  <SlideIn key={step.id} from="left" distance={12} duration={260}>
                  <div style={{
                    display: 'flex', alignItems: 'stretch', gap: 0,
                    borderRadius: 8,
                    background: step.status === 'error'
                      ? 'rgba(239,68,68,0.05)'
                      : (isA3 ? 'rgba(56,189,248,0.04)' : SY.surface),
                    border: `1px solid ${
                      step.status === 'error' ? 'rgba(239,68,68,0.25)'
                        : isA3 ? `${AGENT3_CYAN}30`
                        : SY.border
                    }`,
                    overflow: 'hidden',
                    transition: 'all 0.2s',
                  }}>
                    {/* Rail vertical gauche colore par agent (style Claude Code) */}
                    <div style={{
                      width: 3, flexShrink: 0,
                      background: step.status === 'error'
                        ? SY.error
                        : step.status === 'running'
                          ? `linear-gradient(180deg, ${accent}, transparent, ${accent})`
                          : (step.status === 'done' ? SY.success : SY.textDim),
                      animation: step.status === 'running' ? 'a3-flow 2s ease-in-out infinite' : 'none',
                      backgroundSize: step.status === 'running' ? '100% 200%' : 'auto',
                    }} />

                    <div style={{ flex: 1, padding: '10px 14px', minWidth: 0 }}>
                      {/* Header : numero + categorie + statut + timestamp */}
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        fontFamily: SY.mono,
                        marginBottom: 6,
                      }}>
                        {/* Numero */}
                        <span style={{
                          fontSize: 9, color: SY.textDim, letterSpacing: '0.06em',
                          fontWeight: 600, minWidth: 22,
                        }}>
                          #{String(idx + 1).padStart(3, '0')}
                        </span>
                        {/* Icone + categorie */}
                        <span style={{
                          fontSize: 13, color: accent, lineHeight: 1,
                        }}>{icons[step.action] || '▸'}</span>
                        <span style={{
                          fontSize: 10, fontWeight: 700,
                          color: accent, letterSpacing: '0.14em',
                          textTransform: 'uppercase',
                        }}>
                          {step.action.replace(/_/g, ' ')}
                        </span>
                        {/* Badge agent */}
                        {isA3 && (
                          <span style={{
                            fontSize: 8, color: AGENT3_CYAN, letterSpacing: '0.1em',
                            padding: '1px 5px', borderRadius: 3,
                            border: `1px solid ${AGENT3_CYAN}50`,
                            background: 'rgba(56,189,248,0.08)',
                            fontWeight: 700,
                          }}>AGENT 3</span>
                        )}
                        <div style={{ flex: 1 }} />
                        {/* Statut + glyph */}
                        <span style={{
                          fontSize: 10, fontWeight: 700,
                          color: statusColors[step.status],
                          letterSpacing: '0.12em', textTransform: 'uppercase',
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                        }}>
                          <span style={{
                            display: 'inline-block',
                            animation: step.status === 'running' ? 'sy-spin 1s linear infinite' : 'none',
                          }}>
                            {statusGlyphs[step.status]}
                          </span>
                          {step.status}
                        </span>
                        {/* Timestamp */}
                        <span style={{
                          fontSize: 10, color: SY.textDim, letterSpacing: '0.06em',
                          fontVariantNumeric: 'tabular-nums',
                        }}>
                          {step.time}
                        </span>
                      </div>

                      {/* Body : detail (+ sub-bullet ↳ pour ressembler aux tool calls Claude Code) */}
                      <div style={{
                        display: 'flex', alignItems: 'flex-start', gap: 8,
                        paddingLeft: 30,
                      }}>
                        <span style={{
                          fontFamily: SY.mono, fontSize: 12,
                          color: SY.textMute, marginTop: -1, flexShrink: 0,
                        }}>↳</span>
                        <p style={{
                          fontSize: 13, color: SY.text, lineHeight: 1.5,
                          margin: 0, wordBreak: 'break-word', flex: 1,
                          fontWeight: step.status === 'running' ? 500 : 400,
                        }}>
                          {step.detail}
                        </p>
                      </div>
                    </div>
                  </div>
                  </SlideIn>
                )
              })}
              <div ref={stepsEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* ── DROITE : TODOLIST + STATS HUD ──
          Style "Claude Code" : checkboxes nettes, numerotation, progress
          bar globale en haut, items compactes mais lisibles. */}
      <div style={{
        width: 380,
        display: 'flex', flexDirection: 'column',
        background: 'rgba(7, 12, 26, 0.55)',
        backdropFilter: 'blur(8px)',
        position: 'relative', zIndex: 2,
      }}>
        {/* ── Header todolist ── */}
        {(() => {
          // Source unifiee : si Agent 3 streame, on prend ses steps, sinon le
          // plan classique. Resultat = liste {id, label, status, detail}.
          const items =
            selectedAgent === 'agent3' && agent3StreamSteps.length > 0
              ? agent3StreamSteps.map(s => ({
                  id: s.id, label: s.label, status: s.status,
                  detail: s.detail, agent: 'agent3' as const,
                }))
              : plan.map((p, i) => ({
                  id: `plan-${i}`, label: p.step, status: p.status,
                  detail: '', agent: p.agent || 'agent2',
                }))

          const isA3Source = selectedAgent === 'agent3' && agent3StreamSteps.length > 0
          const accent = isA3Source ? AGENT3_CYAN : SY.cyan
          const totalDone = items.filter(i => i.status === 'done').length
          const total = items.length
          const pct = total > 0 ? Math.round((totalDone / total) * 100) : 0

          return (
            <>
              <div style={{
                padding: '14px 16px 12px',
                borderBottom: `1px solid ${SY.border}`,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10, marginBottom: total > 0 ? 10 : 0,
                }}>
                  <span style={{
                    fontFamily: SY.mono, fontSize: 11, letterSpacing: '0.2em',
                    color: accent, textTransform: 'uppercase',
                  }}>▸ TODOLIST</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: SY.text, letterSpacing: '0.02em' }}>
                    {isA3Source ? 'Agent 3 — Plan' : 'Plan d\'execution'}
                  </span>
                  <div style={{ flex: 1 }} />
                  {total > 0 && (
                    <span style={{
                      fontFamily: SY.mono, fontSize: 11, fontWeight: 700,
                      color: accent, background: `${accent}14`,
                      padding: '3px 9px', borderRadius: 5,
                      border: `1px solid ${accent}40`,
                      letterSpacing: '0.06em',
                    }}>
                      <CountUp to={totalDone} durationMs={400} />/<CountUp to={total} durationMs={400} />
                    </span>
                  )}
                </div>
                {/* Progress bar globale (visible seulement si plan actif) */}
                {total > 0 && (
                  <>
                    <div style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.14em',
                      color: SY.textDim, marginBottom: 5, textTransform: 'uppercase',
                    }}>
                      <span>Progression</span>
                      <span style={{ color: accent, fontWeight: 700 }}>
                        <CountUp to={pct} durationMs={500} suffix="%" />
                      </span>
                    </div>
                    <div style={{
                      height: 5, borderRadius: 3,
                      background: 'rgba(0,0,0,0.4)',
                      border: `1px solid ${SY.border}`,
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        height: '100%', borderRadius: 3,
                        background: isA3Source
                          ? `linear-gradient(90deg, ${AGENT3_CYAN}, ${AGENT3_INDIGO}, ${AGENT3_CYAN})`
                          : `linear-gradient(90deg, ${SY.cyan}, ${SY.blue}, ${SY.cyan})`,
                        backgroundSize: '200% 100%',
                        animation: 'a3-border 3s ease-in-out infinite',
                        boxShadow: `0 0 8px ${accent}80`,
                        width: `${pct}%`,
                        transition: 'width 0.5s ease',
                      }} />
                    </div>
                  </>
                )}
              </div>

              {/* ── Liste todolist ── */}
              <div style={{
                flex: 1, overflow: 'auto', padding: '10px 12px 14px',
              }} className="sy-scroll">
                {total === 0 ? (
                  <div style={{
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                    height: '100%', gap: 12, textAlign: 'center',
                    padding: '40px 14px',
                  }}>
                    <div style={{
                      width: 56, height: 56, borderRadius: '50%',
                      border: `1.5px dashed ${SY.border}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: SY.textDim, fontSize: 22,
                    }}>
                      ☐
                    </div>
                    <div>
                      <div style={{
                        fontFamily: SY.mono, fontSize: 11, letterSpacing: '0.18em',
                        color: SY.textMute, textTransform: 'uppercase', marginBottom: 6,
                      }}>
                        Aucune tache active
                      </div>
                      <div style={{
                        fontSize: 11, color: SY.textDim, maxWidth: 240, lineHeight: 1.5,
                      }}>
                        Quand un agent recevra une instruction, sa todolist apparaitra ici avec progress live.
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {items.map((item, idx) => {
                      const isA3 = item.agent === 'agent3'
                      const statusColor =
                        item.status === 'done'    ? SY.success :
                        item.status === 'running' ? (isA3 ? AGENT3_CYAN : SY.warn) :
                                                    SY.textDim
                      return (
                        <SlideIn key={item.id} from="right" distance={10} duration={260}>
                        <div style={{
                          display: 'flex', alignItems: 'flex-start', gap: 10,
                          padding: '10px 12px', borderRadius: 7,
                          background:
                            item.status === 'done'    ? 'rgba(16,185,129,0.05)' :
                            item.status === 'running' ? (isA3 ? 'rgba(56,189,248,0.07)' : 'rgba(245,158,11,0.06)') :
                                                        SY.surface,
                          border: `1px solid ${
                            item.status === 'done'    ? `${SY.success}30` :
                            item.status === 'running' ? (isA3 ? `${AGENT3_CYAN}50` : `${SY.warn}40`) :
                                                        SY.border
                          }`,
                          transition: 'all 0.25s',
                          position: 'relative',
                        }}>
                          {/* Numero d'item */}
                          <div style={{
                            fontFamily: SY.mono, fontSize: 10,
                            color: SY.textDim, letterSpacing: '0.06em',
                            minWidth: 18, paddingTop: 1, fontWeight: 600,
                          }}>
                            {String(idx + 1).padStart(2, '0')}
                          </div>

                          {/* Checkbox status */}
                          <div style={{
                            width: 18, height: 18, borderRadius: 4,
                            border: `1.5px solid ${statusColor}`,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            flexShrink: 0, marginTop: 1,
                            background: item.status === 'done' ? `${SY.success}22` : 'transparent',
                            transition: 'all 0.25s',
                          }}>
                            {item.status === 'done' && (
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                                   stroke={SY.success} strokeWidth="3.5"
                                   strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                            )}
                            {item.status === 'running' && (
                              <div style={{
                                width: 9, height: 9, borderRadius: '50%',
                                border: '2px solid transparent',
                                borderTopColor: statusColor,
                                borderRightColor: statusColor,
                                animation: 'sy-spin 0.8s linear infinite',
                              }} />
                            )}
                          </div>

                          {/* Contenu : label + detail */}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <p style={{
                              fontSize: 12, margin: 0,
                              lineHeight: 1.4,
                              fontWeight: item.status === 'running' ? 600 : 500,
                              color:
                                item.status === 'done'    ? SY.text :
                                item.status === 'running' ? statusColor :
                                                            SY.textMute,
                              textDecoration: item.status === 'done' ? 'line-through' : 'none',
                              textDecorationColor: 'rgba(16,185,129,0.4)',
                              wordBreak: 'break-word',
                            }}>
                              {item.label}
                            </p>
                            {item.detail && (
                              <p style={{
                                fontSize: 10, fontFamily: SY.mono,
                                color: SY.textDim, margin: '4px 0 0',
                                letterSpacing: '0.02em',
                                lineHeight: 1.4,
                              }}>
                                ↳ {item.detail}
                              </p>
                            )}
                          </div>

                          {/* Badge agent (si A3) */}
                          {isA3 && (
                            <span style={{
                              fontFamily: SY.mono, fontSize: 8,
                              color: AGENT3_CYAN, letterSpacing: '0.1em',
                              padding: '2px 5px', borderRadius: 3,
                              border: `1px solid ${AGENT3_CYAN}50`,
                              background: 'rgba(56,189,248,0.08)',
                              alignSelf: 'flex-start',
                            }}>A3</span>
                          )}
                        </div>
                        </SlideIn>
                      )
                    })}
                  </div>
                )}
              </div>
            </>
          )
        })()}

        {/* Sprint 2.7 — Stats real-time HUD avec sparklines */}
        <div style={{
          padding: '10px 10px 0', borderTop: `1px solid ${SY.border}`,
        }}>
          <div style={{
            fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.18em',
            color: SY.textDim, textTransform: 'uppercase', marginBottom: 6,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ color: SY.cyan }}>▸</span> System HUD
          </div>
          <StatsHUD
            data={stats}
            cyan={SY.cyan}
            textMute={SY.textMute}
            textDim={SY.textDim}
            border={SY.border}
            surface={SY.surface}
            text={SY.text}
          />
        </div>

        {/* Status footer */}
        <div style={{
          padding: '8px 12px', borderTop: `1px solid ${SY.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.14em',
          color: SY.textDim, textTransform: 'uppercase',
        }}>
          <span>v1.0</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <StatusDot
              color={openclawConnected ? SY.success : SY.warn}
              pulsing={!openclawConnected}
              size={5}
            />
            <span style={{ color: openclawConnected ? SY.success : SY.warn }}>
              OpenClaw {openclawConnected ? 'OK' : 'WAIT'}
            </span>
          </div>
        </div>
      </div>
    </div>
    </div>
  )
}

export default App
