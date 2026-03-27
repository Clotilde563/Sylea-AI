import { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8000'

// Logo Syléa SVG
function SyleaLogo({ size = 30, color1 = '#60a5fa', color2 = '#818cf8', color3 = '#a78bfa' }: { size?: number; color1?: string; color2?: string; color3?: string }) {
  const id = `logo-${Math.random().toString(36).slice(2, 6)}`
  return (
    <svg width={size} height={size * 1.3} viewBox="0 0 100 130" fill="none">
      <defs>
        <linearGradient id={`${id}-g1`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={color1} />
          <stop offset="100%" stopColor={color2} />
        </linearGradient>
        <linearGradient id={`${id}-g2`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={color2} />
          <stop offset="100%" stopColor={color3} />
        </linearGradient>
      </defs>
      <path d="M65 8 C85 8, 90 28, 90 42 C90 56, 75 66, 55 66 C35 66, 20 76, 20 90 C20 104, 35 118, 55 118"
        stroke={`url(#${id}-g1)`} strokeWidth="11" strokeLinecap="round" fill="none" />
      <path d="M55 8 C35 8, 25 22, 25 36 C25 50, 40 60, 50 60"
        stroke={`url(#${id}-g2)`} strokeWidth="7" strokeLinecap="round" fill="none" opacity="0.5" />
      <path d="M50 70 C60 70, 75 80, 75 94 C75 108, 60 118, 45 118"
        stroke={`url(#${id}-g2)`} strokeWidth="7" strokeLinecap="round" fill="none" opacity="0.5" />
    </svg>
  )
}

interface ActionStep {
  id: string
  action: string
  status: 'pending' | 'running' | 'done' | 'error'
  detail: string
  time: string
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
  { id: 'agent3', name: 'Sylea 3', color: '#3b82f6', colorLight: '#60a5fa', status: 'locked', unread: 0 },
  { id: 'agent4', name: 'Super Agent', color: '#8b5cf6', colorLight: '#a78bfa', status: 'locked', unread: 0 },
]

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('sylea_desktop_token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [wsConnected, setWsConnected] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState('agent2')
  const [steps, setSteps] = useState<ActionStep[]>([])
  const [plan, setPlan] = useState<Array<{ step: string; status: 'pending' | 'done' | 'running' }>>([])
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

      ws.onmessage = (event) => {
        if (event.data === 'pong') return
        try {
          const data = JSON.parse(event.data)
          if (data.message) {
            addStep(data.type || 'action', data.message, 'running')
          }
          if (data.actions?.length > 0) {
            // Build plan from actions
            setPlan(data.actions.map((a: any) => ({
              step: `${a.type}: ${a.data?.title || a.data?.to || a.data?.label || a.data?.message || ''}`,
              status: 'pending' as const,
            })))
            data.actions.forEach((action: any, idx: number) => {
              setTimeout(() => handleAction(action, idx), idx * 2000)
            })
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

  const addStep = (action: string, detail: string, status: ActionStep['status']) => {
    setSteps(prev => [...prev, {
      id: `${Date.now()}-${Math.random()}`,
      action, detail, status,
      time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    }])
  }

  const updatePlan = (idx: number, status: 'done' | 'running' | 'pending') => {
    setPlan(prev => prev.map((p, i) => i === idx ? { ...p, status } : p))
  }

  const handleAction = async (action: any, planIdx: number) => {
    updatePlan(planIdx, 'running')
    switch (action.type) {
      case 'EMAIL':
        addStep('EMAIL', `Envoi mail a ${action.data.to}...`, 'running')
        try {
          await fetch(`${API_BASE}/api/agent2/send-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(action.data),
          })
          addStep('EMAIL', `Mail envoye a ${action.data.to}`, 'done')
          updatePlan(planIdx, 'done')
        } catch {
          addStep('EMAIL', 'Erreur envoi mail', 'error')
        }
        break
      case 'TEXT': {
        addStep('TEXT', `Generation: ${action.data.title}...`, 'running')
        const blob = new Blob([action.data.content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${action.data.title || 'document'}.txt`; a.click()
        URL.revokeObjectURL(url)
        addStep('TEXT', `Fichier telecharge: ${action.data.title}`, 'done')
        updatePlan(planIdx, 'done')
        break
      }
      case 'LINK':
        addStep('LINK', `Ouverture: ${action.data.label || action.data.url}`, 'running')
        window.open(action.data.url, '_blank')
        addStep('LINK', `Lien ouvert`, 'done')
        updatePlan(planIdx, 'done')
        break
      case 'COPY':
        addStep('COPY', 'Copie presse-papier...', 'running')
        try {
          await navigator.clipboard.writeText(action.data.text)
          addStep('COPY', 'Copie dans le presse-papier', 'done')
          updatePlan(planIdx, 'done')
        } catch {
          addStep('COPY', 'Erreur copie', 'error')
        }
        break
      case 'REMINDER':
        addStep('REMINDER', `Rappel: ${action.data.message} a ${action.data.time}`, 'done')
        updatePlan(planIdx, 'done')
        break
      default:
        addStep('ACTION', JSON.stringify(action), 'done')
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

      {/* ── SIDEBAR GAUCHE : Agents ── */}
      <div style={{
        width: 200, borderRight: '1px solid rgba(255,255,255,0.05)',
        display: 'flex', flexDirection: 'column',
        background: 'rgba(255,255,255,0.01)',
      }}>
        {/* Header sidebar */}
        <div style={{ padding: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <SyleaLogo size={16} />
          <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#a5b4fc', letterSpacing: '0.08em' }}>SYLEA AGENT</span>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusDot, marginLeft: 'auto' }} />
        </div>

        {/* Agent list */}
        <div style={{ flex: 1, padding: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          {AGENTS.map(agent => (
            <button
              key={agent.id}
              onClick={() => agent.status !== 'locked' && setSelectedAgent(agent.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.5rem 0.6rem', borderRadius: '8px',
                background: selectedAgent === agent.id ? `${agent.color}12` : 'transparent',
                border: selectedAgent === agent.id ? `1px solid ${agent.color}30` : '1px solid transparent',
                cursor: agent.status === 'locked' ? 'not-allowed' : 'pointer',
                opacity: agent.status === 'locked' ? 0.3 : 1,
                transition: 'all 0.15s', width: '100%', textAlign: 'left',
              }}
            >
              <div style={{
                width: 24, height: 24, borderRadius: '50%',
                background: `${agent.color}20`, border: `1.5px solid ${agent.color}40`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.65rem', fontWeight: 700, color: agent.color,
              }}>
                {agent.id === 'agent4' ? '★' : agent.name.slice(-1)}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.72rem', fontWeight: 600, color: selectedAgent === agent.id ? agent.colorLight : '#888' }}>
                  {agent.name}
                </div>
                <div style={{ fontSize: '0.58rem', color: '#444' }}>
                  {agent.status === 'active' ? '● Actif' : agent.status === 'locked' ? '🔒 Verrouille' : '○ Inactif'}
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
          ))}
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

      {/* ── CENTRE : Actions en cours ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid rgba(255,255,255,0.05)' }}>
        {/* Header centre */}
        <div style={{
          padding: '0.6rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', gap: '0.5rem',
        }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ccc' }}>Actions en cours</span>
          <span style={{ fontSize: '0.6rem', color: '#555', background: 'rgba(255,255,255,0.03)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
            {steps.length} etape{steps.length > 1 ? 's' : ''}
          </span>
        </div>

        {/* Steps list */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0.75rem' }}>
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
                const icons: Record<string, string> = { EMAIL: '📧', TEXT: '📝', LINK: '🔗', COPY: '📋', REMINDER: '⏰', info: 'ℹ️', action: '⚡' }
                const statusColors: Record<string, string> = { done: '#4ade80', running: '#fbbf24', error: '#f87171', pending: '#666' }
                return (
                  <div key={step.id} style={{
                    display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
                    padding: '0.4rem 0.6rem', borderRadius: '8px',
                    background: step.status === 'error' ? 'rgba(239,68,68,0.05)' : step.status === 'done' ? 'rgba(34,197,94,0.03)' : 'rgba(255,255,255,0.02)',
                    border: `1px solid ${step.status === 'error' ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.03)'}`,
                  }}>
                    <span style={{ fontSize: '0.75rem', marginTop: '0.05rem' }}>{icons[step.action] || '•'}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontSize: '0.75rem', color: '#bbb', lineHeight: 1.4, margin: 0 }}>{step.detail}</p>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexShrink: 0 }}>
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

      {/* ── DROITE : Plan d'exécution ── */}
      <div style={{ width: 220, display: 'flex', flexDirection: 'column' }}>
        {/* Header droite */}
        <div style={{
          padding: '0.6rem 0.75rem', borderBottom: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', gap: '0.4rem',
        }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#ccc' }}>Plan</span>
          {plan.length > 0 && (
            <span style={{ fontSize: '0.6rem', color: '#4ade80', background: 'rgba(34,197,94,0.08)', padding: '0.1rem 0.4rem', borderRadius: '8px' }}>
              {plan.filter(p => p.status === 'done').length}/{plan.length}
            </span>
          )}
        </div>

        {/* Plan steps */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0.5rem' }}>
          {plan.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#333' }}>
              <p style={{ fontSize: '0.7rem', color: '#444', textAlign: 'center' }}>Aucun plan en cours</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {plan.map((p, i) => (
                <div key={i} style={{
                  padding: '0.45rem 0.55rem', borderRadius: '8px',
                  background: p.status === 'done' ? 'rgba(34,197,94,0.05)' : p.status === 'running' ? 'rgba(251,191,36,0.05)' : 'rgba(255,255,255,0.02)',
                  border: `1px solid ${p.status === 'done' ? 'rgba(34,197,94,0.12)' : p.status === 'running' ? 'rgba(251,191,36,0.12)' : 'rgba(255,255,255,0.04)'}`,
                  display: 'flex', alignItems: 'flex-start', gap: '0.4rem',
                }}>
                  <span style={{ fontSize: '0.7rem', marginTop: '0.05rem' }}>
                    {p.status === 'done' ? '✓' : p.status === 'running' ? '⟳' : '○'}
                  </span>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: '0.68rem', color: p.status === 'done' ? '#4ade80' : '#999', lineHeight: 1.4, margin: 0 }}>
                      Etape {i + 1}
                    </p>
                    <p style={{ fontSize: '0.6rem', color: '#555', margin: '0.1rem 0 0' }}>{p.step}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Status footer */}
        <div style={{ padding: '0.4rem 0.75rem', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: '0.55rem', color: '#2a2a2a', textAlign: 'center' }}>
          v1.0
        </div>
      </div>
    </div>
  )
}

export default App
