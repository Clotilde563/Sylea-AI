import { useState } from 'react'
import { api } from '../api/client'

export default function FeedbackButton({
  messageId,
  agentResponse,
}: {
  messageId?: string
  agentResponse?: string
}) {
  const [vote, setVote] = useState<'up' | 'down' | null>(null)
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState(false)

  const send = async (v: 'up' | 'down', cmt = '') => {
    try {
      await api.recordFeedback({
        vote: v,
        message_id: messageId,
        comment: cmt || undefined,
        agent_response: agentResponse?.slice(0, 4000),
      })
      setVote(v)
      setSent(true)
      if (cmt) setShowComment(false)
    } catch (e) {
      // silent
    }
  }

  if (sent) {
    return (
      <div style={{
        fontSize: '0.75rem', color: 'var(--text-muted)',
        display: 'inline-flex', gap: 4, alignItems: 'center',
      }}>
        {vote === 'up' ? '👍' : '👎'} Merci !
      </div>
    )
  }

  return (
    <div style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      <button
        onClick={() => send('up')}
        title="Bonne réponse"
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: 4, borderRadius: 4, fontSize: '0.9rem',
          opacity: 0.5, transition: 'opacity 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
        onMouseLeave={e => (e.currentTarget.style.opacity = '0.5')}
      >
        👍
      </button>
      <button
        onClick={() => {
          if (!showComment) setShowComment(true)
          else send('down', comment)
        }}
        title="Mauvaise réponse"
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: 4, borderRadius: 4, fontSize: '0.9rem',
          opacity: 0.5, transition: 'opacity 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
        onMouseLeave={e => (e.currentTarget.style.opacity = '0.5')}
      >
        👎
      </button>

      {showComment && (
        <div style={{
          position: 'absolute', marginTop: 30, zIndex: 100,
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          borderRadius: 8, padding: 8, display: 'flex', gap: 6,
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}>
          <input
            type="text"
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="Qu'est-ce qui n'a pas marché ?"
            autoFocus
            onKeyDown={e => {
              if (e.key === 'Enter') send('down', comment)
              if (e.key === 'Escape') setShowComment(false)
            }}
            style={{
              padding: '4px 8px', background: 'var(--bg-surface)',
              border: '1px solid var(--border)', borderRadius: 4,
              color: 'var(--text-primary)', fontSize: '0.8rem', minWidth: 220,
            }}
          />
          <button
            onClick={() => send('down', comment)}
            style={{
              padding: '4px 10px', background: 'var(--accent-violet)',
              color: '#fff', border: 'none', borderRadius: 4,
              cursor: 'pointer', fontSize: '0.8rem',
            }}
          >
            Envoyer
          </button>
        </div>
      )}
    </div>
  )
}
