// Tests des helpers tracking : recommandation, countdown, progression, etc.

import { describe, it, expect } from 'vitest'
import {
  shouldShowRecommendation,
  bestOptionByImpact,
  countDuePeriodsForTracking,
  formatCountdown,
  trackingProgress,
  canCancelPartial,
} from '../utils/tracking'
import type { AnalyseOption, TrackingItem } from '../types'

const baseOption = (overrides: Partial<AnalyseOption>): AnalyseOption => ({
  lettre: 'A',
  description: 'opt',
  pros: [],
  cons: [],
  impact_probabilite: 0,
  impact_jours: 0,
  resume: '',
  ...overrides,
})

const baseTracking = (overrides: Partial<TrackingItem>): TrackingItem => ({
  id: 't1',
  question: 'Q',
  options: [],
  verdict: '',
  etude_scientifique: '',
  impact_temporel_jours: 90,
  nb_periodes: 3,
  device_tz: 'UTC',
  choices: [
    { periode_idx: 0, choice: null, responded_at: null, retry_count: 0 },
    { periode_idx: 1, choice: null, responded_at: null, retry_count: 0 },
    { periode_idx: 2, choice: null, responded_at: null, retry_count: 0 },
  ],
  status: 'tracking',
  impact_final_jours: null,
  impact_final_probabilite: null,
  so_impactes: [],
  cancellation_mode: null,
  next_notif_at: null,
  created_at: '2026-05-28T00:00:00Z',
  validated_at: null,
  cancelled_at: null,
  ...overrides,
})

describe('shouldShowRecommendation', () => {
  it('false when no options', () => {
    expect(shouldShowRecommendation([])).toBe(false)
  })

  it('true when all options have negative impact (recommandation = moins pire)', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: -40 }),
      baseOption({ lettre: 'B', impact_jours: -180 }),
    ]
    expect(shouldShowRecommendation(opts)).toBe(true)
  })

  it('true even when all impacts are 0', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: 0 }),
      baseOption({ lettre: 'B', impact_jours: 0 }),
    ]
    expect(shouldShowRecommendation(opts)).toBe(true)
  })

  it('true when mixed positive and negative impacts', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: 10 }),
      baseOption({ lettre: 'B', impact_jours: -50 }),
    ]
    expect(shouldShowRecommendation(opts)).toBe(true)
  })

  it('true for single option', () => {
    const opts = [baseOption({ lettre: 'A', impact_jours: 5 })]
    expect(shouldShowRecommendation(opts)).toBe(true)
  })
})

describe('bestOptionByImpact', () => {
  it('null when no options', () => {
    expect(bestOptionByImpact([])).toBeNull()
  })

  it('returns the only option when 1 option', () => {
    expect(bestOptionByImpact([baseOption({ lettre: 'A', impact_jours: -10 })])).toBe('A')
  })

  it('returns the option with highest positive impact', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: 5 }),
      baseOption({ lettre: 'B', impact_jours: 50 }),
      baseOption({ lettre: 'C', impact_jours: 10 }),
    ]
    expect(bestOptionByImpact(opts)).toBe('B')
  })

  it('returns the least negative when all are negative', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: -40 }),  // moins pire
      baseOption({ lettre: 'B', impact_jours: -180 }),
      baseOption({ lettre: 'C', impact_jours: -90 }),
    ]
    expect(bestOptionByImpact(opts)).toBe('A')
  })

  it('returns positive over negative even if more options exist', () => {
    const opts = [
      baseOption({ lettre: 'A', impact_jours: -10 }),
      baseOption({ lettre: 'B', impact_jours: 1 }),  // best
      baseOption({ lettre: 'C', impact_jours: -5 }),
    ]
    expect(bestOptionByImpact(opts)).toBe('B')
  })
})

describe('countDuePeriodsForTracking', () => {
  const future = '2030-01-01T12:00:00Z'
  const past = '2020-01-01T12:00:00Z'

  it('returns 0 if status != tracking', () => {
    const t = baseTracking({ status: 'awaiting_validation', next_notif_at: past })
    expect(countDuePeriodsForTracking(t)).toBe(0)
  })

  it('returns 0 if next_notif_at is null', () => {
    const t = baseTracking({ status: 'tracking', next_notif_at: null })
    expect(countDuePeriodsForTracking(t)).toBe(0)
  })

  it('returns 0 if notif is in the future', () => {
    const t = baseTracking({ status: 'tracking', next_notif_at: future })
    expect(countDuePeriodsForTracking(t)).toBe(0)
  })

  it('returns 1 if notif is in the past and a period is pending', () => {
    const t = baseTracking({ status: 'tracking', next_notif_at: past })
    expect(countDuePeriodsForTracking(t)).toBe(1)
  })

  it('returns 0 if notif is in the past but no period is pending', () => {
    const t = baseTracking({
      status: 'tracking',
      next_notif_at: past,
      choices: [
        { periode_idx: 0, choice: '0', responded_at: '2025-01-01T00:00:00Z', retry_count: 0 },
        { periode_idx: 1, choice: '0', responded_at: '2025-01-01T00:00:00Z', retry_count: 0 },
        { periode_idx: 2, choice: '0', responded_at: '2025-01-01T00:00:00Z', retry_count: 0 },
      ],
    })
    expect(countDuePeriodsForTracking(t)).toBe(0)
  })
})

