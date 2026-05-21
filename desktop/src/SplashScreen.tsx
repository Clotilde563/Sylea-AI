/**
 * Splash screen anime (Sprint 2 — feature 2.1)
 *
 * Affiche au boot pendant 1.4 s (1 s fade-in + 0.4 s fade-out).
 * - Logo Sylea anime (officiel)
 * - Wordmark "SYLEA AGENT" letterspacing tech
 * - Particules cyan qui rayonnent du logo (canvas)
 * - Bar de progression mono "INITIALIZING SYSTEM..."
 *
 * Utilise sy-pulse / sy-fadein keyframes globaux (definis dans index.html /
 * App.tsx). Auto-disparait au mount du parent via prop onComplete.
 */
import { useEffect, useRef, useState } from 'react'
import { SyleaLogo } from './SyleaLogo'

interface SplashScreenProps {
  onComplete: () => void
  /** Duree d'affichage avant fade-out, ms (default 1100) */
  duration?: number
}

export function SplashScreen({ onComplete, duration = 1100 }: SplashScreenProps) {
  const [phase, setPhase] = useState<'enter' | 'visible' | 'leave'>('enter')
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Stocke onComplete dans un ref pour eviter que l'effect re-run quand le
  // parent re-render avec une nouvelle callback inline. Sans ca, un re-render
  // toutes les 1s (interval stats) cancel les timers et recommence -> boucle.
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

  // Phase manager: enter (0→80ms) → visible (→duration) → leave (380ms) → done
  // IMPORTANT : ne PAS mettre onComplete dans les deps (cf. ref ci-dessus)
  useEffect(() => {
    const t1 = setTimeout(() => setPhase('visible'), 80)
    const t2 = setTimeout(() => setPhase('leave'), duration)
    const t3 = setTimeout(() => onCompleteRef.current(), duration + 380)
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3) }
  }, [duration])

  // Particules canvas : 60 points qui rayonnent du centre vers l'exterieur
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const W = canvas.width = canvas.offsetWidth * dpr
    const H = canvas.height = canvas.offsetHeight * dpr
    ctx.scale(dpr, dpr)

    const cx = canvas.offsetWidth / 2
    const cy = canvas.offsetHeight / 2

    interface Particle { x: number; y: number; vx: number; vy: number; life: number; max: number }
    const particles: Particle[] = []
    const spawn = () => {
      const angle = Math.random() * Math.PI * 2
      const speed = 0.6 + Math.random() * 1.6
      particles.push({
        x: cx, y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 0, max: 60 + Math.random() * 60,
      })
    }
    for (let i = 0; i < 25; i++) spawn()

    let raf = 0
    let stopped = false
    const tick = () => {
      if (stopped) return
      ctx.clearRect(0, 0, W, H)
      if (particles.length < 80) spawn()
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i]
        p.x += p.vx
        p.y += p.vy
        p.life++
        const t = p.life / p.max
        if (t >= 1) { particles.splice(i, 1); continue }
        const alpha = (1 - t) * 0.85
        const r = 1.4 + (1 - t) * 1.1
        ctx.beginPath()
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(0, 200, 255, ${alpha})`
        ctx.shadowColor = 'rgba(0, 200, 255, 0.85)'
        ctx.shadowBlur = 8
        ctx.fill()
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { stopped = true; cancelAnimationFrame(raf) }
  }, [])

  const opacity =
    phase === 'enter'   ? 0 :
    phase === 'visible' ? 1 :
    /* leave */           0

  return (
    <div
      style={{
        // absolute (pas fixed) pour rester DANS le conteneur parent —
        // la DesktopTitlebar occupe les 36px du haut et reste cliquable.
        position: 'absolute',
        inset: 0,
        zIndex: 999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 24,
        background: 'radial-gradient(ellipse at center, #0a1428 0%, #050810 70%)',
        opacity,
        transition: 'opacity 380ms ease-out',
        pointerEvents: phase === 'leave' ? 'none' : 'auto',
        userSelect: 'none',
        WebkitUserSelect: 'none',
      }}
    >
      {/* Particules canvas en fond */}
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          inset: 0, width: '100%', height: '100%',
          pointerEvents: 'none',
        }}
      />

      {/* Logo + halo */}
      <div style={{
        position: 'relative', width: 180, height: 180,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        animation: phase === 'visible' ? 'sy-splash-pop 1s ease-out' : 'none',
      }}>
        {/* Halo lumineux derriere le logo (rose Syléa) */}
        <div style={{
          position: 'absolute', inset: 24, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(236,72,153,0.35) 0%, transparent 70%)',
          filter: 'blur(20px)',
          animation: 'sy-pulse 2s ease-in-out infinite',
        }} />
        <SyleaLogo size={140} animated />
      </div>

      {/* Wordmark (rose Syléa) */}
      <div style={{
        fontFamily: '"Inter", system-ui, sans-serif',
        fontWeight: 800,
        fontSize: 28,
        letterSpacing: '0.32em',
        color: '#fbe4f0',
        textShadow: '0 0 18px rgba(236, 72, 153, 0.45)',
        animation: phase === 'visible' ? 'sy-splash-fadein 0.7s ease-out 0.2s backwards' : 'none',
      }}>
        SYLEA <span style={{ color: '#f9a8d4' }}>AGENT</span>
      </div>

      {/* Bar de progression + label tech (rose Syléa) */}
      <div style={{
        marginTop: 4,
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
        animation: phase === 'visible' ? 'sy-splash-fadein 0.7s ease-out 0.4s backwards' : 'none',
      }}>
        <div style={{
          width: 260, height: 2, borderRadius: 1,
          background: 'rgba(236, 72, 153, 0.08)',
          overflow: 'hidden', position: 'relative',
        }}>
          <div style={{
            position: 'absolute', left: 0, top: 0, height: '100%',
            width: '40%',
            background: 'linear-gradient(90deg, transparent, #ec4899, transparent)',
            animation: 'sy-splash-bar 1.1s ease-in-out infinite',
          }} />
        </div>
        <div style={{
          fontFamily: '"JetBrains Mono","Fira Code",monospace',
          fontSize: 10, letterSpacing: '0.28em',
          color: 'rgba(244, 114, 182, 0.75)',
          textTransform: 'uppercase',
        }}>
          <span style={{ color: '#ec4899' }}>▸</span> Initializing system
          <span className="sy-splash-dots">...</span>
        </div>
      </div>

      {/* Inline keyframes */}
      <style>{`
        @keyframes sy-splash-pop {
          0%   { transform: scale(0.85); filter: brightness(0.6); }
          60%  { transform: scale(1.04); filter: brightness(1.15); }
          100% { transform: scale(1);    filter: brightness(1); }
        }
        @keyframes sy-splash-fadein {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes sy-splash-bar {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(360%); }
        }
        @keyframes sy-splash-dots {
          0%   { opacity: 0.2; }
          50%  { opacity: 1; }
          100% { opacity: 0.2; }
        }
        .sy-splash-dots {
          display: inline-block; margin-left: 2px;
          animation: sy-splash-dots 1.2s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}

export default SplashScreen
