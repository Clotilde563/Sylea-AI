import { useState, useEffect, useRef } from 'react'
import { invoke } from '@tauri-apps/api/core'
import OpenClawOnboarding from './OpenClawOnboarding'

const API_BASE = 'http://localhost:8000'

// ── Syléa S logo path (identique a l'app web) ──────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

// Logo Syléa SVG — logo original (violet/indigo par defaut)
function SyleaLogo({ size = 30, color1 = '#60a5fa', color2 = '#818cf8', color3 = '#a78bfa' }: { size?: number; color1?: string; color2?: string; color3?: string }) {
  const id = `logo-${Math.random().toString(36).slice(2, 6)}`
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" fill="none">
      <defs>
        <linearGradient id={`${id}-g`} x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={color1} />
          <stop offset="50%" stopColor={color2} />
          <stop offset="100%" stopColor={color3} />
        </linearGradient>
        <filter id={`${id}-blur`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      <path d={S_PATH} stroke={`url(#${id}-g)`} strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: `url(#${id}-blur)`, opacity: 0.18 }} />
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke={`url(#${id}-g)`} strokeWidth="46" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="rgba(255,230,240,0.35)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

// Logo Agent 3 — bleu & or scintillant avec animations SVG natives
// Les couleurs du gradient bougent reellement (animate sur les stops)
function Agent3Logo({ size = 30 }: { size?: number }) {
  const id = `a3-${Math.random().toString(36).slice(2, 6)}`
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" fill="none" style={{ overflow: 'visible' }}>
      <defs>
        {/* Gradient principal — les stops s'animent entre bleu et or */}
        <linearGradient id={`${id}-g`} x1="0%" y1="100%" x2="100%" y2="0%">
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
        {/* Gradient du halo — meme animation */}
        <linearGradient id={`${id}-glow`} x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%">
            <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="50%">
            <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%">
            <animate attributeName="stop-color" values="#fbbf24;#1e3a5f;#fbbf24" dur="3s" repeatCount="indefinite" />
          </stop>
        </linearGradient>
        <filter id={`${id}-blur`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="20" />
        </filter>
        {/* Reflet blanc anime */}
        <linearGradient id={`${id}-shine`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%">
            <animate attributeName="stop-color" values="rgba(255,230,200,0.6);rgba(200,220,255,0.3);rgba(255,230,200,0.6)" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%">
            <animate attributeName="stop-color" values="rgba(200,220,255,0.3);rgba(255,230,200,0.6);rgba(200,220,255,0.3)" dur="3s" repeatCount="indefinite" />
          </stop>
        </linearGradient>
      </defs>
      {/* Halo diffus */}
      <path d={S_PATH} stroke={`url(#${id}-glow)`} strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: `url(#${id}-blur)`, opacity: 0.22 }} />
      {/* Fond noir interieur */}
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      {/* Trait principal colore — anime */}
      <path d={S_PATH} stroke={`url(#${id}-g)`} strokeWidth="46" fill="none" strokeLinecap="round" />
      {/* Reflet brillant anime */}
      <path d={S_PATH} stroke={`url(#${id}-shine)`} strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
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
  status: 'active' | 'inactive' | 'locked'
  unread: number
}

const AGENTS: AgentInfo[] = [
  { id: 'agent1', name: 'Sylea 1', color: '#f59e0b', colorLight: '#fbbf24', status: 'active', unread: 0 },
  { id: 'agent2', name: 'Sylea 2', color: '#ef4444', colorLight: '#f87171', status: 'inactive', unread: 0 },
  { id: 'agent3', name: 'Sylea 3', color: '#3b82f6', colorLight: '#60a5fa', status: 'inactive', unread: 0 },
  { id: 'agent4', name: 'Super Agent', color: '#8b5cf6', colorLight: '#a78bfa', status: 'locked', unread: 0 },
]

// Agent 3 color constants
const AGENT3_BLUE = '#3b82f6'
const AGENT3_GOLD = '#f59e0b'

