import { describe, it, expect } from 'vitest'
import { dureeFromProb, probFromJours, deltaFromImpact, buildTimeTicks } from '../utils/duration'

describe('dureeFromProb', () => {
  it('returns ~2.5 years for 50%', () => {
    const d = dureeFromProb(50)
    // 50% => totalJours = 900 * ((100-50)/50)^0.675 = 900 * 1^0.675 = 900 days ~2.5 ans
    expect(d.totalJours).toBe(900)
    expect(d.annees).toBe(2)
    expect(d.mois).toBe(5)
  })

  it('returns a large duration for very low probability (1%)', () => {
    const d = dureeFromProb(1)
    // Very low prob => many years
    expect(d.totalJours).toBeGreaterThan(10000)
    expect(d.annees).toBeGreaterThan(20)
  })

  it('returns a short duration for very high probability (99%)', () => {
    const d = dureeFromProb(99)
    // 99% => totalJours = 900 * (1/99)^0.675 => very small
    expect(d.totalJours).toBeLessThan(60)
  })

  it('clamps probability to [0.01, 99.99]', () => {
    const d0 = dureeFromProb(0)
    const dNeg = dureeFromProb(-10)
    // Both should be treated as 0.01%
    expect(d0.totalJours).toBe(dNeg.totalJours)

    const d100 = dureeFromProb(100)
    const d200 = dureeFromProb(200)
    // Both should be treated as 99.99%
    expect(d100.totalJours).toBe(d200.totalJours)
  })

  it('caps at 73000 days maximum', () => {
    const d = dureeFromProb(0.01)
    expect(d.totalJours).toBeLessThanOrEqual(73000)
  })

  it('formats ligne1 correctly for years', () => {
    const d = dureeFromProb(50)
    expect(d.ligne1).toMatch(/ANS?/)
  })

  it('formats ligne1 correctly for months (no years)', () => {
    const d = dureeFromProb(90)
    // 90% => ~4 months
    expect(d.ligne1).toMatch(/MOIS/)
  })

  it('formats ligne1 correctly for days only', () => {
    const d = dureeFromProb(99.9)
    expect(d.ligne1).toMatch(/JOUR/)
  })

  it('returns a non-empty label', () => {
    const d = dureeFromProb(50)
    expect(d.label.length).toBeGreaterThan(0)
  })
})

describe('probFromJours', () => {
  it('returns 100 for 0 or negative days', () => {
    expect(probFromJours(0)).toBe(100)
    expect(probFromJours(-5)).toBe(100)
  })

  it('returns 0 for days >= 73000', () => {
    expect(probFromJours(73000)).toBe(0)
    expect(probFromJours(100000)).toBe(0)
  })

  it('returns ~50% for 900 days (inverse of dureeFromProb)', () => {
    const p = probFromJours(900)
    expect(p).toBeCloseTo(50, 0)
  })

  it('is the inverse of dureeFromProb', () => {
    for (const prob of [10, 25, 50, 75, 90]) {
      const days = dureeFromProb(prob).totalJours
      const recovered = probFromJours(days)
      // Should be close to original (rounding may cause small diff)
      expect(recovered).toBeCloseTo(prob, 0)
    }
  })

  it('returns higher probability for fewer days', () => {
    expect(probFromJours(100)).toBeGreaterThan(probFromJours(1000))
  })
})

describe('deltaFromImpact', () => {
  it('returns a positive delta string for positive impact', () => {
    const result = deltaFromImpact(50, 5)
    expect(result).toMatch(/^\+/)
  })

  it('returns a negative delta string for negative impact', () => {
    const result = deltaFromImpact(50, -5)
    expect(result).toMatch(/^-/)
  })

  it('returns 0min for zero impact', () => {
    const result = deltaFromImpact(50, 0)
    expect(result).toBe('0min')
  })

  it('caps delta by maxJours when provided', () => {
    // Large impact but small maxJours cap
    const uncapped = deltaFromImpact(50, 20)
    const capped = deltaFromImpact(50, 20, 5)
    // Capped result should use hour/min format (maxJours <= 7)
    expect(capped).toMatch(/h|min/)
  })

  it('formats in hours/minutes for maxJours <= 7', () => {
    const result = deltaFromImpact(50, 1, 3)
    expect(result).toMatch(/h|min/)
  })

  it('formats in years for large deltas', () => {
    const result = deltaFromImpact(5, 3)
    // Going from 5% to 8% should still be years of difference
    expect(result).toMatch(/a/)
  })
})

describe('deltaFromImpact regression - never 0min for non-zero impact', () => {
    it('should show at least 1min for small positive impact on 1-day frame', () => {
        const result = deltaFromImpact(10, 0.001, 1)
        expect(result).not.toBe('0min')
        expect(result).toContain('min')
    })

    it('should show at least 1min for small negative impact on 1-day frame', () => {
        const result = deltaFromImpact(10, -0.001, 1)
        expect(result).not.toBe('0min')
        expect(result).toContain('min')
    })

    it('should show 0min only when impact is exactly 0', () => {
        const result = deltaFromImpact(10, 0, 1)
        expect(result).toBe('0min')
    })

    it('should show different values for different impacts', () => {
        const result1 = deltaFromImpact(10, 0.05, 1)
        const result2 = deltaFromImpact(10, -0.02, 1)
        expect(result1).not.toBe(result2)
    })
})

describe('buildTimeTicks', () => {
  it('returns hour-based ticks for less than 1 day', () => {
    const ticks = buildTimeTicks(0.5) // 12 hours
    expect(ticks.length).toBeGreaterThan(0)
    // Should have hour labels
    expect(ticks.some(t => t.label.includes('h'))).toBe(true)
  })

  it('returns day-based ticks for days < 30', () => {
    const ticks = buildTimeTicks(14) // 2 weeks
    expect(ticks.length).toBeGreaterThan(0)
    expect(ticks.some(t => t.label.includes('J+'))).toBe(true)
  })

  it('returns month-based ticks for days < 365', () => {
    const ticks = buildTimeTicks(180) // ~6 months
    expect(ticks.length).toBeGreaterThan(0)
    expect(ticks.some(t => t.label.includes('m'))).toBe(true)
  })

  it('returns year-based ticks for days >= 365', () => {
    const ticks = buildTimeTicks(730) // ~2 years
    expect(ticks.length).toBeGreaterThan(0)
    expect(ticks.some(t => t.label.includes('a'))).toBe(true)
  })

  it('always starts with a tick at valueDays near 0', () => {
    for (const days of [0.5, 14, 180, 730]) {
      const ticks = buildTimeTicks(days)
      expect(ticks[0].valueDays).toBeCloseTo(0, 1)
    }
  })

  it('returns an array of ticks with valueDays and label', () => {
    const ticks = buildTimeTicks(30)
    for (const tick of ticks) {
      expect(tick).toHaveProperty('valueDays')
      expect(tick).toHaveProperty('label')
      expect(typeof tick.valueDays).toBe('number')
      expect(typeof tick.label).toBe('string')
    }
  })
})
