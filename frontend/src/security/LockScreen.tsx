import { useState, useEffect, useCallback } from 'react'
import PatternGrid from './PatternGrid'
import { verifyHash, verifyPattern } from './hashUtils'
import { useT } from '../i18n/LanguageContext'

export default function LockScreen() {
  const t = useT()
  const [locked, setLocked] = useState(false)
  const [lockType, setLockType] = useState<'password' | 'pattern' | null>(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState(false)
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    // If already unlocked this session, skip
    if (sessionStorage.getItem('sylea-unlocked') === 'true') return
    const type = localStorage.getItem('sylea-lock-type') as 'password' | 'pattern' | null
    if (type && localStorage.getItem('sylea-lock-hash')) {
      setLockType(type)
      setLocked(true)
    }
  }, [])

  const unlock = useCallback(() => {
    sessionStorage.setItem('sylea-unlocked', 'true')
    setLocked(false)
  }, [])

  const handlePasswordSubmit = useCallback(async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (checking || !password) return
    setChecking(true)
    setError(false)
    const hash = localStorage.getItem('sylea-lock-hash') || ''
    const ok = await verifyHash(password, hash)
    if (ok) {
      unlock()
    } else {
      setError(true)
      setPassword('')
    }
    setChecking(false)
  }, [password, checking, unlock])

  const handlePatternComplete = useCallback(async (pattern: number[]) => {
    if (checking) return
    if (pattern.length < 4) return
    setChecking(true)
    setError(false)
    const hash = localStorage.getItem('sylea-lock-hash') || ''
    const ok = await verifyPattern(pattern, hash)
    if (ok) {
      unlock()
    } else {
      setError(true)
    }
    setChecking(false)
  }, [checking, unlock])

  if (!locked) return null

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 99999,
      background: 'linear-gradient(135deg, #020509 0%, #0a0e1a 50%, #020509 100%)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: '2rem',
    }}>
      {/* Logo */}
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: '2rem', fontWeight: 800, letterSpacing: '0.15em',
          background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          SYLEA.AI
        </div>
        <div style={{ fontSize: '0.85rem', color: 'rgba(232,232,240,0.5)', marginTop: '0.5rem' }}>
          {t('lock.titre')}
        </div>
      </div>

      {/* Lock icon */}
      <svg width={48} height={48} viewBox="0 0 24 24" fill="none"
        stroke="rgba(255,255,255,0.3)" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <rect x={3} y={11} width={18} height={11} rx={2} />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>

      {lockType === 'password' && (
        <form onSubmit={handlePasswordSubmit} style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem', width: '280px',
        }}>
          <input
            type="password"
            value={password}
            onChange={e => { setPassword(e.target.value); setError(false) }}
            placeholder={t('lock.mdp_placeholder')}
            autoFocus
            style={{
              width: '100%', padding: '0.75rem 1rem',
              background: 'rgba(255,255,255,0.05)', border: `1px solid ${error ? '#ef4444' : 'rgba(255,255,255,0.15)'}`,
              borderRadius: '0.75rem', color: '#e8e8f0', fontSize: '0.9rem',
              outline: 'none', transition: 'border-color 0.2s',
            }}
          />
          <button type="submit" disabled={checking} style={{
            padding: '0.65rem 2rem', borderRadius: '999px',
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            color: 'white', fontWeight: 600, fontSize: '0.85rem',
            border: 'none', cursor: 'pointer', opacity: checking ? 0.6 : 1,
            letterSpacing: '0.06em',
          }}>
            {t('lock.deverrouiller')}
          </button>
        </form>
      )}

      {lockType === 'pattern' && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'rgba(232,232,240,0.5)' }}>
            {t('lock.schema_instruction')}
          </div>
          <PatternGrid onComplete={handlePatternComplete} size={240} />
        </div>
      )}

      {error && (
        <div style={{
          color: '#ef4444', fontSize: '0.8rem', fontWeight: 500,
          animation: 'shake 0.3s ease',
        }}>
          {t('lock.erreur')}
        </div>
      )}

      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0) }
          25% { transform: translateX(-8px) }
          75% { transform: translateX(8px) }
        }
      `}</style>
    </div>
  )
}
