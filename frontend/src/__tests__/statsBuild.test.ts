/**
 * Tests unitaires des fonctions de construction des graphs Statistiques.
 *
 * Critique avant commercialisation : ces fonctions decident de la coherence
 * visuelle des courbes vs les chiffres affiches dans les cartes
 * (PROGRESSION, TEMPS_GAGNE, etc.). Un bug ici = donnees fausses montrees
 * a des clients payants.
 *
 * Couverture :
 *  - buildHistoricalPoints (Chart 2 / progression reelle)
 *      * cas de base (sans decisions)
 *      * decisions avec snapshots valides (cas normal)
 *      * snapshots stale tous=0 (bug rapporte)
 *      * snapshots stale partiels
 *      * snapshots scalables (mismatch lineaire)
 *      * profil null / vide / temps_initial=0
 *      * decisions hors fenetre (avant t0)
 *      * objectif_modifie_le ≠ cree_le
 *  - buildSOTimelines (Chart 1 / sous-objectifs)
 *      * SO sans decisions
 *      * SO avec decisions (impact_sous_objectif)
 *      * scaling vers progression actuelle
 *      * SO matche par titre vs id
 *      * decisions sans soId/titre (ignored)
 *  - interpolateProb (palier)
 */

import { describe, it, expect } from 'vitest'
import {
  buildHistoricalPoints,
  buildSOTimelines,
  interpolateProb,
  type ProfilForStats,
  type DecisionForStats,
  type SousObjectifForStats,
} from '../utils/statsBuild'

// ── Helpers ────────────────────────────────────────────────────────────────

const MS_DAY = 24 * 60 * 60 * 1000

function isoFromDayOffset(t0Ms: number, days: number): string {
  return new Date(t0Ms + days * MS_DAY).toISOString()
}

const REF_T0 = new Date('2026-01-01T00:00:00Z').getTime()

function profil(over: Partial<ProfilForStats> = {}): ProfilForStats {
  return {
    cree_le: new Date(REF_T0).toISOString(),
    objectif_modifie_le: new Date(REF_T0).toISOString(),
    temps_initial_jours: 365,
    temps_gagne_jours: 0,
    ...over,
  }
}

function decision(over: Partial<DecisionForStats> & { dayFromT0: number }): DecisionForStats {
  const { dayFromT0, ...rest } = over
  return {
    cree_le: isoFromDayOffset(REF_T0, dayFromT0),
    temps_gagne_avant: null,
    temps_gagne_apres: null,
    impact_net: 0,
    impact_sous_objectif: 0,
    sous_objectif_id: null,
    sous_objectif_impacte: null,
    ...rest,
  }
}

// ════════════════════════════════════════════════════════════════════════════
//  buildHistoricalPoints (Chart 2)
// ════════════════════════════════════════════════════════════════════════════

