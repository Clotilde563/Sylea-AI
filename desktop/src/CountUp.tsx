/**
 * Animation count-up sur changements de valeur (Sprint 2 — feature 2.9)
 *
 * Anime la transition entre 2 valeurs numeriques avec ease-out cubic.
 * Frame-rate aligne sur RAF, formatte en entier ou avec decimales.
 *
 * <CountUp to={42} durationMs={500} />
 *   → affiche 0 → 1 → ... → 42 sur 500 ms
 */
import { useEffect, useRef, useState } from 'react'

interface CountUpProps {
  to: number
  /** Duree de l'animation, ms (default 500) */
  durationMs?: number
  /** Nombre de decimales (default 0) */
  decimals?: number
  /** Prefixe (ex "$" ou "+") */
  prefix?: string
  /** Suffixe (ex "ms", "%") */
  suffix?: string
  /** Style optionnel */
  style?: React.CSSProperties
  /** ClassName optionnel */
  className?: string
}

// Ease-out cubic : commence vite, ralentit en fin
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)

export function CountUp({
  to,
  durationMs = 500,
  decimals = 0,
  prefix = '',
  suffix = '',
  style,
  className,
}: CountUpProps) {
  const [display, setDisplay] = useState(to)
  const fromRef = useRef(to)
  const targetRef = useRef(to)
  const rafRef = useRef<number | null>(null)
  const startTRef = useRef<number>(0)

  useEffect(() => {
    if (to === targetRef.current) return // pas de change → skip
    fromRef.current = display
    targetRef.current = to

    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    startTRef.current = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startTRef.current
      const t = Math.min(1, elapsed / durationMs)
      const eased = easeOutCubic(t)
      const v = fromRef.current + (targetRef.current - fromRef.current) * eased
      setDisplay(v)
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        setDisplay(targetRef.current)
        rafRef.current = null
      }
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
    // display intentionally not in deps — would create infinite loop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, durationMs])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  const formatted = display.toFixed(decimals)
  // Formatage thousands : 1234 → 1 234
  const withSep = decimals === 0
    ? formatted.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
    : formatted

  return (
    <span style={style} className={className}>
      {prefix}{withSep}{suffix}
    </span>
  )
}

export default CountUp
