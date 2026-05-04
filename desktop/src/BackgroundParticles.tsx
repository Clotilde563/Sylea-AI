/**
 * Particules de fond animees (Sprint 2 — feature 2.2)
 *
 * Canvas plein-ecran fixed, derriere tout (z-index: 0). Affiche un maillage
 * de points cyan qui :
 *   - flottent doucement (wander)
 *   - se relient entre eux quand proches (lignes triangulees)
 *   - sont attires legerement par le curseur souris (parallax tech)
 *
 * Optimise : 60 particules max, frame-rate cap a ~30fps via skip frame,
 * resize-aware via ResizeObserver. Cap a `prefers-reduced-motion` → render
 * statique sans animation.
 */
import { useEffect, useRef } from 'react'

interface BackgroundParticlesProps {
  /** Nombre de particules (default 60) */
  count?: number
  /** Distance max pour relier 2 particules (default 110) */
  linkDist?: number
  /** Couleur de base, par defaut cyan Sylea */
  color?: string
  /** Active l'attraction par la souris (default true) */
  mouseAttract?: boolean
}

export function BackgroundParticles({
  count = 60,
  linkDist = 110,
  color = '0, 200, 255',
  mouseAttract = true,
}: BackgroundParticlesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef<{ x: number; y: number; active: boolean }>({ x: -9999, y: -9999, active: false })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let W = 0, H = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    interface P { x: number; y: number; vx: number; vy: number; r: number }
    const particles: P[] = []

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      W = rect.width
      H = rect.height
      canvas.width = W * dpr
      canvas.height = H * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()

    // Init particles
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        r: 1.0 + Math.random() * 1.4,
      })
    }

    const onMove = (e: MouseEvent) => {
      mouseRef.current.x = e.clientX
      mouseRef.current.y = e.clientY
      mouseRef.current.active = true
    }
    const onLeave = () => {
      mouseRef.current.active = false
      mouseRef.current.x = -9999
      mouseRef.current.y = -9999
    }
    if (mouseAttract) {
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseleave', onLeave)
    }

    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    // Reduced-motion: render once + return early
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = `rgba(${color}, 0.45)`
      for (const p of particles) {
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fill()
      }
      return () => {
        ro.disconnect()
        if (mouseAttract) {
          window.removeEventListener('mousemove', onMove)
          window.removeEventListener('mouseleave', onLeave)
        }
      }
    }

    let raf = 0
    let stopped = false
    let lastT = 0
    const targetMs = 1000 / 30 // 30 fps cap (suffit pour des particules lentes)

    const tick = (now: number) => {
      if (stopped) return
      raf = requestAnimationFrame(tick)
      if (now - lastT < targetMs) return
      lastT = now

      ctx.clearRect(0, 0, W, H)

      const m = mouseRef.current

      // Update + draw points
      for (const p of particles) {
        // Attraction souris (faible, pour effet parallax leger)
        if (mouseAttract && m.active) {
          const dx = m.x - p.x
          const dy = m.y - p.y
          const d2 = dx * dx + dy * dy
          if (d2 < 200 * 200) {
            const f = (1 - Math.sqrt(d2) / 200) * 0.025
            p.vx += (dx / Math.sqrt(d2 + 1)) * f
            p.vy += (dy / Math.sqrt(d2 + 1)) * f
          }
        }
        // Damping + integration
        p.vx *= 0.985
        p.vy *= 0.985
        p.x += p.vx
        p.y += p.vy
        // Wrap edges
        if (p.x < -10) p.x = W + 10
        if (p.x > W + 10) p.x = -10
        if (p.y < -10) p.y = H + 10
        if (p.y > H + 10) p.y = -10
      }

      // Draw lines
      ctx.lineWidth = 0.6
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i], b = particles[j]
          const dx = a.x - b.x, dy = a.y - b.y
          const d2 = dx * dx + dy * dy
          const d = linkDist
          if (d2 < d * d) {
            const alpha = (1 - Math.sqrt(d2) / d) * 0.2
            ctx.strokeStyle = `rgba(${color}, ${alpha})`
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.stroke()
          }
        }
      }

      // Draw points (apres lignes pour qu'ils soient au-dessus)
      for (const p of particles) {
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${color}, 0.55)`
        ctx.shadowColor = `rgba(${color}, 0.6)`
        ctx.shadowBlur = 4
        ctx.fill()
      }
      ctx.shadowBlur = 0
    }
    raf = requestAnimationFrame(tick)

    return () => {
      stopped = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      if (mouseAttract) {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseleave', onLeave)
      }
    }
  }, [count, linkDist, color, mouseAttract])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 0,
        opacity: 0.6,
      }}
      aria-hidden
    />
  )
}

export default BackgroundParticles