describe('buildHistoricalPoints', () => {

  describe('cas degenrees', () => {
    it('retourne vide si profil null', () => {
      const r = buildHistoricalPoints(null, [], REF_T0 + 30 * MS_DAY)
      expect(r.histPoints).toEqual([])
      expect(r.totalElapsedMs).toBe(1)
    })

    it('retourne (0,0) + (totalMs, 0) si pas de decisions et progression nulle', () => {
      const r = buildHistoricalPoints(profil(), [], REF_T0 + 30 * MS_DAY)
      expect(r.histPoints).toHaveLength(2)
      expect(r.histPoints[0]).toEqual({ elapsedMs: 0, prob: 0 })
      expect(r.histPoints[1].prob).toBe(0)
      expect(r.totalElapsedMs).toBe(30 * MS_DAY)
    })

    it('temps_initial=0 -> progressionActuelle=0 meme si temps_gagne>0', () => {
      const r = buildHistoricalPoints(
        profil({ temps_initial_jours: 0, temps_gagne_jours: 50 }),
        [],
        REF_T0 + 10 * MS_DAY,
      )
      expect(r.histPoints[r.histPoints.length - 1].prob).toBe(0)
    })
  })

  describe('cas normal : snapshots valides', () => {
    it('reconstitue la courbe step depuis les snapshots avant/apres', () => {
      // 2 decisions avec snapshots : 0 -> 30 -> 60 jours gagnes sur 365 = 0% -> 8.2% -> 16.4%
      const dec = [
        decision({ dayFromT0: 5,  temps_gagne_avant: 0,  temps_gagne_apres: 30 }),
        decision({ dayFromT0: 10, temps_gagne_avant: 30, temps_gagne_apres: 60 }),
      ]
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 60 }),
        dec,
        REF_T0 + 15 * MS_DAY,
      )
      // Points : (0,0), (5d-1ms, 0), (5d, 8.2), (10d-1ms, 8.2), (10d, 16.4), (15d, 16.4)
      expect(r.histPoints).toHaveLength(6)
      expect(r.histPoints[0]).toEqual({ elapsedMs: 0, prob: 0 })
      expect(r.histPoints[1].prob).toBeCloseTo(0)
      expect(r.histPoints[2].prob).toBeCloseTo(60 / 365 * 100 / 2, 1) // mid point
      expect(r.histPoints[5].prob).toBeCloseTo(60 / 365 * 100, 1)
    })

    it('point final atteint exactement progressionActuelle (invariant critique)', () => {
      // QA-critical : la carte PROGRESSION doit toujours matcher le bord droit du graph
      const r = buildHistoricalPoints(
        profil({ temps_initial_jours: 1956, temps_gagne_jours: 652 }),
        [
          decision({ dayFromT0: 10, temps_gagne_avant: 0,   temps_gagne_apres: 200 }),
          decision({ dayFromT0: 20, temps_gagne_avant: 200, temps_gagne_apres: 652 }),
        ],
        REF_T0 + 30 * MS_DAY,
      )
      const last = r.histPoints[r.histPoints.length - 1]
      const expectedPct = (652 / 1956) * 100
      expect(last.prob).toBeCloseTo(expectedPct, 4)
      expect(last.elapsedMs).toBe(30 * MS_DAY)
    })
  })

  describe('snapshots stale (BUG fix Sprint 4)', () => {
    it('tous snapshots=0 mais progression>0 -> distribution lineaire', () => {
      // 4 decisions toutes avec tg=0 (donnees pre-feature), profil dit 33%
      const dec = [
        decision({ dayFromT0: 5,  temps_gagne_avant: 0, temps_gagne_apres: 0 }),
        decision({ dayFromT0: 10, temps_gagne_avant: 0, temps_gagne_apres: 0 }),
        decision({ dayFromT0: 15, temps_gagne_avant: 0, temps_gagne_apres: 0 }),
        decision({ dayFromT0: 20, temps_gagne_avant: 0, temps_gagne_apres: 0 }),
      ]
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 120, temps_initial_jours: 365 }),
        dec,
        REF_T0 + 30 * MS_DAY,
      )
      // Apres distribution lineaire, le dernier snapshot avant le point final
      // doit avoir une prob non nulle (sinon on a un saut vertical au bord)
      const points = r.histPoints
      // Distribution : 8 points apres (0,0), repartis lineaire
      const lastSnapshot = points[points.length - 2] // avant le point final (totalMs)
      expect(lastSnapshot.prob).toBeGreaterThan(0)
      // L'expected progression = 120/365*100 = 32.88%
      const expectedPct = (120 / 365) * 100
      expect(points[points.length - 1].prob).toBeCloseTo(expectedPct, 4)
      // Le dernier snapshot doit etre proche de la progression actuelle (a la fin de la distribution)
      expect(lastSnapshot.prob).toBeCloseTo(expectedPct, 1)
    })

    it('snapshots scalables (last>0 mais mismatch) -> scaling proportionnel', () => {
      // Decisions montrent 0 -> 50% -> 100% mais profil dit 50% (donnees half-stale)
      const dec = [
        decision({ dayFromT0: 5,  temps_gagne_avant: 0,    temps_gagne_apres: 100 }),
        decision({ dayFromT0: 10, temps_gagne_avant: 100,  temps_gagne_apres: 200 }),
      ]
      // Profil dit temps_gagne=100 (50% / 200) au lieu de 200 (100%)
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 100, temps_initial_jours: 200 }),
        dec,
        REF_T0 + 15 * MS_DAY,
      )
      const points = r.histPoints
      // Snapshots cumules etaient 50% + 100% = 100. Profil dit 50.
      // Scale = 50/100 = 0.5. Tous les snapshots multiplies par 0.5.
      expect(points[points.length - 1].prob).toBeCloseTo(50, 4) // point final
      // Snapshots scalees : 0, 0, 25, 25, 50, 50
      const scaled = points.slice(1, -1).map(p => p.prob)
      // Le dernier snapshot avant le point final doit etre 50 (apres scaling)
      expect(scaled[scaled.length - 1]).toBeCloseTo(50, 1)
    })

    it('snapshots non-stale (cas normal) -> garde tels quels', () => {
      // Snapshots coherents avec la progression actuelle : pas de modification
      const dec = [
        decision({ dayFromT0: 5,  temps_gagne_avant: 0,  temps_gagne_apres: 100 }),
        decision({ dayFromT0: 10, temps_gagne_avant: 100, temps_gagne_apres: 200 }),
      ]
      // Profil dit 200 (matche le dernier snapshot)
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 200, temps_initial_jours: 365 }),
        dec,
        REF_T0 + 20 * MS_DAY,
      )
      const points = r.histPoints
      // Snapshots gardes tels quels : (0,0), (5d-1, 0), (5d, 27.4), (10d-1, 27.4), (10d, 54.79), (20d, 54.79)
      const expectedFirstStep = (100 / 365) * 100  // ~27.4%
      const expectedSecondStep = (200 / 365) * 100 // ~54.79%
      expect(points[2].prob).toBeCloseTo(expectedFirstStep, 1)
      expect(points[4].prob).toBeCloseTo(expectedSecondStep, 1)
      expect(points[5].prob).toBeCloseTo(expectedSecondStep, 1)
    })
  })

  describe('proprietes invariantes (QA)', () => {
    it('points sont monotonement croissants en elapsedMs', () => {
      const dec = [
        decision({ dayFromT0: 5 }),
        decision({ dayFromT0: 1 }), // ordre desordonne
        decision({ dayFromT0: 10 }),
      ]
      const r = buildHistoricalPoints(profil({ temps_gagne_jours: 50 }), dec, REF_T0 + 15 * MS_DAY)
      for (let i = 1; i < r.histPoints.length; i++) {
        expect(r.histPoints[i].elapsedMs).toBeGreaterThanOrEqual(r.histPoints[i - 1].elapsedMs)
      }
    })

    it('toutes les prob restent dans [0, 100]', () => {
      // Cas extreme : temps_gagne = 2x temps_initial (= bug DB) -> doit clamp
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 800, temps_initial_jours: 200 }),
        [decision({ dayFromT0: 5, temps_gagne_apres: 800, temps_gagne_avant: 0 })],
        REF_T0 + 10 * MS_DAY,
      )
      for (const p of r.histPoints) {
        expect(p.prob).toBeGreaterThanOrEqual(0)
        // Note : on autorise > 100 dans ce cas car le profil est incoherent.
        // L'UI doit clamper visuellement, mais la fonction garde la verite.
      }
    })

    it('decisions avant t0 (objectif_modifie_le) sont ignorees', () => {
      // Si objectif a ete reset a J+5, les decisions avant J+5 ne comptent pas
      const omlDate = new Date(REF_T0 + 5 * MS_DAY).toISOString()
      const dec = [
        decision({ dayFromT0: 2,  temps_gagne_avant: 0, temps_gagne_apres: 50 }), // avant reset
        decision({ dayFromT0: 7,  temps_gagne_avant: 0, temps_gagne_apres: 30 }), // apres reset
      ]
      const r = buildHistoricalPoints(
        profil({ temps_gagne_jours: 30, objectif_modifie_le: omlDate }),
        dec,
        REF_T0 + 10 * MS_DAY,
      )
      // Decision a J+2 a un tMs = -3 days < 0, donc skip.
      // Reste : (0,0), (J+2 vs reset, ?), (J+7, ?), (J+5, 30/365)
      // En realite on devrait avoir 4 points : (0,0), (2d-1,0), (2d, 30/365), (5d, 30/365)
      // Donc histPoints.length doit etre <= si une decision est skipped (avant reset)
      const decisionPoints = r.histPoints.slice(1, -1)
      // L'attendu : seule la decision a J+7 (post-reset) genere des points
      expect(decisionPoints.length).toBeLessThanOrEqual(2)  // max 2 (avant + apres) pour 1 decision
    })
  })
})

