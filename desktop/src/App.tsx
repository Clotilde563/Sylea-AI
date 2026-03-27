import { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8000'

interface ActionMessage {
  type: string
  content: string
  time: string
  status?: 'success' | 'error' | 'info' | 'pending'
}

// Logo Syléa SVG — variantes rouges pour le desktop
function SyleaDesktopLogo({ size = 60 }: { size?: number }) {
  return (
    <svg width={size} height={size * 1.4} viewBox="0 0 100 140" fill="none">
      <defs>
        <linearGradient id="desk-grad1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f87171" />
          <stop offset="50%" stopColor="#ef4444" />
          <stop offset="100%" stopColor="#dc2626" />
        </linearGradient>
        <linearGradient id="desk-grad2" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#dc2626" />
          <stop offset="100%" stopColor="#991b1b" />
        </linearGradient>
        <filter id="desk-glow">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M65 10 C85 10, 90 30, 90 45 C90 60, 75 70, 55 70 C35 70, 20 80, 20 95 C20 110, 35 125, 55 125"
        stroke="url(#desk-grad1)" strokeWidth="12" strokeLinecap="round" fill="none"
        filter="url(#desk-glow)"
      />
      <path
        d="M55 10 C35 10, 25 25, 25 40 C25 55, 40 65, 50 65"
        stroke="url(#desk-grad2)" strokeWidth="8" strokeLinecap="round" fill="none"
        opacity="0.6"
      />
      <path
        d="M50 75 C60 75, 75 85, 75 100 C75 115, 60 125, 45 125"
        stroke="url(#desk-grad2)" strokeWidth="8" strokeLinecap="round" fill="none"
        opacity="0.6"
      />
    </svg>
  )
}

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('sylea_desktop_token'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [wsConnected, setWsConnected] = useState(false)
  const [messages, setMessages] = useState<ActionMessage[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
      setError('Impossible de se connecter. Verifiez que l\'API tourne sur localhost:8000')
    }
  }

  useEffect(() => {
    if (!token) return

    let reconnectAttempts = 0
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let isCleaningUp = false
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
          addMessage('success', 'Connecte au serveur Sylea.AI')
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
          addMessage('pending', data.message || 'Action recue...')
          if (data.actions?.length > 0) {
            data.actions.forEach((action: any) => handleAction(action))
          }
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        setWsConnected(false)
        if (isCleaningUp) return
        // Exponential backoff: 5s, 10s, 20s, max 60s
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

  const addMessage = (status: ActionMessage['status'], content: string) => {
    setMessages(prev => [...prev, {
      type: 'action', content,
      time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
      status,
    }])
  }

  const handleAction = async (action: any) => {
    switch (action.type) {
      case 'EMAIL':
        addMessage('pending', `Envoi du mail a ${action.data.to}...`)
        try {
          await fetch(`${API_BASE}/api/agent2/send-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify(action.data),
          })
          addMessage('success', `Email envoye a ${action.data.to}`)
        } catch {
          addMessage('error', 'Erreur envoi email')
        }
        break
      case 'TEXT': {
        const blob = new Blob([action.data.content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${action.data.title || 'document'}.txt`; a.click()
        URL.revokeObjectURL(url)
        addMessage('success', `Fichier telecharge: ${action.data.title}`)
        break
      }
      case 'LINK':
        window.open(action.data.url, '_blank')
        addMessage('success', `Lien ouvert: ${action.data.label || action.data.url}`)
        break
      case 'COPY':
        try {
          await navigator.clipboard.writeText(action.data.text)
          addMessage('success', 'Copie dans le presse-papier')
        } catch {
          addMessage('error', 'Erreur copie')
        }
        break
      case 'REMINDER':
        addMessage('info', `Rappel: ${action.data.message} a ${action.data.time}`)
        break
      default:
        addMessage('info', `Action: ${JSON.stringify(action)}`)
    }
  }

  const handleLogout = () => {
    wsRef.current?.close()
    setToken(null)
    localStorage.removeItem('sylea_desktop_token')
    setMessages([])
    setWsConnected(false)
  }

  // ── LOGIN ──
  if (!token) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        minHeight: '100vh', padding: '2rem',
        background: 'radial-gradient(ellipse at 50% 30%, rgba(239,68,68,0.08) 0%, #050810 70%)',
      }}>
        <div style={{ marginBottom: '1rem', animation: 'float 3s ease-in-out infinite' }}>
          <SyleaDesktopLogo size={50} />
        </div>

        <h1 style={{
          fontSize: '1.5rem', fontWeight: 800, marginBottom: '0.25rem', letterSpacing: '0.15em',
        }}>
          <span style={{ color: '#f87171' }}>SYLEA</span>
          <span style={{ color: '#ef4444', marginLeft: '0.3rem' }}>AGENT</span>
        </h1>
        <p style={{ color: '#555', marginBottom: '2rem', fontSize: '0.75rem', letterSpacing: '0.08em' }}>
          VOTRE ASSISTANT DESKTOP
        </p>

        <div style={{
          background: 'rgba(239,68,68,0.03)', border: '1px solid rgba(239,68,68,0.1)',
          borderRadius: '16px', padding: '1.5rem', width: '100%', maxWidth: '340px',
          boxShadow: '0 8px 32px rgba(239,68,68,0.05)',
        }}>
          {error && (
            <div style={{
              color: '#fca5a5', fontSize: '0.78rem', marginBottom: '1rem',
              padding: '0.5rem 0.75rem', background: 'rgba(239,68,68,0.08)',
              borderRadius: '10px', border: '1px solid rgba(239,68,68,0.12)',
              textAlign: 'center',
            }}>{error}</div>
          )}

          <label style={{ fontSize: '0.7rem', color: '#666', display: 'block', marginBottom: '0.25rem', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Email</label>
          <input
            type="email" value={email} onChange={e => setEmail(e.target.value)}
            placeholder="votre@email.com"
            style={{
              width: '100%', padding: '0.65rem 0.85rem', borderRadius: '10px',
              border: '1px solid rgba(239,68,68,0.12)', background: 'rgba(255,255,255,0.03)',
              color: '#e8e8f0', marginBottom: '0.75rem', fontSize: '0.85rem',
              transition: 'border-color 0.2s',
            }}
            onFocus={e => e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)'}
            onBlur={e => e.currentTarget.style.borderColor = 'rgba(239,68,68,0.12)'}
          />

          <label style={{ fontSize: '0.7rem', color: '#666', display: 'block', marginBottom: '0.25rem', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Mot de passe</label>
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            style={{
              width: '100%', padding: '0.65rem 0.85rem', borderRadius: '10px',
              border: '1px solid rgba(239,68,68,0.12)', background: 'rgba(255,255,255,0.03)',
              color: '#e8e8f0', marginBottom: '1.5rem', fontSize: '0.85rem',
              transition: 'border-color 0.2s',
            }}
            onFocus={e => e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)'}
            onBlur={e => e.currentTarget.style.borderColor = 'rgba(239,68,68,0.12)'}
          />

          <button onClick={handleLogin} style={{
            width: '100%', padding: '0.75rem', borderRadius: '12px', border: 'none',
            background: 'linear-gradient(135deg, #ef4444, #dc2626)',
            color: 'white', fontWeight: 700, fontSize: '0.9rem', cursor: 'pointer',
            boxShadow: '0 4px 16px rgba(239,68,68,0.3)',
            transition: 'all 0.2s', letterSpacing: '0.04em',
          }}
          onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
          onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
          >
            Se connecter
          </button>
        </div>

        <p style={{ fontSize: '0.6rem', color: '#333', marginTop: '1.5rem', textAlign: 'center' }}>
          Connectez-vous avec votre compte Sylea.AI
        </p>

        <style>{`
          @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-8px); }
          }
        `}</style>
      </div>
    )
  }

  // ── DASHBOARD ──
  const statusIcon = wsConnected ? '●' : '○'
  const statusColor = wsConnected ? '#4ade80' : '#f87171'
  const statusText = wsConnected ? 'Connecte' : 'Deconnecte'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#050810' }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '0.6rem 1rem',
        borderBottom: '1px solid rgba(239,68,68,0.08)',
        background: 'linear-gradient(180deg, rgba(239,68,68,0.04) 0%, transparent 100%)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <SyleaDesktopLogo size={18} />
          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#f87171', letterSpacing: '0.08em' }}>SYLEA AGENT</span>
          <span style={{
            fontSize: '0.55rem', fontWeight: 600, padding: '0.1rem 0.4rem', borderRadius: '999px',
            background: `${statusColor}15`, color: statusColor,
            border: `1px solid ${statusColor}30`,
          }}>
            {statusIcon} {statusText}
          </span>
        </div>
        <button onClick={handleLogout} style={{
          background: 'none', border: '1px solid rgba(239,68,68,0.15)',
          color: '#f87171', padding: '0.2rem 0.55rem', borderRadius: '8px',
          fontSize: '0.65rem', cursor: 'pointer', transition: 'all 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.08)'}
        onMouseLeave={e => e.currentTarget.style.background = 'none'}
        >
          Deconnexion
        </button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        {messages.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            flex: 1, color: '#444',
          }}>
            <div style={{ marginBottom: '1rem', opacity: 0.3 }}>
              <SyleaDesktopLogo size={40} />
            </div>
            <p style={{ fontSize: '0.82rem', color: '#555', fontWeight: 500 }}>En attente d'actions...</p>
            <p style={{ fontSize: '0.68rem', color: '#3a3a3a', marginTop: '0.3rem', textAlign: 'center', lineHeight: 1.5 }}>
              Envoyez un message a l'Agent 2<br />depuis l'app web Sylea.AI
            </p>
          </div>
        ) : (
          messages.map((msg, i) => {
            const colors = {
              success: { bg: 'rgba(34,197,94,0.05)', border: 'rgba(34,197,94,0.12)', icon: '✓' },
              error: { bg: 'rgba(239,68,68,0.05)', border: 'rgba(239,68,68,0.12)', icon: '✕' },
              pending: { bg: 'rgba(251,191,36,0.05)', border: 'rgba(251,191,36,0.12)', icon: '⟳' },
              info: { bg: 'rgba(96,165,250,0.05)', border: 'rgba(96,165,250,0.12)', icon: 'ℹ' },
            }
            const c = colors[msg.status || 'info']
            return (
              <div key={i} style={{
                padding: '0.45rem 0.7rem', borderRadius: '10px',
                background: c.bg, border: `1px solid ${c.border}`,
                display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
              }}>
                <span style={{ fontSize: '0.7rem', marginTop: '0.1rem', opacity: 0.7 }}>{c.icon}</span>
                <p style={{ fontSize: '0.78rem', color: '#bbb', lineHeight: 1.5, flex: 1 }}>{msg.content}</p>
                <span style={{ fontSize: '0.58rem', color: '#444', whiteSpace: 'nowrap', marginTop: '0.15rem' }}>{msg.time}</span>
              </div>
            )
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Footer */}
      <div style={{
        padding: '0.35rem 1rem', borderTop: '1px solid rgba(239,68,68,0.06)',
        fontSize: '0.55rem', color: '#2a2a2a', textAlign: 'center', letterSpacing: '0.06em',
      }}>
        SYLEA AGENT v1.0 — Actions executees via Sylea.AI
      </div>
    </div>
  )
}

export default App