describe('formatCountdown', () => {
  const fixedNow = new Date('2026-06-01T12:00:00Z').getTime()

  it('returns "—" for null', () => {
    expect(formatCountdown(null, fixedNow)).toBe('—')
  })

  it('returns "Maintenant" for past target', () => {
    expect(formatCountdown('2026-05-01T00:00:00Z', fixedNow)).toBe('Maintenant')
  })

  it('returns minutes only for < 1 hour', () => {
    expect(formatCountdown('2026-06-01T12:30:00Z', fixedNow)).toBe('30m')
  })

  it('returns hours and minutes for > 1 hour', () => {
    expect(formatCountdown('2026-06-01T16:23:00Z', fixedNow)).toBe('4h 23m')
  })

  it('returns days and hours for > 1 day', () => {
    expect(formatCountdown('2026-06-03T15:00:00Z', fixedNow)).toBe('2j 3h')
  })

  it('handles days but 0 hours edge case', () => {
    expect(formatCountdown('2026-06-03T12:00:00Z', fixedNow)).toBe('2j 0h')
  })
})

describe('trackingProgress', () => {
  it('returns 0 for 0 responded', () => {
    const t = baseTracking({})
    expect(trackingProgress(t)).toBe(0)
  })

  it('returns 1 for all responded', () => {
    const t = baseTracking({
      choices: [
        { periode_idx: 0, choice: '0', responded_at: 'x', retry_count: 0 },
        { periode_idx: 1, choice: '1', responded_at: 'x', retry_count: 0 },
        { periode_idx: 2, choice: 'none', responded_at: 'x', retry_count: 0 },
      ],
    })
    expect(trackingProgress(t)).toBe(1)
  })

  it('returns 2/3 for partial', () => {
    const t = baseTracking({
      choices: [
        { periode_idx: 0, choice: '0', responded_at: 'x', retry_count: 0 },
        { periode_idx: 1, choice: '1', responded_at: 'x', retry_count: 0 },
        { periode_idx: 2, choice: null, responded_at: null, retry_count: 0 },
      ],
    })
    expect(trackingProgress(t)).toBeCloseTo(2 / 3, 5)
  })

  it('returns 0 if nb_periodes is 0 (degenerate)', () => {
    const t = baseTracking({ nb_periodes: 0, choices: [] })
    expect(trackingProgress(t)).toBe(0)
  })

  it('clamps at 1 if responded > nb_periodes (defensive)', () => {
    const t = baseTracking({
      nb_periodes: 2,
      choices: [
        { periode_idx: 0, choice: '0', responded_at: 'x', retry_count: 0 },
        { periode_idx: 1, choice: '0', responded_at: 'x', retry_count: 0 },
        { periode_idx: 2, choice: '0', responded_at: 'x', retry_count: 0 },
      ],
    })
    expect(trackingProgress(t)).toBe(1)
  })
})

describe('canCancelPartial', () => {
  it('false if no choice responded yet', () => {
    const t = baseTracking({})
    expect(canCancelPartial(t)).toBe(false)
  })

  it('true if at least one choice', () => {
    const t = baseTracking({
      choices: [
        { periode_idx: 0, choice: '0', responded_at: 'x', retry_count: 0 },
        { periode_idx: 1, choice: null, responded_at: null, retry_count: 0 },
        { periode_idx: 2, choice: null, responded_at: null, retry_count: 0 },
      ],
    })
    expect(canCancelPartial(t)).toBe(true)
  })

  it('true even if only "none" choices', () => {
    const t = baseTracking({
      choices: [
        { periode_idx: 0, choice: 'none', responded_at: 'x', retry_count: 0 },
        { periode_idx: 1, choice: null, responded_at: null, retry_count: 0 },
        { periode_idx: 2, choice: null, responded_at: null, retry_count: 0 },
      ],
    })
    expect(canCancelPartial(t)).toBe(true)
  })
})