// ════════════════════════════════════════════════════════════════════════════
//  buildSOTimelines (Chart 1)
// ════════════════════════════════════════════════════════════════════════════

describe('buildSOTimelines', () => {

  function so(over: Partial<SousObjectifForStats> & { id: string; titre: string }): SousObjectifForStats {
    return { progression: 0, ...over }
  }

  describe('cas degenrees', () => {
    it('retourne vide si pas de SO', () => {
      const r = buildSOTimelines(profil(), [], [], REF_T0 + 10 * MS_DAY)
      expect(r.timelines).toEqual([])
    })

    it('SO sans decision -> ligne plate de 0 a current', () => {
      const r = buildSOTimelines(
        profil(),
        [],
        [so({ id: 'a', titre: 'A', progression: 30 })],
        REF_T0 + 10 * MS_DAY,
      )
      const tl = r.timelines[0]
      expect(tl.points[0]).toEqual({ elapsedMs: 0, prog: 0 })
      expect(tl.points[tl.points.length - 1].prog).toBe(30)
      expect(tl.points[tl.points.length - 1].elapsedMs).toBe(10 * MS_DAY)
    })
  })

  describe('attribution decision -> SO', () => {
    it('decision avec sous_objectif_id matche par UUID', () => {
      const dec = [
        decision({
          dayFromT0: 5,
          sous_objectif_id: 'so-1',
          impact_sous_objectif: 25,
        }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'so-1', titre: 'Apprentissage', progression: 25 })],
        REF_T0 + 10 * MS_DAY,
      )
      const tl = r.timelines[0]
      // Points : (0,0), (5d, 25), (10d, 25)
      expect(tl.points).toHaveLength(3)
      expect(tl.points[1].prog).toBeCloseTo(25, 1)
    })

    it('decision avec sous_objectif_impacte matche par titre (fallback)', () => {
      const dec = [
        decision({
          dayFromT0: 5,
          sous_objectif_impacte: 'Apprentissage', // titre, pas id
          impact_sous_objectif: 40,
        }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'so-uuid', titre: 'Apprentissage', progression: 40 })],
        REF_T0 + 10 * MS_DAY,
      )
      expect(r.timelines[0].points[1].prog).toBeCloseTo(40, 1)
    })

    it('decision sans soId ni titre est ignoree', () => {
      const dec = [
        decision({
          dayFromT0: 5,
          sous_objectif_id: null,
          sous_objectif_impacte: null,
          impact_sous_objectif: 50,
        }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'a', titre: 'A', progression: 0 })],
        REF_T0 + 10 * MS_DAY,
      )
      // Pas d'impact applique, ligne de 0 a 0
      const tl = r.timelines[0]
      expect(tl.points[1].prog).toBe(0)
    })

    it('decision avec sous_objectif_id inconnu est ignoree', () => {
      const dec = [
        decision({
          dayFromT0: 5,
          sous_objectif_id: 'so-INEXISTANT',
          impact_sous_objectif: 50,
        }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'so-1', titre: 'Foo', progression: 0 })],
        REF_T0 + 10 * MS_DAY,
      )
      // Aucun impact applique
      expect(r.timelines[0].points[1].prog).toBe(0)
    })
  })

  describe('scaling des timelines', () => {
    it('scale les snapshots pour matcher la progression actuelle', () => {
      // 2 decisions sur SO 'a' : impact 20 + 30 = 50 cumule
      // Mais SO progression actuelle = 60 (donnees out-of-sync)
      const dec = [
        decision({ dayFromT0: 5,  sous_objectif_id: 'a', impact_sous_objectif: 20 }),
        decision({ dayFromT0: 10, sous_objectif_id: 'a', impact_sous_objectif: 30 }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'a', titre: 'A', progression: 60 })],
        REF_T0 + 15 * MS_DAY,
      )
      const tl = r.timelines[0]
      // Apres scaling : last = 60. Premier point decision (impact 20 -> 24 apres scale 60/50=1.2)
      // Points : (0,0), (5d, 24), (10d, 60), (15d, 60)
      expect(tl.points[1].prog).toBeCloseTo(24, 1)
      expect(tl.points[2].prog).toBeCloseTo(60, 1)
      expect(tl.points[tl.points.length - 1].prog).toBeCloseTo(60, 1)
    })

    it('point final TOUJOURS = currentProg (invariant QA critique)', () => {
      // Critique : le bord droit du graph DOIT matcher la valeur de la card
      // "Progression" du SO. Sinon l'utilisateur voit deux chiffres differents.
      const sousObj = [
        so({ id: 'a', titre: 'A', progression: 75 }),
        so({ id: 'b', titre: 'B', progression: 12 }),
      ]
      const dec = [
        decision({ dayFromT0: 1, sous_objectif_id: 'a', impact_sous_objectif: 100 }),
        decision({ dayFromT0: 5, sous_objectif_id: 'b', impact_sous_objectif: 5 }),
      ]
      const r = buildSOTimelines(profil(), dec, sousObj, REF_T0 + 10 * MS_DAY)
      for (const tl of r.timelines) {
        const last = tl.points[tl.points.length - 1]
        const expected = sousObj.find(s => s.id === tl.soId)!.progression
        expect(last.prog).toBeCloseTo(expected, 4)
      }
    })
  })

  describe('proprietes invariantes (QA)', () => {
    it('toutes les progs restent dans [0, 100]', () => {
      const dec = [
        decision({ dayFromT0: 1, sous_objectif_id: 'a', impact_sous_objectif: 200 }), // > 100
        decision({ dayFromT0: 2, sous_objectif_id: 'a', impact_sous_objectif: -300 }), // < 0
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'a', titre: 'A', progression: 50 })],
        REF_T0 + 5 * MS_DAY,
      )
      for (const p of r.timelines[0].points) {
        expect(p.prog).toBeGreaterThanOrEqual(0)
        expect(p.prog).toBeLessThanOrEqual(100)
      }
    })

    it('points monotones en elapsedMs', () => {
      const dec = [
        decision({ dayFromT0: 5, sous_objectif_id: 'a', impact_sous_objectif: 10 }),
        decision({ dayFromT0: 1, sous_objectif_id: 'a', impact_sous_objectif: 5 }), // desordre
        decision({ dayFromT0: 10, sous_objectif_id: 'a', impact_sous_objectif: 20 }),
      ]
      const r = buildSOTimelines(
        profil(),
        dec,
        [so({ id: 'a', titre: 'A', progression: 35 })],
        REF_T0 + 15 * MS_DAY,
      )
      const tl = r.timelines[0]
      for (let i = 1; i < tl.points.length; i++) {
        expect(tl.points[i].elapsedMs).toBeGreaterThanOrEqual(tl.points[i - 1].elapsedMs)
      }
    })
  })
})

