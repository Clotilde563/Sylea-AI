// Chatbot Service Sylea — panneau de chat flottant

import { useState, useRef, useEffect } from 'react'
import { SyleaLogo } from './SyleaLogo'
import { api } from '../api/client'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface ServiceChatbotProps {
  visible: boolean
  onClose: () => void
}

export function ServiceChatbot({ visible, onClose }: ServiceChatbotProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: 'Bonjour ! 👋 Je suis le Service Syléa. Comment puis-je vous aider ?' },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!visible) return null

  const handleSend = async () => {
    if (!input.trim() || sending) return
    const userMsg: ChatMessage = { role: 'user', content: input.trim() }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
    setSending(true)
    try {
      const history = newMessages.map(m => ({ role: m.role, content: m.content }))
      const response = await api.serviceClientChat(history)
      setMessages(prev => [...prev, { role: 'assistant', content: response.message }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Désolé, une erreur est survenue. Réessayez.' }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', bottom: '1rem', right: '1rem',
      width: 380, maxHeight: 520,
      background: 'rgba(6, 12, 26, 0.96)',
      backdropFilter: 'blur(20px)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: '0 12px 48px rgba(0,0,0,0.8)',
      zIndex: 1000,
      display: 'flex', flexDirection: 'column',
      animation: 'fadeInScale 0.2s ease',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0.75rem 1rem',
        borderBottom: '1px solid var(--border)',
        background: 'rgba(26,111,216,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <SyleaLogo size={20} animated={false} />
          <span style={{ fontSize: '0.78rem', fontWeight: 700, letterSpacing: '0.1em', color: 'var(--accent-silver)' }}>
            SERVICE SYLÉA
          </span>
        </div>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--text-muted)', fontSize: '1.1rem', padding: '0.25rem',
        }}>✕</button>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '0.75rem',
        display: 'flex', flexDirection: 'column', gap: '0.5rem',
        minHeight: 300,
      }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
            maxWidth: '85%',
            padding: '0.6rem 0.85rem',
            borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
            background: msg.role === 'user' ? 'var(--bg-elevated)' : 'rgba(26,111,216,0.1)',
            border: msg.role === 'user' ? '1px solid var(--border)' : '1px solid rgba(26,111,216,0.2)',
            fontSize: '0.82rem',
            lineHeight: 1.6,
            color: 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
          }}>
            {msg.content}
          </div>
        ))}
        {sending && (
          <div style={{
            alignSelf: 'flex-start', maxWidth: '85%',
            padding: '0.6rem 0.85rem',
            borderRadius: '12px 12px 12px 2px',
            background: 'rgba(26,111,216,0.1)',
            border: '1px solid rgba(26,111,216,0.2)',
            fontSize: '0.82rem', color: 'var(--text-muted)',
          }}>
            <span className="spinner spinner-sm" style={{ marginRight: '0.5rem' }} />
            Réflexion...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{
        display: 'flex', gap: '0.5rem', padding: '0.75rem',
        borderTop: '1px solid var(--border)',
      }}>
        <input
          className="input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
          placeholder="Posez votre question..."
          style={{ flex: 1, fontSize: '0.82rem', padding: '0.5rem 0.75rem' }}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || sending}
          style={{
            padding: '0.5rem 0.85rem', borderRadius: 'var(--radius-md)',
            background: input.trim() && !sending ? 'var(--accent-violet)' : 'var(--bg-hover)',
            border: 'none', color: '#fff', fontWeight: 600,
            cursor: input.trim() && !sending ? 'pointer' : 'default',
            fontSize: '0.9rem',
          }}
        >→</button>
      </div>
    </div>
  )
}
