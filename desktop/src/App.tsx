import { useState, useEffect, useRef, useCallback } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import OpenClawOnboarding from './OpenClawOnboarding'
import { SyleaLogo, SyleaWordmark, AgentSyleaLogo, type AgentVariant } from './SyleaLogo'
import { DesktopTitlebar } from './DesktopTitlebar'
import { useDragDrop, type DroppedFile } from './useDragDrop'
import { SplashScreen } from './SplashScreen'
import { BackgroundParticles } from './BackgroundParticles'
import { useSound } from './useSound'
import { useTheme } from './useTheme'
import { ThemeSwitcher } from './ThemeSwitcher'
import { SoundToggle } from './SoundToggle'
import { LiveActivityFeed, type LiveActivity } from './LiveActivityFeed'
import { StatsHUD, type StatsHUDData, pushHist } from './StatsHUD'
import { CountUp } from './CountUp'
import { FadeIn, SlideIn } from './Motion'

const API_BASE = 'http://localhost:8000'

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
const AGENTS: AgentInfo[] = [
  { id: 'agent1', name: 'Syléa 1',   color: '#f59e0b', colorLight: '#fbbf24', logoVariant: 'gold',   status: 'active',   unread: 0 },
  { id: 'agent2', name: 'Syléa 2',   color: '#ef4444', colorLight: '#f87171', logoVariant: 'red',    status: 'inactive', unread: 0 },
  { id: 'agent3', name: 'Syléa 3',   color: '#38bdf8', colorLight: '#a5b4fc', logoVariant: 'agent3', status: 'inactive', unread: 0 },
  { id: 'agent4', name: 'Super Agent', color: '#8b5cf6', colorLight: '#c4b5fd', logoVariant: 'violet', status: 'locked',   unread: 0 },
]

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
  // Sprint 2.1 — Splash screen au premier mount (1.4s). Une seule fois par
  // session, pas re-affiche apres login/logout.
  const [splashDone, setSplashDone] = useState(false)

  // Sprint 2.8 — Theme actif (dark | cyber | aurora). La palette s'applique
  // aussi via CSS variables (--sy-*) dans useTheme.ts.
  const { palette, theme: _theme } = useTheme()

  // Sprint 2.3 — Sound design (clic / succes / erreur / notify).
  const { play: playSound } = useSound()

  // Sprint 2.6 — Live activity feed : map agentId → derniere activite
  const [liveActivities, setLiveActivities] = useState<LiveActivity[]>([])
  const pushActivity = useCallback((activity: Omit<LiveActivity, 'since'>) => {
    setLiveActivities(prev => {
      const next = prev.filter(a => a.agentId !== activity.agentId)
      next.push({ ...activity, since: Date.now() })
      return next.slice(-5)
    })
  }, [])

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
  const [wsConnected, setWsConnected] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState('agent2')
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

  // Login
  const handleLogin = async () => {
    setError('')
    playSound('click')
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (data.access_token) {
        playSound('success')
        setToken(data.access_token)
        localStorage.setItem('sylea_desktop_token', data.access_token)
      } else {
        playSound('error')
        setError(data.detail || 'Identifiants incorrects')
      }
    } catch {
      playSound('error')
      setError('Serveur inaccessible (localhost:8000)')
    }
  }

  // Request notification permission on mount
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // Reminder checker — polls every 30s and fires desktop notifications
  useEffect(() => {
    if (!token) return
    const headers = { 'Authorization': `Bearer ${token}` }
    const firedReminders = new Set<number>()

    const checkReminders = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agent2/reminders`, { headers })
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
            // Mark as completed
            fetch(`${API_BASE}/api/agent2/reminders/${r.id}/complete`, {
              method: 'POST', headers,
            }).catch(() => {})
          }
        }
      } catch { /* silent */ }
    }

    const interval = setInterval(checkReminders, 30000)
    checkReminders() // Check immediately
    return () => clearInterval(interval)
  }, [token])

  // OpenClaw Gateway health check — polls every 45s
  useEffect(() => {
    if (!token) return
    const checkOpenClaw = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/agent3/status`, {
          headers: { 'Authorization': `Bearer ${token}` },
        })
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
      const ws = new WebSocket(`ws://localhost:8000/ws/agent?token=${token}`)
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
              // Send content back to server
              const response = await fetch(`${API_BASE}/api/agent3/file-response`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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
    // Sprint 2.3 — Sound feedback discret sur completions et erreurs
    if (status === 'done')  playSound('notify')
    if (status === 'error') playSound('error')
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
          const res = await fetch(`${API_BASE}/api/agent2/send-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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
          await fetch(`${API_BASE}/api/agent2/create-reminder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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
            await fetch(`${API_BASE}/api/agent3/chat`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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
          const response = await fetch(`${API_BASE}${downloadUrl}`, {
            headers: { 'Authorization': `Bearer ${token}` },
          })
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
          const response = await fetch(`${API_BASE}${pdfUrl}`, {
            headers: { 'Authorization': `Bearer ${token}` },
          })
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
    playSound('click')
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
  if (!splashDone) {
    return <SplashScreen onComplete={() => setSplashDone(true)} />
  }

  // ── ONBOARDING OPENCLAW (Phase 2b) ──
  // Affichage bloquant au 1er lancement : wizard qui installe OpenClaw,
  // genere le token gateway et propose 5 skills ClawHub pre-coches.
  if (isOnboarded === null) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        minHeight: '100vh', gap: 18,
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
    )
  }
  if (isOnboarded === false) {
    return <OpenClawOnboarding onComplete={() => setIsOnboarded(true)} />
  }

  // ── LOGIN ──
  if (!token) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        minHeight: '100vh', padding: '2rem',
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
          }}>
            ▸ Connexion
          </button>

          <div style={{
            marginTop: 16, fontSize: 10, fontFamily: SY.mono,
            color: SY.textDim, textAlign: 'center', letterSpacing: '0.1em',
          }}>
            Secure · End-to-end · <span style={{ color: SY.cyan }}>localhost:8000</span>
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
        <DesktopTitlebar onTogglePill={togglePill} isPill accent={palette.cyanSoft} />
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
      {/* Sprint 2.2 — Particules de fond (canvas plein-ecran derriere tout) */}
      <BackgroundParticles count={50} color={palette.particleRgb} />

      <DesktopTitlebar
        onTogglePill={togglePill}
        isPill={false}
        accent={palette.cyanSoft}
        extraButtons={
          <>
            <SoundToggle color={palette.cyanSoft} />
            <ThemeSwitcher />
          </>
        }
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
                  if (agent.status === 'locked') {
                    playSound('error')
                    return
                  }
                  playSound('click')
                  setSelectedAgent(agent.id)
                }}
                onMouseEnter={() => { if (agent.status !== 'locked') playSound('hover') }}
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
                    {isAgent3 && (
                      <span
                        title={openclawConnected ? 'OpenClaw connecte' : 'OpenClaw — fallback Claude'}
                        style={{
                          display: 'inline-block', marginLeft: 2,
                          width: 4, height: 4, borderRadius: '50%',
                          background: openclawConnected ? SY.success : SY.warn,
                          boxShadow: openclawConnected ? `0 0 4px ${SY.success}` : 'none',
                        }}
                      />
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
          accent={palette.cyan}
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {steps.map((step) => {
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
                const isA3 = step.agent === 'agent3'
                return (
                  <SlideIn key={step.id} from="left" distance={12} duration={280}>
                  <div style={{
                    display: 'flex', alignItems: 'flex-start', gap: 10,
                    padding: '8px 12px', borderRadius: 6,
                    background: step.status === 'error'
                      ? 'rgba(239,68,68,0.05)'
                      : (isA3 ? 'rgba(56,189,248,0.03)' : SY.surface),
                    border: `1px solid ${
                      step.status === 'error' ? 'rgba(239,68,68,0.2)'
                        : isA3 ? `${AGENT3_CYAN}22`
                        : SY.border
                    }`,
                    transition: 'all 0.2s',
                  }}>
                    <span style={{
                      fontFamily: SY.mono, fontSize: 13,
                      color: isA3 ? AGENT3_CYAN : SY.cyan,
                      marginTop: 1, minWidth: 14,
                    }}>{icons[step.action] || '▸'}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{
                        fontSize: 12, color: SY.text, lineHeight: 1.45, margin: 0,
                        wordBreak: 'break-word',
                      }}>{step.detail}</p>
                    </div>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
                      fontFamily: SY.mono,
                    }}>
                      {isA3 && <span style={{
                        fontSize: 8, color: AGENT3_CYAN, letterSpacing: '0.1em',
                        padding: '1px 4px', borderRadius: 3,
                        border: `1px solid ${AGENT3_CYAN}40`, background: 'rgba(56,189,248,0.06)',
                      }}>A3</span>}
                      <StatusDot color={statusColors[step.status]} pulsing={step.status === 'running'} size={6} />
                      <span style={{ fontSize: 9, color: SY.textDim, letterSpacing: '0.08em' }}>{step.time}</span>
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

      {/* ── DROITE : Plan d'execution / Taches Agent 3 ── */}
      <div style={{
        width: 260, display: 'flex', flexDirection: 'column',
        background: 'rgba(7, 12, 26, 0.45)',
        position: 'relative', zIndex: 2,
      }}>
        {/* Header droite */}
        <div style={{
          padding: '12px 14px',
          borderBottom: `1px solid ${SY.border}`,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          {selectedAgent === 'agent3' && agent3StreamSteps.length > 0 ? (
            <>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.18em',
                color: AGENT3_CYAN, textTransform: 'uppercase',
              }}>▸ TASKS</span>
              <span className="agent3-name-shimmer" style={{ fontSize: 12, fontWeight: 700 }}>
                Agent 3
              </span>
              <div style={{ flex: 1 }} />
              <span style={{
                fontFamily: SY.mono, fontSize: 10,
                color: AGENT3_CYAN, background: 'rgba(56,189,248,0.08)',
                padding: '2px 7px', borderRadius: 4,
                border: `1px solid ${AGENT3_CYAN}30`,
              }}>
                {agent3StreamSteps.filter(s => s.status === 'done').length}/{agent3StreamSteps.length}
              </span>
            </>
          ) : (
            <>
              <span style={{
                fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.18em',
                color: SY.cyan, textTransform: 'uppercase',
              }}>▸ PLAN</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: SY.text }}>
                Execution
              </span>
              <div style={{ flex: 1 }} />
              {plan.length > 0 && (
                <span style={{
                  fontFamily: SY.mono, fontSize: 10,
                  color: SY.success, background: 'rgba(16,185,129,0.08)',
                  padding: '2px 7px', borderRadius: 4,
                  border: `1px solid ${SY.success}30`,
                }}>
                  {plan.filter(p => p.status === 'done').length}/{plan.length}
                </span>
              )}
            </>
          )}
        </div>

        {/* Agent 3 streaming steps with progress bar */}
        {selectedAgent === 'agent3' && agent3StreamSteps.length > 0 ? (
          <div style={{ flex: 1, overflow: 'auto', padding: '10px 10px 14px' }}>
            {/* Progress bar */}
            <div style={{ padding: '0 2px 12px' }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.14em',
                color: SY.textDim, marginBottom: 6, textTransform: 'uppercase',
              }}>
                <span>Progress</span>
                <span style={{ color: AGENT3_CYAN }}>
                  {Math.round((agent3StreamSteps.filter(s => s.status === 'done').length / agent3StreamSteps.length) * 100)}%
                </span>
              </div>
              <div style={{
                height: 3, borderRadius: 2,
                background: SY.surface,
                border: `1px solid ${SY.border}`,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%', borderRadius: 2,
                  background: `linear-gradient(90deg, ${AGENT3_CYAN}, ${AGENT3_INDIGO}, ${AGENT3_CYAN})`,
                  backgroundSize: '200% 100%',
                  animation: 'a3-border 3s ease-in-out infinite',
                  boxShadow: `0 0 8px ${AGENT3_CYAN}80`,
                  width: `${Math.round((agent3StreamSteps.filter(s => s.status === 'done').length / agent3StreamSteps.length) * 100)}%`,
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
            {/* Steps list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {agent3StreamSteps.map((s) => (
                <div key={s.id} style={{
                  padding: '8px 10px', borderRadius: 6,
                  background:
                    s.status === 'running' ? 'rgba(56,189,248,0.06)' :
                    s.status === 'done'    ? 'rgba(16,185,129,0.04)' :
                    SY.surface,
                  border: `1px solid ${
                    s.status === 'running' ? `${AGENT3_CYAN}40` :
                    s.status === 'done'    ? `${SY.success}30` :
                    SY.border
                  }`,
                  display: 'flex', alignItems: 'center', gap: 8,
                  transition: 'all 0.3s',
                }}>
                  {/* Status indicator */}
                  <div style={{
                    width: 16, height: 16, display: 'flex',
                    alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  }}>
                    {s.status === 'done' && (
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={SY.success} strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                    )}
                    {s.status === 'running' && (
                      <div style={{
                        width: 12, height: 12, borderRadius: '50%',
                        border: '2px solid transparent',
                        borderTopColor: AGENT3_CYAN, borderRightColor: AGENT3_INDIGO,
                        animation: 'sy-spin 0.8s linear infinite',
                      }} />
                    )}
                    {s.status === 'pending' && (
                      <div style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: SY.textDim,
                      }} />
                    )}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{
                      fontSize: 11, margin: 0, lineHeight: 1.35,
                      fontWeight: s.status === 'running' ? 600 : 500,
                      color:
                        s.status === 'running' ? AGENT3_CYAN :
                        s.status === 'done'    ? SY.success :
                        SY.textMute,
                    }}>
                      {s.label}
                    </p>
                    <p style={{
                      fontSize: 9, fontFamily: SY.mono,
                      color: SY.textDim, margin: '2px 0 0',
                      letterSpacing: '0.04em',
                    }}>{s.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          /* Original plan steps */
          <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
            {plan.length === 0 ? (
              <div style={{
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                height: '100%', gap: 8, textAlign: 'center',
              }}>
                <div style={{
                  fontFamily: SY.mono, fontSize: 10, letterSpacing: '0.18em',
                  color: SY.textDim, textTransform: 'uppercase',
                }}>
                  ◌ Aucun plan actif
                </div>
                <div style={{
                  fontSize: 10, color: SY.textDim, maxWidth: 180, lineHeight: 1.4,
                }}>
                  Les etapes d'execution apparaitront ici.
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {plan.map((p, i) => {
                  const isA3 = p.agent === 'agent3'
                  return (
                    <div key={i} style={{
                      padding: '8px 10px', borderRadius: 6,
                      background:
                        p.status === 'done'    ? (isA3 ? 'rgba(56,189,248,0.06)' : 'rgba(16,185,129,0.05)') :
                        p.status === 'running' ? 'rgba(245,158,11,0.05)' :
                        SY.surface,
                      border: `1px solid ${
                        p.status === 'done'    ? (isA3 ? `${AGENT3_CYAN}30` : `${SY.success}30`) :
                        p.status === 'running' ? `${SY.warn}30` :
                        SY.border
                      }`,
                      display: 'flex', alignItems: 'flex-start', gap: 8,
                    }}>
                      <span style={{
                        fontFamily: SY.mono, fontSize: 13, marginTop: -1,
                        color:
                          p.status === 'done'    ? (isA3 ? AGENT3_CYAN : SY.success) :
                          p.status === 'running' ? SY.warn : SY.textDim,
                      }}>
                        {p.status === 'done' ? '✓' : p.status === 'running' ? '◐' : '○'}
                      </span>
                      <div style={{ flex: 1 }}>
                        <p style={{
                          fontSize: 11, lineHeight: 1.3, margin: 0,
                          color:
                            p.status === 'done'    ? (isA3 ? AGENT3_CYAN : SY.success) :
                            p.status === 'running' ? SY.warn : SY.textMute,
                          fontFamily: SY.mono, letterSpacing: '0.04em',
                        }}>
                          ETAPE {String(i + 1).padStart(2, '0')}{isA3 ? ' · A3' : ''}
                        </p>
                        <p style={{
                          fontSize: 11, color: SY.text, margin: '3px 0 0',
                          lineHeight: 1.4,
                        }}>{p.step}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Sprint 2.7 — Stats real-time HUD avec sparklines */}
        <div style={{
          padding: '10px 10px 0', borderTop: `1px solid ${SY.border}`,
        }}>
          <div style={{
            fontFamily: SY.mono, fontSize: 9, letterSpacing: '0.18em',
            color: SY.textDim, textTransform: 'uppercase', marginBottom: 6,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ color: palette.cyan }}>▸</span> System HUD
          </div>
          <StatsHUD
            data={stats}
            cyan={palette.cyan}
            textMute={palette.textMute}
            textDim={palette.textDim}
            border={palette.border}
            surface={palette.surface}
            text={palette.text}
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