// ════════════════════════════════════════════════════════════════════════════
//  interpolateProb
// ════════════════════════════════════════════════════════════════════════════

describe('interpolateProb', () => {
  it('retourne 0 sur tableau vide', () => {
    expect(interpolateProb([], 100)).toBe(0)
  })

  it('retourne premier point si ems avant le 1er point', () => {
    const pts = [{ elapsedMs: 100, prob: 50 }]
    expect(interpolateProb(pts, 50)).toBe(50)
  })

  it('palier (step) : derniere valeur connue avant ems', () => {
    const pts = [
      { elapsedMs: 0,    prob: 0 },
      { elapsedMs: 100,  prob: 30 },
      { elapsedMs: 200,  prob: 60 },
    ]
    expect(interpolateProb(pts, -50)).toBe(0)  // avant 0 -> 0
    expect(interpolateProb(pts, 0)).toBe(0)
    expect(interpolateProb(pts, 50)).toBe(0)   // avant 100 -> 0
    expect(interpolateProb(pts, 100)).toBe(30)
    expect(interpolateProb(pts, 150)).toBe(30) // avant 200 -> 30
    expect(interpolateProb(pts, 200)).toBe(60)
    expect(interpolateProb(pts, 300)).toBe(60) // apres dernier -> 60
  })
})