function App() {
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

  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps])

  // Login
  const handleLogin = async () => {
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (data.access_token) {
        setToken(data.access_token)
        localStorage.setItem('sylea_desktop_token', data.access_token)
      } else {
        setError(data.detail || 'Identifiants incorrects')
      }
    } catch {
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
            if ('Notification' in window && Notification.permission === 'granted') {
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
        try {
          const data = JSON.parse(event.data)
          const sourceAgent = data.agent || 'agent2'  // Default to agent2 for backward compat
          const agentLabel = sourceAgent === 'agent3' ? '[Agent 3]' : '[Agent 2]'

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
      case 'SEARCH': {
        addStep('SEARCH', `${tag}Recherche: ${action.data?.query || 'web'}`, 'done', sourceAgent)
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

  // ── ONBOARDING OPENCLAW (Phase 2b) ──
  // Affichage bloquant au 1er lancement : wizard qui installe OpenClaw,
  // genere le token gateway et propose 5 skills ClawHub pre-coches.
  if (isOnboarded === null) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        minHeight: '100vh', background: '#050810', color: '#a78bfa', fontSize: '0.85rem',
      }}>
        Initialisation…
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
        background: 'radial-gradient(ellipse at 50% 30%, rgba(139,92,246,0.06) 0%, #050810 70%)',
      }}>
        <div style={{ marginBottom: '1rem' }}>
          <SyleaLogo size={50} color1="#818cf8" color2="#a78bfa" color3="#c4b5fd" />
        </div>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 800, letterSpacing: '0.12em', marginBottom: '0.2rem' }}>
          <span style={{ color: '#a5b4fc' }}>SYLEA</span>
          <span style={{ color: '#818cf8', marginLeft: '0.3rem' }}>AGENT</span>
        </h1>
        <p style={{ color: '#555', marginBottom: '2rem', fontSize: '0.72rem', letterSpacing: '0.08em' }}>DESKTOP COMPANION</p>

        <div style={{
          background: 'rgba(139,92,246,0.03)', border: '1px solid rgba(139,92,246,0.1)',
          borderRadius: '16px', padding: '1.5rem', width: '100%', maxWidth: '340px',
        }}>
          {error && <div style={{ color: '#fca5a5', fontSize: '0.78rem', marginBottom: '1rem', padding: '0.5rem', background: 'rgba(239,68,68,0.08)', borderRadius: '8px', textAlign: 'center' }}>{error}</div>}

          <label style={{ fontSize: '0.68rem', color: '#666', display: 'block', marginBottom: '0.2rem', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="votre@email.com"
            style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '10px', border: '1px solid rgba(139,92,246,0.12)', background: 'rgba(255,255,255,0.03)', color: '#e8e8f0', marginBottom: '0.7rem', fontSize: '0.85rem' }} />

          <label style={{ fontSize: '0.68rem', color: '#666', display: 'block', marginBottom: '0.2rem', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Mot de passe</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            style={{ width: '100%', padding: '0.6rem 0.8rem', borderRadius: '10px', border: '1px solid rgba(139,92,246,0.12)', background: 'rgba(255,255,255,0.03)', color: '#e8e8f0', marginBottom: '1.25rem', fontSize: '0.85rem' }} />

          <button onClick={handleLogin} style={{
            width: '100%', padding: '0.7rem', borderRadius: '10px', border: 'none',
            background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', color: 'white',
            fontWeight: 700, fontSize: '0.88rem', cursor: 'pointer', letterSpacing: '0.04em',
          }}>Se connecter</button>
        </div>
      </div>
    )
  }

  // ── DASHBOARD 3 COLONNES ──
  const statusDot = wsConnected ? '#4ade80' : '#f87171'

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#050810', overflow: 'hidden' }}>

      {/* CSS animations — Agent 3 shimmer bleu & or */}
      <style>{`
        @keyframes agent3-border-glow {
          0%, 100% {
            border-color: rgba(37,99,235,0.3);
            box-shadow: 0 0 8px rgba(37,99,235,0.12), inset 0 0 6px rgba(212,160,23,0.04);
          }
          50% {
            border-color: rgba(212,160,23,0.35);
            box-shadow: 0 0 12px rgba(245,158,11,0.15), inset 0 0 10px rgba(37,99,235,0.06);
          }
        }
        .agent3-name-shimmer {
          background: linear-gradient(90deg, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f, #2563eb);
          background-size: 300% 100%;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          animation: agent3-name-flow 3s ease-in-out infinite;
        }
        @keyframes agent3-name-flow {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        .agent3-status-shimmer {
          animation: agent3-status-pulse 3s ease-in-out infinite;
        }
        @keyframes agent3-status-pulse {
          0%, 100% { color: rgba(37,99,235,0.5); }
          50% { color: rgba(212,160,23,0.6); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>

      {/* ── SIDEBAR GAUCHE : Agents ── */}
      <div style={{
        width: 200, borderRight: '1px solid rgba(255,255,255,0.05)',
        display: 'flex', flexDirection: 'column',
        background: 'rgba(255,255,255,0.01)',
      }}>
        {/* Header sidebar */}
        <div style={{ padding: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <SyleaLogo size={18} />
          <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#a5b4fc', letterSpacing: '0.08em' }}>SYLEA AGENT</span>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusDot, marginLeft: 'auto' }} />
        </div>

        {/* Agent list */}
        <div style={{ flex: 1, padding: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          {AGENTS.map(agent => {
            const isAgent3 = agent.id === 'agent3'
            const isSelected = selectedAgent === agent.id
            return (
              <button
                key={agent.id}
                onClick={() => agent.status !== 'locked' && setSelectedAgent(agent.id)}
                className={isAgent3 && isSelected ? 'agent3-sidebar-btn' : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.5rem',
                  padding: '0.5rem 0.6rem', borderRadius: '8px',
                  background: isSelected
                    ? (isAgent3
                      ? 'linear-gradient(135deg, rgba(37,99,235,0.08), rgba(212,160,23,0.04), rgba(5,8,16,0.9))'
                      : `${agent.color}12`)
                    : 'transparent',
                  border: isSelected
                    ? (isAgent3 ? '1px solid rgba(37,99,235,0.25)' : `1px solid ${agent.color}30`)
                    : '1px solid transparent',
                  cursor: agent.status === 'locked' ? 'not-allowed' : 'pointer',
                  opacity: agent.status === 'locked' ? 0.3 : 1,
                  transition: 'all 0.15s', width: '100%', textAlign: 'left',
                  ...(isAgent3 && isSelected ? { animation: 'agent3-border-glow 3s ease-in-out infinite' } : {}),
                }}
              >
                {/* Logo avatar */}
                {isAgent3 ? (
                  <div style={{ width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <Agent3Logo size={22} />
                  </div>
                ) : (
                  <div style={{
                    width: 24, height: 24, borderRadius: '50%',
                    background: `${agent.color}20`, border: `1.5px solid ${agent.color}40`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.65rem', fontWeight: 700, color: agent.color,
                  }}>
                    {agent.id === 'agent4' ? '★' : agent.name.slice(-1)}
                  </div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  {isAgent3 ? (
                    <div className={isSelected ? 'agent3-name-shimmer' : undefined}
                      style={{
                        fontSize: '0.72rem', fontWeight: 700,
                        ...(isSelected ? {} : { color: '#888' }),
                      }}>
                      {agent.name}
                    </div>
                  ) : (
                    <div style={{ fontSize: '0.72rem', fontWeight: 600, color: isSelected ? agent.colorLight : '#888' }}>
                      {agent.name}
                    </div>
                  )}
                  <div className={isAgent3 ? 'agent3-status-shimmer' : undefined}
                    style={{ fontSize: '0.58rem', color: isAgent3 ? undefined : '#444', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    {agent.status === 'active' ? '● Actif' : agent.status === 'locked' ? '🔒 Verrouille' : '○ Inactif'}
                    {isAgent3 && (
                      <span style={{
                        width: 5, height: 5, borderRadius: '50%',
                        background: openclawConnected ? '#4ade80' : '#f59e0b',
                        display: 'inline-block', marginLeft: '0.15rem',
                        boxShadow: openclawConnected ? '0 0 4px rgba(74,222,128,0.5)' : 'none',
                      }} title={openclawConnected ? 'OpenClaw connecte' : 'OpenClaw — fallback Claude'} />
                    )}
                  </div>
                </div>
                {agent.unread > 0 && (
                  <span style={{
                    width: 16, height: 16, borderRadius: '50%', background: agent.color,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.55rem', fontWeight: 700, color: 'white',
                  }}>{agent.unread}</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Footer sidebar */}
        <div style={{ padding: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          <button onClick={handleLogout} style={{
            width: '100%', padding: '0.35rem', borderRadius: '6px',
            background: 'none', border: '1px solid rgba(239,68,68,0.15)',
            color: '#f87171', fontSize: '0.65rem', cursor: 'pointer',
          }}>Deconnexion</button>
        </div>
      </div>

      {/* ── CENTRE : Actions en cours / Agent 3 Log ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid rgba(255,255,255,0.05)' }}>
        {/* Header centre */}
        <div style={{
          padding: '0.6rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', gap: '0.5rem',
        }}>
          {selectedAgent === 'agent3' && agent3Logs.length > 0 ? (
            <>
              <span className="agent3-name-shimmer" style={{ fontSize: '0.8rem', fontWeight: 700 }}>Agent 3 — Execution</span>
              <span style={{ fontSize: '0.6rem', color: AGENT3_BLUE, background: 'rgba(59,130,246,0.08)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
                {agent3Logs.length} log{agent3Logs.length > 1 ? 's' : ''}
              </span>
              <div style={{ flex: 1 }} />
              <button onClick={() => setAgent3Logs([])} style={{
                background: 'none', border: 'none', color: '#555', fontSize: '0.6rem', cursor: 'pointer',
              }}>Effacer</button>
            </>
          ) : (
            <>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ccc' }}>Actions en cours</span>
              <span style={{ fontSize: '0.6rem', color: '#555', background: 'rgba(255,255,255,0.03)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
                {steps.length} etape{steps.length > 1 ? 's' : ''}
              </span>
            </>
          )}
        </div>

        {/* Agent 3 Claude Code-like log panel */}
        {selectedAgent === 'agent3' && agent3Logs.length > 0 && (
          <div style={{
            flex: 1, overflow: 'auto', padding: '0.5rem 0.75rem',
            background: 'rgba(0,0,0,0.3)',
            fontFamily: "'Fira Code', 'Cascadia Code', 'Consolas', monospace",
          }}>
            {agent3Logs.map((log, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
                padding: '0.2rem 0.4rem', borderRadius: '4px',
                fontSize: '0.72rem', lineHeight: 1.5,
                background: log.type === 'tool' ? 'rgba(212,160,23,0.03)' : 'transparent',
                borderLeft: log.type === 'tool' ? `2px solid ${AGENT3_GOLD}`
                  : log.type === 'success' ? '2px solid #10b981'
                  : log.type === 'error' ? '2px solid #ef4444'
                  : '2px solid transparent',
              }}>
                <span style={{ color: 'rgba(255,255,255,0.2)', flexShrink: 0, fontSize: '0.62rem', minWidth: '5rem' }}>
                  {log.time}
                </span>
                <span style={{
                  color: log.type === 'success' ? '#10b981'
                    : log.type === 'tool' ? AGENT3_GOLD
                    : log.type === 'warning' ? '#f59e0b'
                    : log.type === 'error' ? '#ef4444'
                    : 'rgba(255,255,255,0.55)',
                }}>
                  {log.type === 'tool' && <span style={{ color: AGENT3_BLUE, marginRight: '0.3rem' }}>⚡</span>}
                  {log.type === 'success' && <span style={{ marginRight: '0.3rem' }}>✓</span>}
                  {log.type === 'error' && <span style={{ marginRight: '0.3rem' }}>✗</span>}
                  {log.text}
                </span>
              </div>
            ))}
            <div ref={agent3LogEndRef} />
          </div>
        )}

        {/* Steps list — hidden when Agent 3 log is shown */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0.75rem', display: (selectedAgent === 'agent3' && agent3Logs.length > 0) ? 'none' : 'block' }}>
          {steps.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#333' }}>
              <div style={{ opacity: 0.2, marginBottom: '0.75rem' }}>
                <SyleaLogo size={35} />
              </div>
              <p style={{ fontSize: '0.78rem', color: '#555' }}>En attente d'instructions...</p>
              <p style={{ fontSize: '0.62rem', color: '#333', marginTop: '0.25rem' }}>Envoyez une commande depuis l'app web</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {steps.map((step) => {
                const icons: Record<string, string> = { EMAIL: '📧', TEXT: '📝', LINK: '🔗', COPY: '📋', REMINDER: '⏰', SEARCH: '🔍', X_SEARCH: '𝕏', ANALYSIS: '📊', info: 'ℹ️', action: '⚡' }
                const statusColors: Record<string, string> = { done: '#4ade80', running: '#fbbf24', error: '#f87171', pending: '#666' }
                const agentBorderColor = step.agent === 'agent3' ? 'rgba(59,130,246,0.15)' : step.agent === 'agent2' ? 'rgba(239,68,68,0.08)' : 'rgba(255,255,255,0.03)'
                const agentBg = step.agent === 'agent3'
                  ? (step.status === 'error' ? 'rgba(239,68,68,0.05)' : step.status === 'done' ? 'rgba(59,130,246,0.04)' : 'rgba(59,130,246,0.02)')
                  : (step.status === 'error' ? 'rgba(239,68,68,0.05)' : step.status === 'done' ? 'rgba(34,197,94,0.03)' : 'rgba(255,255,255,0.02)')
                return (
                  <div key={step.id} style={{
                    display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
                    padding: '0.4rem 0.6rem', borderRadius: '8px',
                    background: agentBg,
                    border: `1px solid ${step.status === 'error' ? 'rgba(239,68,68,0.1)' : agentBorderColor}`,
                  }}>
                    <span style={{ fontSize: '0.75rem', marginTop: '0.05rem' }}>{icons[step.action] || '•'}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontSize: '0.75rem', color: '#bbb', lineHeight: 1.4, margin: 0 }}>{step.detail}</p>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexShrink: 0 }}>
                      {step.agent === 'agent3' && <div style={{ width: 4, height: 4, borderRadius: '50%', background: AGENT3_BLUE, opacity: 0.6 }} />}
                      <div style={{ width: 5, height: 5, borderRadius: '50%', background: statusColors[step.status] }} />
                      <span style={{ fontSize: '0.55rem', color: '#444' }}>{step.time}</span>
                    </div>
                  </div>
                )
              })}
              <div ref={stepsEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* ── DROITE : Plan d'exécution / Taches Agent 3 ── */}
      <div style={{ width: 220, display: 'flex', flexDirection: 'column' }}>
        {/* Header droite */}
        <div style={{
          padding: '0.6rem 0.75rem', borderBottom: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', gap: '0.4rem',
        }}>
          {selectedAgent === 'agent3' && agent3StreamSteps.length > 0 ? (
            <>
              <span className="agent3-name-shimmer" style={{ fontSize: '0.8rem', fontWeight: 700 }}>Taches</span>
              <span style={{ fontSize: '0.6rem', color: AGENT3_BLUE, background: 'rgba(59,130,246,0.08)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
                {agent3StreamSteps.filter(s => s.status === 'done').length}/{agent3StreamSteps.length}
              </span>
            </>
          ) : (
            <>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ccc' }}>Plan</span>
              {plan.length > 0 && (
                <span style={{ fontSize: '0.6rem', color: '#4ade80', background: 'rgba(34,197,94,0.08)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
                  {plan.filter(p => p.status === 'done').length}/{plan.length}
                </span>
              )}
            </>
          )}
        </div>

        {/* Agent 3 streaming steps with progress bar */}
        {selectedAgent === 'agent3' && agent3StreamSteps.length > 0 ? (
          <div style={{ flex: 1, overflow: 'auto', padding: '0.5rem' }}>
            {/* Progress bar */}
            <div style={{ padding: '0 0.25rem 0.5rem' }}>
              <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.04)', overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 2,
                  background: `linear-gradient(90deg, ${AGENT3_BLUE}, ${AGENT3_GOLD}, ${AGENT3_BLUE})`,
                  backgroundSize: '200% 100%',
                  animation: 'agent3-border-glow 3s ease-in-out infinite',
                  width: `${Math.round((agent3StreamSteps.filter(s => s.status === 'done').length / agent3StreamSteps.length) * 100)}%`,
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
            {/* Steps list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              {agent3StreamSteps.map((s) => (
                <div key={s.id} style={{
                  padding: '0.4rem 0.5rem', borderRadius: '8px',
                  background: s.status === 'running' ? 'rgba(59,130,246,0.06)'
                    : s.status === 'done' ? 'rgba(16,185,129,0.04)' : 'rgba(255,255,255,0.02)',
                  border: `1px solid ${s.status === 'running' ? 'rgba(59,130,246,0.15)'
                    : s.status === 'done' ? 'rgba(16,185,129,0.12)' : 'rgba(255,255,255,0.04)'}`,
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  transition: 'all 0.3s',
                }}>
                  {/* Status indicator */}
                  <div style={{ width: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    {s.status === 'done' && (
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                    )}
                    {s.status === 'running' && (
                      <div style={{
                        width: 12, height: 12, borderRadius: '50%',
                        border: '2px solid transparent',
                        borderTopColor: AGENT3_BLUE, borderRightColor: AGENT3_GOLD,
                        animation: 'spin 0.8s linear infinite',
                      }} />
                    )}
                    {s.status === 'pending' && (
                      <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'rgba(255,255,255,0.12)' }} />
                    )}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{
                      fontSize: '0.68rem', margin: 0, lineHeight: 1.3,
                      fontWeight: s.status === 'running' ? 600 : 400,
                      color: s.status === 'running' ? '#60a5fa' : s.status === 'done' ? '#10b981' : '#666',
                    }}>
                      {s.label}
                    </p>
                    <p style={{ fontSize: '0.58rem', color: '#444', margin: '0.1rem 0 0' }}>{s.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          /* Original plan steps */
          <div style={{ flex: 1, overflow: 'auto', padding: '0.5rem' }}>
            {plan.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#333' }}>
                <p style={{ fontSize: '0.7rem', color: '#444', textAlign: 'center' }}>Aucun plan en cours</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                {plan.map((p, i) => {
                  const isA3 = p.agent === 'agent3'
                  return (
                    <div key={i} style={{
                      padding: '0.45rem 0.55rem', borderRadius: '8px',
                      background: p.status === 'done'
                        ? (isA3 ? 'rgba(59,130,246,0.06)' : 'rgba(34,197,94,0.05)')
                        : p.status === 'running' ? 'rgba(251,191,36,0.05)' : 'rgba(255,255,255,0.02)',
                      border: `1px solid ${p.status === 'done'
                        ? (isA3 ? 'rgba(59,130,246,0.15)' : 'rgba(34,197,94,0.12)')
                        : p.status === 'running' ? 'rgba(251,191,36,0.12)' : 'rgba(255,255,255,0.04)'}`,
                      display: 'flex', alignItems: 'flex-start', gap: '0.4rem',
                    }}>
                      <span style={{ fontSize: '0.7rem', marginTop: '0.05rem', color: isA3 && p.status === 'done' ? AGENT3_BLUE : undefined }}>
                        {p.status === 'done' ? '✓' : p.status === 'running' ? '⟳' : '○'}
                      </span>
                      <div style={{ flex: 1 }}>
                        <p style={{ fontSize: '0.68rem', color: p.status === 'done' ? (isA3 ? '#60a5fa' : '#4ade80') : '#999', lineHeight: 1.4, margin: 0 }}>
                          Etape {i + 1}{isA3 ? ' (Agent 3)' : ''}
                        </p>
                        <p style={{ fontSize: '0.6rem', color: '#555', margin: '0.1rem 0 0' }}>{p.step}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Status footer */}
        <div style={{
          padding: '0.4rem 0.75rem', borderTop: '1px solid rgba(255,255,255,0.05)',
          fontSize: '0.55rem', color: '#2a2a2a', textAlign: 'center',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem',
        }}>
          <span>v1.0</span>
          <span style={{ color: '#333' }}>|</span>
          <span style={{
            display: 'flex', alignItems: 'center', gap: '0.2rem',
            color: openclawConnected ? '#4ade80' : '#555',
          }}>
            <span style={{
              width: 4, height: 4, borderRadius: '50%',
              background: openclawConnected ? '#4ade80' : '#555',
              boxShadow: openclawConnected ? '0 0 4px rgba(74,222,128,0.4)' : 'none',
            }} />
            OpenClaw
          </span>
        </div>
      </div>
    </div>
  )
}

export default App
