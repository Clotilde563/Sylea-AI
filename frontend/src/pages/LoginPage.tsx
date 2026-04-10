// Page de connexion / inscription Sylea.AI — Design premium avec animations

import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent, type ClipboardEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '../auth/authStore'
import { SyleaLogo } from '../components/SyleaLogo'

type Tab = 'login' | 'register'
type View = 'welcome' | 'email'

// ── Neural Network Canvas Background ─────────────────────────────────────

interface Node {
  x: number; y: number; vx: number; vy: number
  radius: number; baseAlpha: number; pulse: number; pulseSpeed: number
}

interface Ripple {
  x: number; y: number; radius: number; maxRadius: number; alpha: number
}

function AnimatedBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animId: number
    let w = 0, h = 0
    const nodes: Node[] = []
    const ripples: Ripple[] = []
    const CONNECTION_DIST = 180
    const NODE_COUNT = 85
    const MOUSE = { x: -1000, y: -1000 }
    let time = 0

    const resize = () => {
      w = canvas.width = window.innerWidth
      h = canvas.height = window.innerHeight
    }
    resize()
    window.addEventListener('resize', resize)

    // Initialize nodes
    for (let i = 0; i < NODE_COUNT; i++) {
      nodes.push({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        radius: Math.random() * 2 + 1,
        baseAlpha: Math.random() * 0.4 + 0.15,
        pulse: Math.random() * Math.PI * 2,
        pulseSpeed: Math.random() * 0.015 + 0.008,
      })
    }

    // Spawn ripple periodically
    let lastRipple = 0
    const spawnRipple = () => {
      ripples.push({
        x: Math.random() * w,
        y: Math.random() * h,
        radius: 0,
        maxRadius: Math.random() * 200 + 150,
        alpha: 0.12,
      })
    }

    // Track mouse
    const onMouse = (e: MouseEvent) => { MOUSE.x = e.clientX; MOUSE.y = e.clientY }
    window.addEventListener('mousemove', onMouse)

    const draw = () => {
      time++
      ctx.clearRect(0, 0, w, h)

      // ── Background gradient ──
      const bg = ctx.createRadialGradient(w * 0.5, h * 0.4, 0, w * 0.5, h * 0.5, w * 0.8)
      bg.addColorStop(0, '#0a1628')
      bg.addColorStop(0.5, '#060e1a')
      bg.addColorStop(1, '#030710')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, h)

      // ── Subtle grid with perspective ──
      ctx.strokeStyle = 'rgba(59, 130, 246, 0.03)'
      ctx.lineWidth = 0.5
      const gridSize = 50
      for (let x = 0; x < w; x += gridSize) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke()
      }
      for (let y = 0; y < h; y += gridSize) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke()
      }

      // ── Horizontal scan line ──
      const scanY = (time * 0.5) % (h + 100) - 50
      const scanGrad = ctx.createLinearGradient(0, scanY - 30, 0, scanY + 30)
      scanGrad.addColorStop(0, 'transparent')
      scanGrad.addColorStop(0.5, 'rgba(59, 130, 246, 0.04)')
      scanGrad.addColorStop(1, 'transparent')
      ctx.fillStyle = scanGrad
      ctx.fillRect(0, scanY - 30, w, 60)

      // ── Ripples ──
      if (time - lastRipple > 180) { spawnRipple(); lastRipple = time }
      for (let i = ripples.length - 1; i >= 0; i--) {
        const r = ripples[i]
        r.radius += 1.2
        r.alpha *= 0.993
        if (r.radius > r.maxRadius || r.alpha < 0.002) { ripples.splice(i, 1); continue }
        ctx.beginPath()
        ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(59, 130, 246, ${r.alpha})`
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      // ── Update nodes ──
      for (const n of nodes) {
        n.x += n.vx
        n.y += n.vy
        n.pulse += n.pulseSpeed

        // Bounce off edges with margin
        if (n.x < -20) n.x = w + 20
        if (n.x > w + 20) n.x = -20
        if (n.y < -20) n.y = h + 20
        if (n.y > h + 20) n.y = -20

        // Subtle mouse attraction
        const mdx = MOUSE.x - n.x, mdy = MOUSE.y - n.y
        const mDist = Math.sqrt(mdx * mdx + mdy * mdy)
        if (mDist < 250 && mDist > 10) {
          n.vx += (mdx / mDist) * 0.015
          n.vy += (mdy / mDist) * 0.015
        }

        // Damping
        n.vx *= 0.998
        n.vy *= 0.998
      }

      // ── Draw connections ──
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x
          const dy = nodes[i].y - nodes[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < CONNECTION_DIST) {
            const alpha = (1 - dist / CONNECTION_DIST) * 0.25

            // Data flow particle along connection
            const flowT = ((time * 0.008 + i * 0.1) % 1)

            // Line gradient
            const lg = ctx.createLinearGradient(nodes[i].x, nodes[i].y, nodes[j].x, nodes[j].y)
            lg.addColorStop(0, `rgba(59, 130, 246, ${alpha * 0.6})`)
            lg.addColorStop(0.5, `rgba(99, 102, 241, ${alpha})`)
            lg.addColorStop(1, `rgba(59, 130, 246, ${alpha * 0.6})`)

            ctx.beginPath()
            ctx.moveTo(nodes[i].x, nodes[i].y)
            ctx.lineTo(nodes[j].x, nodes[j].y)
            ctx.strokeStyle = lg
            ctx.lineWidth = alpha * 2.5
            ctx.stroke()

            // Data packet traveling along the line
            if (dist < CONNECTION_DIST * 0.7) {
              const px = nodes[i].x + (nodes[j].x - nodes[i].x) * flowT
              const py = nodes[i].y + (nodes[j].y - nodes[i].y) * flowT
              ctx.beginPath()
              ctx.arc(px, py, 1.2, 0, Math.PI * 2)
              ctx.fillStyle = `rgba(147, 197, 253, ${alpha * 2})`
              ctx.fill()
            }
          }
        }
      }

      // ── Draw nodes ──
      for (const n of nodes) {
        const pulseAlpha = n.baseAlpha + Math.sin(n.pulse) * 0.15
        const pulseRadius = n.radius + Math.sin(n.pulse) * 0.5

        // Mouse proximity glow
        const mdx = MOUSE.x - n.x, mdy = MOUSE.y - n.y
        const mDist = Math.sqrt(mdx * mdx + mdy * mdy)
        const mouseBoost = mDist < 200 ? (1 - mDist / 200) * 0.6 : 0

        // Outer glow
        const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, pulseRadius * 8)
        glow.addColorStop(0, `rgba(99, 102, 241, ${(pulseAlpha + mouseBoost) * 0.3})`)
        glow.addColorStop(1, 'transparent')
        ctx.fillStyle = glow
        ctx.fillRect(n.x - pulseRadius * 8, n.y - pulseRadius * 8, pulseRadius * 16, pulseRadius * 16)

        // Core
        ctx.beginPath()
        ctx.arc(n.x, n.y, pulseRadius, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(165, 180, 252, ${pulseAlpha + mouseBoost})`
        ctx.fill()

        // Bright center
        ctx.beginPath()
        ctx.arc(n.x, n.y, pulseRadius * 0.4, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(224, 231, 255, ${(pulseAlpha + mouseBoost) * 1.5})`
        ctx.fill()
      }

      // ── Floating hexagons ──
      const hexCount = 5
      for (let i = 0; i < hexCount; i++) {
        const hx = (w * (0.15 + i * 0.18)) + Math.sin(time * 0.005 + i * 1.5) * 40
        const hy = (h * (0.2 + (i % 3) * 0.3)) + Math.cos(time * 0.004 + i * 2) * 30
        const hSize = 20 + i * 8
        const hAlpha = 0.04 + Math.sin(time * 0.008 + i) * 0.02
        const rotation = time * 0.002 + i * 0.5

        ctx.beginPath()
        for (let s = 0; s < 6; s++) {
          const angle = (Math.PI / 3) * s + rotation
          const px = hx + hSize * Math.cos(angle)
          const py = hy + hSize * Math.sin(angle)
          s === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.strokeStyle = `rgba(99, 102, 241, ${hAlpha})`
        ctx.lineWidth = 1
        ctx.stroke()
      }

      // ── Orbiting rings around center ──
      const cx = w * 0.5, cy = h * 0.42
      for (let i = 0; i < 3; i++) {
        const ringR = 220 + i * 80
        const ringAlpha = 0.025 - i * 0.006
        const ringRot = time * (0.001 + i * 0.0005) * (i % 2 === 0 ? 1 : -1)

        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(ringRot)
        ctx.scale(1, 0.35)
        ctx.beginPath()
        ctx.arc(0, 0, ringR, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(59, 130, 246, ${ringAlpha})`
        ctx.lineWidth = 1
        ctx.stroke()

        // Moving dot on ring
        const dotAngle = time * (0.012 + i * 0.005)
        const dotX = ringR * Math.cos(dotAngle)
        const dotY = ringR * Math.sin(dotAngle)
        ctx.beginPath()
        ctx.arc(dotX, dotY, 2.5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(147, 197, 253, ${ringAlpha * 6})`
        ctx.fill()
        ctx.restore()
      }

      // ── Vignette overlay ──
      const vignette = ctx.createRadialGradient(w * 0.5, h * 0.5, w * 0.2, w * 0.5, h * 0.5, w * 0.85)
      vignette.addColorStop(0, 'transparent')
      vignette.addColorStop(1, 'rgba(3, 7, 16, 0.6)')
      ctx.fillStyle = vignette
      ctx.fillRect(0, 0, w, h)

      animId = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMouse)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'auto',
      }}
    />
  )
}

// ── Composant principal ────────────────────────────────────────────────────

export default function LoginPage() {
  const [view, setView] = useState<View>('welcome')
  const [tab, setTab] = useState<Tab>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [acceptCGU, setAcceptCGU] = useState(false)
  const [acceptPrivacy, setAcceptPrivacy] = useState(false)

  // Verification step
  const [verificationStep, setVerificationStep] = useState(false)
  const [verificationCode, setVerificationCode] = useState(['', '', '', '', '', ''])
  const digitRefs = useRef<(HTMLInputElement | null)[]>([])

  const { login, register, verifyCode, error, clearError } = useAuthStore()
  const googleLogin = useAuthStore((s) => s.googleLogin)
  const githubLogin = useAuthStore((s) => s.githubLogin)
  const navigate = useNavigate()

  // Inject CSS animations
  useEffect(() => {
    const styleId = 'login-animations'
    if (document.getElementById(styleId)) return
    const style = document.createElement('style')
    style.id = styleId
    style.textContent = `
      @keyframes fadeSlideUp {
        from { opacity: 0; transform: translateY(30px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes fadeSlideDown {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes shimmer {
        0% { background-position: -200% center; }
        100% { background-position: 200% center; }
      }
      @keyframes glowPulse {
        0%, 100% { box-shadow: 0 0 20px rgba(37,99,235,0.15), 0 0 60px rgba(37,99,235,0.05); }
        50% { box-shadow: 0 0 30px rgba(37,99,235,0.25), 0 0 80px rgba(37,99,235,0.1); }
      }
      @keyframes borderGlow {
        0%, 100% { border-color: rgba(99, 102, 241, 0.15); }
        50% { border-color: rgba(99, 102, 241, 0.3); }
      }
      .login-btn-oauth:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 30px rgba(59, 130, 246, 0.25) !important;
      }
      .login-btn-oauth:active {
        transform: translateY(0) !important;
      }
    `
    document.head.appendChild(style)
    return () => { document.getElementById(styleId)?.remove() }
  }, [])

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
    setAcceptCGU(false)
    setAcceptPrivacy(false)
  }

  const goToEmailView = (t: Tab) => {
    switchTab(t)
    setView('email')
  }

  const goBack = () => {
    setView('welcome')
    setLocalError(null)
    setSuccessMsg(null)
    clearError()
  }

  const handleDigitChange = (index: number, value: string) => {
    if (value.length > 1) value = value.slice(-1)
    if (value && !/^\d$/.test(value)) return
    const newCode = [...verificationCode]
    newCode[index] = value
    setVerificationCode(newCode)
    if (value && index < 5) digitRefs.current[index + 1]?.focus()
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
      for (let i = 0; i < 6; i++) newCode[i] = pasted[i] || ''
      setVerificationCode(newCode)
      digitRefs.current[Math.min(pasted.length, 5)]?.focus()
    }
  }

  const handleVerify = async () => {
    const code = verificationCode.join('')
    if (code.length !== 6) { setLocalError('Veuillez entrer les 6 chiffres du code.'); return }
    setLocalError(null); setSuccessMsg(null); clearError(); setSubmitting(true)
    try {
      await verifyCode(email, code)
      setVerificationStep(false)
      setVerificationCode(['', '', '', '', '', ''])
      setTab('login')
      setPassword('')
      setSuccessMsg('Compte verifie ! Connectez-vous.')
    } catch { /* error in store */ } finally { setSubmitting(false) }
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLocalError(null); clearError()
    if (!email.trim() || !password.trim()) { setLocalError('Veuillez remplir tous les champs.'); return }
    if (tab === 'register' && password !== confirmPassword) { setLocalError('Les mots de passe ne correspondent pas.'); return }
    if (tab === 'register' && password.length < 6) { setLocalError('Le mot de passe doit contenir au moins 6 caracteres.'); return }
    if (tab === 'register' && (!acceptCGU || !acceptPrivacy)) { setLocalError('Veuillez accepter les CGU et la Politique de Confidentialite.'); return }
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
    } catch { /* error in store */ } finally { setSubmitting(false) }
  }

  const handleOAuth = async (provider: string) => {
    setLocalError(null); clearError()
    if (provider === 'google') {
      try {
        setSubmitting(true)
        await googleLogin()
      } catch {
        setLocalError('Erreur connexion Google. Verifiez que le serveur est demarre et que GOOGLE_CLIENT_ID est configure.')
        setSubmitting(false)
      }
    } else if (provider === 'github') {
      try {
        setSubmitting(true)
        await githubLogin()
      } catch {
        setLocalError('Erreur connexion GitHub. Verifiez que le serveur est demarre et que GITHUB_CLIENT_ID est configure.')
        setSubmitting(false)
      }
    } else if (provider === 'apple') {
      setLocalError('La connexion Apple sera bientot disponible.')
    } else {
      setLocalError(`Connexion ${provider} bientot disponible.`)
    }
  }

  const displayError = localError || error

  return (
    <div style={styles.page}>
      <AnimatedBackground />

      <div style={styles.mainContainer}>
        {/* Logo — always visible */}
        <div style={{
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.75rem',
          animation: 'fadeSlideDown 0.8s ease-out',
        }}>
          <SyleaLogo size={72} animated />
          <h1 style={styles.logoText}>
            <span style={{ color: '#e2e8f0', fontWeight: 800, letterSpacing: '0.15em' }}>SYLEA</span>
            <span style={{ color: '#60a5fa' }}>.AI</span>
          </h1>
          <p style={styles.tagline}>
            {view === 'welcome'
              ? 'Ton coach de vie intelligent'
              : tab === 'login' ? 'Content de te revoir' : 'Rejoins l\'aventure'}
          </p>
        </div>

        {/* ── WELCOME VIEW ── */}
        {view === 'welcome' && (
          <div style={{
            ...styles.card,
            animation: 'fadeSlideUp 0.6s ease-out',
          }}>
            {/* Error */}
            {displayError && (
              <div style={styles.errorBox}>
                <span style={{ marginRight: '0.5rem' }}>⚠️</span>
                {displayError}
              </div>
            )}

            {/* Google button */}
            <button
              className="login-btn-oauth"
              style={styles.oauthBtnGoogle}
              onClick={() => handleOAuth('google')}
              disabled={submitting}
            >
              <svg width="20" height="20" viewBox="0 0 24 24">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
              </svg>
              Continuer avec Google
            </button>

            {/* GitHub button */}
            <button
              className="login-btn-oauth"
              style={styles.oauthBtnGithub}
              onClick={() => handleOAuth('github')}
              disabled={submitting}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
              </svg>
              Continuer avec GitHub
            </button>

            {/* Divider */}
            <div style={styles.dividerRow}>
              <div style={styles.dividerLine} />
              <span style={styles.dividerText}>ou</span>
              <div style={styles.dividerLine} />
            </div>

            {/* Email button */}
            <button
              className="login-btn-oauth"
              style={styles.oauthBtnEmail}
              onClick={() => goToEmailView('login')}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="M22 4L12 13L2 4" />
              </svg>
              Connexion email / mot de passe
            </button>

            {/* Inscription link */}
            <p style={{ textAlign: 'center', fontSize: '0.85rem', color: 'rgba(148,163,184,0.8)', margin: '0.5rem 0 0' }}>
              Pas encore de compte ?{' '}
              <button
                onClick={() => goToEmailView('register')}
                style={{ background: 'none', border: 'none', color: '#60a5fa', cursor: 'pointer', fontWeight: 600, fontFamily: 'inherit', fontSize: 'inherit', textDecoration: 'underline' }}
              >
                S'inscrire
              </button>
            </p>
          </div>
        )}

        {/* ── EMAIL VIEW ── */}
        {view === 'email' && (
          <div style={{
            ...styles.card,
            animation: 'fadeSlideUp 0.5s ease-out',
          }}>
            {/* Back button */}
            <button onClick={goBack} style={styles.backButton}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5" />
                <path d="M12 19l-7-7 7-7" />
              </svg>
              Retour
            </button>

            {/* Tabs */}
            <div style={styles.tabs}>
              <button
                style={{ ...styles.tab, ...(tab === 'login' ? styles.tabActive : {}) }}
                onClick={() => switchTab('login')}
              >
                Connexion
              </button>
              <button
                style={{ ...styles.tab, ...(tab === 'register' ? styles.tabActive : {}) }}
                onClick={() => switchTab('register')}
              >
                Inscription
              </button>
            </div>

            {/* Success */}
            {successMsg && <div style={styles.successBox}>{successMsg}</div>}

            {/* Error */}
            {displayError && (
              <div style={styles.errorBox}>
                <span style={{ marginRight: '0.5rem' }}>⚠️</span>
                {displayError}
              </div>
            )}

            {/* Verification step */}
            {verificationStep ? (
              <div style={styles.verificationBlock}>
                <div style={{ opacity: 0.9 }}>
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="2" y="4" width="20" height="16" rx="2" />
                    <path d="M22 4L12 13L2 4" />
                  </svg>
                </div>
                <p style={{ color: 'rgba(148,163,184,0.9)', fontSize: '0.9rem', textAlign: 'center', margin: 0 }}>
                  Un code de verification a ete envoye a
                </p>
                <p style={{ color: '#60a5fa', fontSize: '0.95rem', fontWeight: 600, margin: 0, wordBreak: 'break-all', textAlign: 'center' }}>
                  {email}
                </p>

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
                  style={styles.submitBtn}
                  disabled={submitting || verificationCode.join('').length !== 6}
                  onClick={handleVerify}
                >
                  {submitting ? <span className="spinner spinner-sm" style={{ borderTopColor: 'white' }} /> : 'Verifier'}
                </button>

                <button type="button" style={styles.linkBtn} onClick={() => {
                  setVerificationStep(false); setVerificationCode(['', '', '', '', '', '']); clearError()
                }}>
                  Retour
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div className="input-group">
                  <label className="input-label" htmlFor="email">Adresse e-mail</label>
                  <input
                    id="email" className="input" type="email" placeholder="vous@exemple.com"
                    value={email} onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email" autoFocus
                  />
                </div>

                <div className="input-group">
                  <label className="input-label" htmlFor="password">Mot de passe</label>
                  <input
                    id="password" className="input" type="password" placeholder="Votre mot de passe"
                    value={password} onChange={(e) => setPassword(e.target.value)}
                    autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                  />
                </div>

                {tab === 'register' && (
                  <div className="input-group">
                    <label className="input-label" htmlFor="confirmPassword">Confirmer le mot de passe</label>
                    <input
                      id="confirmPassword" className="input" type="password"
                      placeholder="Confirmez votre mot de passe"
                      value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                      autoComplete="new-password"
                    />
                  </div>
                )}

                {tab === 'register' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginTop: '0.25rem' }}>
                    <label style={styles.checkLabel}>
                      <input type="checkbox" checked={acceptCGU} onChange={() => setAcceptCGU(!acceptCGU)}
                        style={{ marginTop: '0.15rem', accentColor: '#3b82f6' }} />
                      <span>
                        J'accepte les{' '}
                        <Link to="/terms" style={{ color: '#60a5fa' }} target="_blank">
                          Conditions Generales d'Utilisation
                        </Link>
                      </span>
                    </label>
                    <label style={styles.checkLabel}>
                      <input type="checkbox" checked={acceptPrivacy} onChange={() => setAcceptPrivacy(!acceptPrivacy)}
                        style={{ marginTop: '0.15rem', accentColor: '#3b82f6' }} />
                      <span>
                        J'ai lu et j'accepte la{' '}
                        <Link to="/privacy" style={{ color: '#60a5fa' }} target="_blank">
                          Politique de Confidentialite
                        </Link>
                      </span>
                    </label>
                  </div>
                )}

                <button type="submit" style={styles.submitBtn} disabled={submitting}>
                  {submitting ? (
                    <span className="spinner spinner-sm" style={{ borderTopColor: 'white' }} />
                  ) : tab === 'login' ? 'Se connecter' : "S'inscrire"}
                </button>
              </form>
            )}
          </div>
        )}

        {/* Footer */}
        <p style={styles.footer}>
          <span style={{ color: 'rgba(226,232,240,0.5)', fontWeight: 700, letterSpacing: '0.1em' }}>SYLEA</span>
          <span style={{ color: 'rgba(96,165,250,0.5)' }}>.AI</span>
          <span style={{ color: 'rgba(148,163,184,0.3)', marginLeft: '0.5rem' }}>v3.0</span>
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
    position: 'relative',
    overflow: 'hidden',
  },
  mainContainer: {
    position: 'relative',
    zIndex: 1,
    width: '100%',
    maxWidth: '440px',
    padding: '2rem 1.5rem',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '2rem',
  },
  logoText: {
    fontSize: '2.2rem',
    fontWeight: 800,
    letterSpacing: '0.12em',
    margin: 0,
    textShadow: '0 0 30px rgba(96,165,250,0.2)',
  },
  tagline: {
    color: 'rgba(148,163,184,0.7)',
    fontSize: '0.95rem',
    letterSpacing: '0.04em',
    fontWeight: 400,
  },
  card: {
    width: '100%',
    background: 'rgba(10,18,35,0.82)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid rgba(99,102,241,0.15)',
    borderRadius: '20px',
    padding: '2rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
    boxShadow: '0 0 50px rgba(0,0,0,0.4), 0 0 100px rgba(59,130,246,0.06), inset 0 1px 0 rgba(255,255,255,0.03)',
    animation: 'borderGlow 4s ease-in-out infinite',
  },

  // OAuth buttons
  oauthBtnGoogle: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.75rem',
    width: '100%',
    padding: '0.875rem 1.5rem',
    background: 'white',
    color: '#1f2937',
    border: 'none',
    borderRadius: '12px',
    fontSize: '0.95rem',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    fontFamily: 'inherit',
  },
  oauthBtnGithub: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.75rem',
    width: '100%',
    padding: '0.875rem 1.5rem',
    background: '#24292f',
    color: 'white',
    border: '1px solid rgba(255,255,255,0.15)',
    borderRadius: '12px',
    fontSize: '0.95rem',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    fontFamily: 'inherit',
  },
  oauthBtnEmail: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.75rem',
    width: '100%',
    padding: '0.875rem 1.5rem',
    background: 'transparent',
    color: 'rgba(226,232,240,0.9)',
    border: '1px solid rgba(100,160,255,0.2)',
    borderRadius: '12px',
    fontSize: '0.95rem',
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'all 0.2s ease',
    fontFamily: 'inherit',
  },

  // Back button
  backButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    background: 'none',
    border: 'none',
    color: 'rgba(148,163,184,0.8)',
    fontSize: '0.85rem',
    cursor: 'pointer',
    padding: '0.25rem 0',
    fontFamily: 'inherit',
    transition: 'color 0.2s',
    alignSelf: 'flex-start',
  },

  // Tabs
  tabs: {
    display: 'flex',
    borderRadius: '10px',
    background: 'rgba(30,41,59,0.6)',
    border: '1px solid rgba(100,160,255,0.08)',
    overflow: 'hidden',
  },
  tab: {
    flex: 1,
    padding: '0.625rem 1rem',
    background: 'transparent',
    border: 'none',
    color: 'rgba(148,163,184,0.7)',
    fontSize: '0.9rem',
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
  },
  tabActive: {
    background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
    color: 'white',
    boxShadow: '0 0 15px rgba(37,99,235,0.3)',
  },

  // Messages
  successBox: {
    background: 'rgba(34,197,94,0.1)',
    color: '#4ade80',
    border: '1px solid rgba(34,197,94,0.2)',
    borderRadius: '10px',
    padding: '0.75rem 1rem',
    fontSize: '0.85rem',
    fontWeight: 500,
    textAlign: 'center' as const,
  },
  errorBox: {
    background: 'rgba(239,68,68,0.1)',
    color: '#f87171',
    border: '1px solid rgba(239,68,68,0.2)',
    borderRadius: '10px',
    padding: '0.75rem 1rem',
    fontSize: '0.85rem',
    fontWeight: 500,
  },

  // Submit button
  submitBtn: {
    width: '100%',
    padding: '0.875rem',
    background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
    color: 'white',
    border: 'none',
    borderRadius: '12px',
    fontSize: '0.95rem',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
    marginTop: '0.25rem',
  },

  // Divider
  dividerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    margin: '0.25rem 0',
  },
  dividerLine: {
    flex: 1,
    height: '1px',
    background: 'rgba(100,160,255,0.1)',
  },
  dividerText: {
    color: 'rgba(148,163,184,0.4)',
    fontSize: '0.78rem',
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
  },

  // Verification
  verificationBlock: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.75rem',
    padding: '0.5rem 0',
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
    background: 'rgba(30,41,59,0.6)',
    border: '1px solid rgba(100,160,255,0.15)',
    borderRadius: '10px',
    color: '#e2e8f0',
    outline: 'none',
    fontFamily: 'monospace',
  },

  // Links
  linkBtn: {
    background: 'none',
    border: 'none',
    color: 'rgba(148,163,184,0.6)',
    fontSize: '0.85rem',
    cursor: 'pointer',
    textDecoration: 'underline',
    padding: '0.25rem',
    fontFamily: 'inherit',
  },
  checkLabel: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '0.5rem',
    fontSize: '0.78rem',
    color: 'rgba(148,163,184,0.7)',
    cursor: 'pointer',
    lineHeight: 1.5,
  },

  footer: {
    fontSize: '0.75rem',
    letterSpacing: '0.06em',
    marginTop: '0.5rem',
  },
}
