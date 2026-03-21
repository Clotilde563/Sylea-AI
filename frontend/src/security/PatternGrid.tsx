import { useState, useRef, useCallback, useEffect } from 'react'

interface Props {
  onComplete: (pattern: number[]) => void
  size?: number
}

export default function PatternGrid({ onComplete, size = 220 }: Props) {
  const [selected, setSelected] = useState<number[]>([])
  const [drawing, setDrawing] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)

  const dotSize = size / 5
  const gap = size / 3

  // Center positions of each dot (3x3 grid)
  const dots = Array.from({ length: 9 }, (_, i) => ({
    id: i,
    cx: (i % 3) * gap + gap / 2 + dotSize / 2,
    cy: Math.floor(i / 3) * gap + gap / 2 + dotSize / 2,
  }))

  const getDotAt = useCallback((x: number, y: number): number | null => {
    for (const d of dots) {
      const dist = Math.sqrt((x - d.cx) ** 2 + (y - d.cy) ** 2)
      if (dist < dotSize * 1.2) return d.id
    }
    return null
  }, [dots, dotSize])

  const getPointerPos = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    if (!svgRef.current) return { x: 0, y: 0 }
    const rect = svgRef.current.getBoundingClientRect()
    const scale = size / rect.width
    if ('touches' in e) {
      const t = e.touches[0] || e.changedTouches[0]
      return { x: (t.clientX - rect.left) * scale, y: (t.clientY - rect.top) * scale }
    }
    return { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale }
  }, [size])

  const handleStart = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault()
    const pos = getPointerPos(e)
    const dot = getDotAt(pos.x, pos.y)
    if (dot !== null) {
      setSelected([dot])
      setDrawing(true)
    }
  }, [getPointerPos, getDotAt])

  const handleMove = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    if (!drawing) return
    e.preventDefault()
    const pos = getPointerPos(e)
    const dot = getDotAt(pos.x, pos.y)
    if (dot !== null && !selected.includes(dot)) {
      setSelected(prev => [...prev, dot])
    }
  }, [drawing, selected, getPointerPos, getDotAt])

  const handleEnd = useCallback(() => {
    if (drawing && selected.length >= 1) {
      onComplete(selected)
    }
    setDrawing(false)
    setTimeout(() => setSelected([]), 400)
  }, [drawing, selected, onComplete])

  // Prevent scroll on touch
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const prevent = (e: TouchEvent) => e.preventDefault()
    el.addEventListener('touchmove', prevent, { passive: false })
    return () => el.removeEventListener('touchmove', prevent)
  }, [])

  // Lines between selected dots
  const lines: { x1: number; y1: number; x2: number; y2: number }[] = []
  for (let i = 1; i < selected.length; i++) {
    const a = dots[selected[i - 1]]
    const b = dots[selected[i]]
    lines.push({ x1: a.cx, y1: a.cy, x2: b.cx, y2: b.cy })
  }

  return (
    <svg
      ref={svgRef}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: 'block', cursor: 'pointer', touchAction: 'none' }}
      onMouseDown={handleStart}
      onMouseMove={handleMove}
      onMouseUp={handleEnd}
      onMouseLeave={handleEnd}
      onTouchStart={handleStart}
      onTouchMove={handleMove}
      onTouchEnd={handleEnd}
    >
      {/* Lines */}
      {lines.map((l, i) => (
        <line key={i} {...l}
          stroke="#3b82f6" strokeWidth={4} strokeLinecap="round" opacity={0.7}
        />
      ))}
      {/* Dots */}
      {dots.map(d => {
        const isSelected = selected.includes(d.id)
        return (
          <g key={d.id}>
            <circle cx={d.cx} cy={d.cy} r={isSelected ? 18 : 14}
              fill={isSelected ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.05)'}
              stroke={isSelected ? '#3b82f6' : 'rgba(255,255,255,0.2)'}
              strokeWidth={2}
              style={{ transition: 'all 0.15s' }}
            />
            <circle cx={d.cx} cy={d.cy} r={isSelected ? 7 : 5}
              fill={isSelected ? '#3b82f6' : 'rgba(255,255,255,0.3)'}
              style={{
                transition: 'all 0.15s',
                filter: isSelected ? 'drop-shadow(0 0 6px rgba(59,130,246,0.8))' : 'none',
              }}
            />
          </g>
        )
      })}
    </svg>
  )
}
