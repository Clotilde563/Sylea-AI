/**
 * Animations & transitions cards (Sprint 2 — feature 2.5)
 *
 * Wrapper leger autour des CSS transitions + Web Animations API. On evite
 * Framer Motion pour garder le bundle minimal (pas besoin de deps externe
 * pour des fades / slides / scales).
 *
 * Composants exposes :
 *   <FadeIn>    — fade + translateY 0.3s ease-out
 *   <SlideIn>   — slide depuis cote (left|right|top|bottom)
 *   <Stagger>   — applique un delay incremental aux enfants
 *   <Scale>     — scale 0.96 → 1
 *   <ScrollSmooth> — wrapper qui active scroll-behavior smooth + scrollbar custom
 */
import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'

export type Direction = 'left' | 'right' | 'top' | 'bottom'

interface BaseProps {
  children: ReactNode
  /** Duree ms (default 300) */
  duration?: number
  /** Delay ms (default 0) */
  delay?: number
  /** Easing CSS (default ease-out) */
  easing?: string
  /** Style supplementaire */
  style?: CSSProperties
  className?: string
  /** Cle qui force le rejouage de l'animation au changement */
  triggerKey?: string | number
}

/** Fade in + translateY leger */
export function FadeIn({
  children, duration = 300, delay = 0, easing = 'ease-out',
  style, className, triggerKey,
}: BaseProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const anim = el.animate([
      { opacity: 0, transform: 'translateY(8px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ], { duration, delay, easing, fill: 'both' })
    return () => { try { anim.cancel() } catch {} }
  }, [duration, delay, easing, triggerKey])
  return <div ref={ref} style={style} className={className}>{children}</div>
}

/** Slide in depuis un cote */
export function SlideIn({
  children, duration = 320, delay = 0, easing = 'cubic-bezier(0.34, 1.2, 0.64, 1)',
  style, className, triggerKey, from = 'right', distance = 24,
}: BaseProps & { from?: Direction; distance?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const startTransform =
      from === 'left'   ? `translateX(-${distance}px)` :
      from === 'right'  ? `translateX(${distance}px)` :
      from === 'top'    ? `translateY(-${distance}px)` :
                          `translateY(${distance}px)`
    const anim = el.animate([
      { opacity: 0, transform: startTransform },
      { opacity: 1, transform: 'translate(0, 0)' },
    ], { duration, delay, easing, fill: 'both' })
    return () => { try { anim.cancel() } catch {} }
  }, [duration, delay, easing, from, distance, triggerKey])
  return <div ref={ref} style={style} className={className}>{children}</div>
}

/** Scale 0.96 → 1, ideal pour les cartes qui apparaissent */
export function Scale({
  children, duration = 280, delay = 0, easing = 'cubic-bezier(0.34, 1.56, 0.64, 1)',
  style, className, triggerKey,
}: BaseProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const anim = el.animate([
      { opacity: 0, transform: 'scale(0.96)' },
      { opacity: 1, transform: 'scale(1)' },
    ], { duration, delay, easing, fill: 'both' })
    return () => { try { anim.cancel() } catch {} }
  }, [duration, delay, easing, triggerKey])
  return <div ref={ref} style={style} className={className}>{children}</div>
}

interface StaggerProps {
  children: ReactNode[]
  /** Delay incremental entre items (default 50ms) */
  step?: number
  /** Anim type pour chaque item */
  variant?: 'fade' | 'slide' | 'scale'
  /** Duree de chaque item */
  duration?: number
  style?: CSSProperties
  className?: string
}

/** Applique une animation echelonnee a chaque enfant */
export function Stagger({ children, step = 50, variant = 'fade', duration = 300, style, className }: StaggerProps) {
  const arr = Array.isArray(children) ? children : [children]
  return (
    <div style={style} className={className}>
      {arr.map((child, i) => {
        const delay = i * step
        if (variant === 'slide')
          return <SlideIn key={i} delay={delay} duration={duration}>{child}</SlideIn>
        if (variant === 'scale')
          return <Scale key={i} delay={delay} duration={duration}>{child}</Scale>
        return <FadeIn key={i} delay={delay} duration={duration}>{child}</FadeIn>
      })}
    </div>
  )
}

interface ScrollSmoothProps {
  children: ReactNode
  style?: CSSProperties
  className?: string
}

/** Wrapper avec scrollbar custom + scroll-behavior smooth */
export function ScrollSmooth({ children, style, className }: ScrollSmoothProps) {
  return (
    <>
      <style>{`
        .sy-scroll {
          scroll-behavior: smooth;
          scrollbar-width: thin;
          scrollbar-color: rgba(0, 200, 255, 0.25) transparent;
        }
        .sy-scroll::-webkit-scrollbar          { width: 6px; height: 6px; }
        .sy-scroll::-webkit-scrollbar-track    { background: transparent; }
        .sy-scroll::-webkit-scrollbar-thumb    {
          background: rgba(0, 200, 255, 0.18);
          border-radius: 3px;
        }
        .sy-scroll::-webkit-scrollbar-thumb:hover {
          background: rgba(0, 200, 255, 0.32);
        }
      `}</style>
      <div className={['sy-scroll', className].filter(Boolean).join(' ')} style={style}>
        {children}
      </div>
    </>
  )
}

/** Hook : observe un element et anime son entree quand il entre dans le viewport */
export function useInViewAnimation<T extends HTMLElement>(
  options: { threshold?: number; once?: boolean } = {},
) {
  const ref = useRef<T>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === 'undefined') {
      el.style.opacity = '1'
      return
    }
    el.style.opacity = '0'
    el.style.transform = 'translateY(10px)'
    el.style.transition = 'opacity 0.4s ease-out, transform 0.4s ease-out'
    const io = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          el.style.opacity = '1'
          el.style.transform = 'translateY(0)'
          if (options.once !== false) io.disconnect()
        }
      }
    }, { threshold: options.threshold ?? 0.15 })
    io.observe(el)
    return () => io.disconnect()
  }, [options.threshold, options.once])
  return ref
}
