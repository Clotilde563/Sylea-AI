// Page de connexion / inscription Sylea.AI

import { useState, useRef, type FormEvent, type KeyboardEvent, type ClipboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../auth/authStore'
import { SyleaLogo } from '../components/SyleaLogo'

type Tab = 'login' | 'register'

export default function LoginPage() {
  const [tab, setTab] = useState<Tab>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Verification step
  const [verificationStep, setVerificationStep] = useState(false)
  const [verificationCode, setVerificationCode] = useState(['', '', '', '', '', ''])
  const digitRefs = useRef<(HTMLInputElement | null)[]>([])

  const { login, register, verifyCode, error, clearError } = useAuthStore()
  const navigate = useNavigate()

  const switchTab = (t: Tab) => {
    setTab(t)
    setLocalError(null)
    setSuccessMsg(null)
    clearError()
    setEmail('')
    setPassword('')
    setConfirmPassword('')
    setVerificationStep(false)
    setVerificationCode(['', '', '', '', '', ''])
  }

  const handleDigitChange = (index: number, value: string) => {
    if (value.length > 1) value = value.slice(-1)
    if (value && !/^\d$/.test(value)) return

    const newCode = [...verificationCode]
    newCode[index] = value
    setVerificationCode(newCode)

    // Auto-focus next input
    if (value && index < 5) {
      digitRefs.current[index + 1]?.focus()
    }
  }

  const handleDigitKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !verificationCode[index] && index > 0) {
      digitRefs.current[index - 1]?.focus()
    }
  }

  const handleDigitPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (pasted.length > 0) {
      const newCode = [...verificationCode]
      for (let i = 0; i < 6; i++) {
        newCode[i] = pasted[i] || ''
      }
      setVerificationCode(newCode)
      // Focus the last filled or next empty
      const focusIdx = Math.min(pasted.length, 5)
      digitRefs.current[focusIdx]?.focus()
    }
  }

  const handleVerify = async () => {
    const code = verificationCode.join('')
    if (code.length !== 6) {
      setLocalError('Veuillez entrer les 6 chiffres du code.')
      return
    }
    setLocalError(null)
    setSuccessMsg(null)
    clearError()
    setSubmitting(true)
    try {
      await verifyCode(email, code)
      // Verification succeeded — redirect to login tab with success message
      setVerificationStep(false)
      setVerificationCode(['', '', '', '', '', ''])
      setTab('login')
      setPassword('')
      setSuccessMsg('Compte verifie ! Connectez-vous.')
    } catch {
      // error is set in the store
    } finally {
      setSubmitting(false)
    }
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    clearError()

    if (!email.trim() || !password.trim()) {
      setLocalError('Veuillez remplir tous les champs.')
      return
    }

    if (tab === 'register' && password !== confirmPassword) {
      setLocalError('Les mots de passe ne correspondent pas.')
      return
    }

    if (tab === 'register' && password.length < 6) {
      setLocalError('Le mot de passe doit contenir au moins 6 caracteres.')
      return
    }

    setSubmitting(true)
    try {
      if (tab === 'login') {
        await login(email, password)
        navigate('/', { replace: true })
      } else {
        const result = await register(email, password)
        if (result?.requires_verification) {
          setVerificationStep(true)
          setVerificationCode(['', '', '', '', '', ''])
        } else {
          navigate('/', { replace: true })
        }
      }
    } catch {
      // error is set in the store
    } finally {
      setSubmitting(false)
    }
  }

  const handleOAuth = (provider: string) => {
    setLocalError(`Configuration OAuth ${provider} requise. Contactez l'administrateur.`)
  }

  const displayError = localError || error

  return (
    <div style={styles.page}>
      {/* Background glow */}
      <div style={styles.bgGlow} />

      <div style={styles.container}>
        {/* Logo */}
        <div style={styles.logoBlock}>
          <SyleaLogo size={64} animated />
          <h1 style={styles.logoText}>
            <span style={{ color: 'var(--accent-silver)', fontWeight: 700, letterSpacing: '0.12em' }}>
              SYLEA
            </span>
            <span style={{ color: 'var(--accent-violet-light)' }}>.AI</span>
          </h1>
          <p style={styles.tagline}>Votre assistant de prise de decision</p>
        </div>

        {/* Card */}
        <div style={styles.card}>
          {/* Tabs */}
          <div style={styles.tabs}>
            <button
              style={{
                ...styles.tab,
                ...(tab === 'login' ? styles.tabActive : {}),
              }}
              onClick={() => switchTab('login')}
            >
              Connexion
            </button>
            <button
              style={{
                ...styles.tab,
                ...(tab === 'register' ? styles.tabActive : {}),
              }}
              onClick={() => switchTab('register')}
            >
              Inscription
            </button>
          </div>

          {/* Success */}
          {successMsg && (
            <div style={styles.successBox}>
              {successMsg}
            </div>
          )}

          {/* Error */}
          {displayError && (
            <div style={styles.errorBox}>
              <span style={{ marginRight: '0.5rem' }}>!</span>
              {displayError}
            </div>
          )}

          {/* Verification step or Form */}
          {verificationStep ? (
            <div style={styles.verificationBlock}>
              <div style={styles.verificationIcon}>
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent-violet-light)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="4" width="20" height="16" rx="2" />
                  <path d="M22 4L12 13L2 4" />
                </svg>
              </div>
              <p style={styles.verificationText}>
                Un code de verification a ete envoye a
              </p>
              <p style={styles.verificationEmail}>{email}</p>

              <div style={styles.digitRow}>
                {verificationCode.map((digit, i) => (
                  <input
                    key={i}
                    ref={(el) => { digitRefs.current[i] = el }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={(e) => handleDigitChange(i, e.target.value)}
                    onKeyDown={(e) => handleDigitKeyDown(i, e)}
                    onPaste={i === 0 ? handleDigitPaste : undefined}
                    style={styles.digitInput}
                    autoFocus={i === 0}
                  />
                ))}
              </div>

              <button
                type="button"
                className="btn btn-primary btn-full btn-lg"
                disabled={submitting || verificationCode.join('').length !== 6}
                onClick={handleVerify}
                style={{ marginTop: '0.5rem' }}
              >
                {submitting ? (
                  <span className="spinner spinner-sm" style={{ borderTopColor: 'white' }} />
                ) : (
                  'Verifier'
                )}
              </button>

              <button
                type="button"
                style={styles.backLink}
                onClick={() => {
                  setVerificationStep(false)
                  setVerificationCode(['', '', '', '', '', ''])
                  clearError()
                }}
              >
                Retour
              </button>
            </div>
          ) : (
            <>
              {/* Form */}
              <form onSubmit={handleSubmit} style={styles.form}>
                <div className="input-group">
                  <label className="input-label" htmlFor="email">Adresse e-mail</label>
                  <input
                    id="email"
                    className="input"
                    type="email"
                    placeholder="vous@exemple.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    autoFocus
                  />
                </div>

                <div className="input-group">
                  <label className="input-label" htmlFor="password">Mot de passe</label>
                  <input
                    id="password"
                    className="input"
                    type="password"
                    placeholder="Votre mot de passe"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                  />
                </div>

                {tab === 'register' && (
                  <div className="input-group">
                    <label className="input-label" htmlFor="confirmPassword">
                      Confirmer le mot de passe
                    </label>
                    <input
                      id="confirmPassword"
                      className="input"
                      type="password"
                      placeholder="Confirmez votre mot de passe"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      autoComplete="new-password"
                    />
                  </div>
                )}

                <button
                  type="submit"
                  className="btn btn-primary btn-full btn-lg"
                  disabled={submitting}
                  style={{ marginTop: '0.5rem' }}
                >
                  {submitting ? (
                    <span className="spinner spinner-sm" style={{ borderTopColor: 'white' }} />
                  ) : tab === 'login' ? (
                    'Se connecter'
                  ) : (
                    "S'inscrire"
                  )}
                </button>
              </form>

              {/* Divider */}
              <div style={styles.dividerRow}>
                <div style={styles.dividerLine} />
                <span style={styles.dividerText}>ou</span>
                <div style={styles.dividerLine} />
              </div>

              {/* OAuth buttons */}
              <div style={styles.oauthRow}>
                <button
                  type="button"
                  className="btn btn-outline btn-full"
                  style={styles.oauthBtn}
                  onClick={() => handleOAuth('Google')}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24">
                    <path
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
                      fill="#4285F4"
                    />
                    <path
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      fill="#34A853"
                    />
                    <path
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                      fill="#FBBC05"
                    />
                    <path
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      fill="#EA4335"
                    />
                  </svg>
                  Google
                </button>

                <button
                  type="button"
                  className="btn btn-outline btn-full"
                  style={styles.oauthBtn}
                  onClick={() => handleOAuth('GitHub')}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="var(--text-primary)">
                    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                  </svg>
                  GitHub
                </button>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <p style={styles.footer}>
          <span style={{ color: 'var(--accent-silver)', fontWeight: 700, letterSpacing: '0.1em' }}>
            SYLEA
          </span>
          <span style={{ color: 'var(--accent-violet-light)' }}>.AI</span>
        </p>
      </div>
    </div>
  )
}

// ── Styles ──────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'var(--bg-primary)',
    position: 'relative',
    overflow: 'hidden',
  },
  bgGlow: {
    position: 'absolute',
    top: '-20%',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '600px',
    height: '600px',
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(26,111,216,0.08) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    width: '100%',
    maxWidth: '420px',
    padding: '2rem 1.5rem',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '1.5rem',
  },
  logoBlock: {
    textAlign: 'center',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.5rem',
  },
  logoInfinity: {
    marginBottom: '0.25rem',
    filter: 'drop-shadow(0 0 12px rgba(64,144,240,0.4))',
  },
  logoText: {
    fontSize: '2rem',
    fontWeight: 700,
    letterSpacing: '0.08em',
    margin: 0,
  },
  tagline: {
    color: 'var(--text-muted)',
    fontSize: '0.85rem',
    letterSpacing: '0.04em',
  },
  card: {
    width: '100%',
    background: 'var(--bg-surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '1.75rem',
    boxShadow: 'var(--shadow-card)',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  tabs: {
    display: 'flex',
    borderRadius: 'var(--radius-md)',
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    overflow: 'hidden',
  },
  tab: {
    flex: 1,
    padding: '0.625rem 1rem',
    background: 'transparent',
    border: 'none',
    color: 'var(--text-secondary)',
    fontSize: '0.9rem',
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: 'var(--font-sans)',
  },
  tabActive: {
    background: 'var(--accent-violet)',
    color: 'white',
    boxShadow: '0 0 12px rgba(26,111,216,0.3)',
  },
  successBox: {
    background: 'rgba(34,197,94,0.1)',
    color: 'var(--success, #22c55e)',
    border: '1px solid rgba(34,197,94,0.3)',
    borderRadius: 'var(--radius-sm)',
    padding: '0.625rem 0.875rem',
    fontSize: '0.85rem',
    fontWeight: 500,
    textAlign: 'center' as const,
  },
  errorBox: {
    background: 'var(--danger-dim)',
    color: 'var(--danger)',
    border: '1px solid rgba(239,68,68,0.3)',
    borderRadius: 'var(--radius-sm)',
    padding: '0.625rem 0.875rem',
    fontSize: '0.85rem',
    fontWeight: 500,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
  },
  dividerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
  },
  dividerLine: {
    flex: 1,
    height: '1px',
    background: 'var(--border)',
  },
  dividerText: {
    color: 'var(--text-muted)',
    fontSize: '0.8rem',
    letterSpacing: '0.04em',
    textTransform: 'uppercase' as const,
  },
  oauthRow: {
    display: 'flex',
    gap: '0.75rem',
  },
  oauthBtn: {
    fontSize: '0.85rem',
    padding: '0.625rem 1rem',
  },
  verificationBlock: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.75rem',
    padding: '0.5rem 0',
  },
  verificationIcon: {
    marginBottom: '0.25rem',
    opacity: 0.9,
  },
  verificationText: {
    color: 'var(--text-secondary)',
    fontSize: '0.9rem',
    textAlign: 'center',
    margin: 0,
  },
  verificationEmail: {
    color: 'var(--accent-violet-light)',
    fontSize: '0.95rem',
    fontWeight: 600,
    margin: 0,
    wordBreak: 'break-all',
    textAlign: 'center',
  },
  digitRow: {
    display: 'flex',
    gap: '0.5rem',
    justifyContent: 'center',
    margin: '1rem 0',
  },
  digitInput: {
    width: '3rem',
    height: '3.5rem',
    textAlign: 'center',
    fontSize: '1.5rem',
    fontWeight: 700,
    letterSpacing: '0',
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md)',
    color: 'var(--text-primary)',
    outline: 'none',
    fontFamily: 'var(--font-mono, monospace)',
  },
  backLink: {
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    fontSize: '0.85rem',
    cursor: 'pointer',
    textDecoration: 'underline',
    padding: '0.25rem',
    fontFamily: 'var(--font-sans)',
  },
  footer: {
    fontSize: '0.75rem',
    color: 'var(--text-muted)',
    letterSpacing: '0.06em',
    marginTop: '0.5rem',
  },
}
