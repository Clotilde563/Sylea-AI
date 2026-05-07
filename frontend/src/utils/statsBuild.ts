/**
 * Fonctions pures pour construire les datasets des graphs de la page
 * Statistiques. Extraites de StatistiquesPage.tsx pour pouvoir etre
 * testees unitairement (Vitest).
 *
 * - buildHistoricalPoints  : Chart 2 (progression reelle dans le temps)
 * - buildSOTimelines       : Chart 1 (progression par sous-objectif)
 *
 * Logique critique avant commercialisation : ces fonctions decident de
 * la coherence visuelle des courbes vs les chiffres affiches dans les
 * cartes (PROGRESSION, TEMPS_GAGNE, etc.). Toute incoherence ici est
 * directement visible par l'utilisateur final.
 */

export interface HistPoint {
  elapsedMs: number
  prob: number
}

export interface ProfilForStats {
  cree_le?: string
  objectif_modifie_le?: string | null
  temps_initial_jours?: number | null
  temps_gagne_jours?: number | null
}

export interface DecisionForStats {
  cree_le: string
  temps_gagne_avant?: number | null
  temps_gagne_apres?: number | null
  impact_net?: number | null
  impact_sous_objectif?: number | null
  sous_objectif_id?: string | null
  sous_objectif_impacte?: string | null
}

export interface SousObjectifForStats {
  id: string
  titre: string
  progression: number
}

/**
 * Reconstruit l'historique de progression globale (Chart 2).
 *
 * Strategie :
 *   1. Construit (elapsedMs, prob%) pour chaque snapshot present sur
 *      les decisions (temps_gagne_avant/apres / temps_initial × 100)
 *   2. Si les snapshots sont stale (last != progressionActuelle),
 *      applique un correctif :
 *        - Scaling proportionnel si lastSnapshot > 0
 *        - Distribution lineaire par index si tous = 0
 *   3. Ajoute un point final (totalMs, progressionActuelle)
 *
 * Garantit que la courbe rejoint TOUJOURS progressionActuelle au "now".
 */
export function buildHistoricalPoints(
  profil: ProfilForStats | null,
  decisions: DecisionForStats[],
  // Injection optionnelle pour tests deterministes
  nowMs: number = Date.now(),
): { histPoints: HistPoint[]; totalElapsedMs: number } {
  if (!profil) return { histPoints: [], totalElapsedMs: 1 }

  const tempsInitial = profil.temps_initial_jours || 0

  const sorted = [...decisions]
    .filter((d) => d.cree_le)
    .sort((a, b) => new Date(a.cree_le).getTime() - new Date(b.cree_le).getTime())

  const oml = profil.objectif_modifie_le
  const refDate = oml
    ? oml
    : (sorted.length === 0 ? new Date(nowMs).toISOString() : profil.cree_le)
  const t0 = refDate ? new Date(refDate).getTime() : nowMs
  const totalMs = Math.max(nowMs - t0, 1)

  const progressionActuelle = tempsInitial > 0
    ? ((profil.temps_gagne_jours || 0) / tempsInitial) * 100
    : 0

  const points: HistPoint[] = []
  points.push({ elapsedMs: 0, prob: 0 })

  for (const d of sorted) {
    const tMs = new Date(d.cree_le).getTime() - t0
    if (tMs <= 0) continue
    if (tempsInitial <= 0) continue
    const tgAvant = d.temps_gagne_avant
    const tgApres = d.temps_gagne_apres
    if (tgAvant !== null && tgAvant !== undefined) {
      const progAvant = (tgAvant / tempsInitial) * 100
      points.push({ elapsedMs: tMs - 1, prob: progAvant })
    }
    if (tgApres !== null && tgApres !== undefined) {
      const progApres = (tgApres / tempsInitial) * 100
      points.push({ elapsedMs: tMs, prob: progApres })
    }
  }

  // Stale snapshot fix
  const lastSnapshotProb = points.length > 1 ? points[points.length - 1].prob : 0
  const snapshotsStale = Math.abs(lastSnapshotProb - progressionActuelle) > 0.5
  if (snapshotsStale) {
    if (lastSnapshotProb > 0) {
      const scale = progressionActuelle / lastSnapshotProb
      for (let i = 1; i < points.length; i++) {
        points[i].prob = Math.max(0, Math.min(100, points[i].prob * scale))
      }
    } else if (progressionActuelle > 0 && points.length > 1) {
      const n = points.length - 1
      for (let i = 1; i <= n; i++) {
        points[i].prob = (i / n) * progressionActuelle
      }
    }
  }

  points.push({ elapsedMs: totalMs, prob: progressionActuelle })

  return { histPoints: points, totalElapsedMs: totalMs }
}

/** Interpolation par palier : retourne la derniere proba <= ems */
export function interpolateProb(points: HistPoint[], ems: number): number {
  if (points.length === 0) return 0
  let result = points[0].prob
  for (const p of points) {
    if (p.elapsedMs <= ems) result = p.prob
    else break
  }
  return result
}

// ── Chart 1 : Timelines per Sous-Objectif ──────────────────────────────────

export interface SOTimeline {
  soId: string
  titre: string
  points: { elapsedMs: number; prog: number }[]
}

/**
 * Reconstruit les timelines de progression par sous-objectif (Chart 1).
 *
 * Pour chaque SO :
 *   - Demarre a 0%
 *   - Accumule impact_sous_objectif des decisions matchees
 *   - Si decisions presentes : scale pour matcher la progression actuelle
 *   - Si pas de decisions : ligne plate de 0 a progression actuelle
 *   - Termine au point (totalElapsedMs, currentProg)
 */
export function buildSOTimelines(
  profil: ProfilForStats | null,
  decisions: DecisionForStats[],
  sousObjectifs: SousObjectifForStats[],
  nowMs: number = Date.now(),
): { timelines: SOTimeline[]; totalElapsedMs: number } {
  if (!profil || sousObjectifs.length === 0) {
    return { timelines: [], totalElapsedMs: 1 }
  }

  const sorted = [...decisions]
    .filter((d) => d.cree_le)
    .sort((a, b) => new Date(a.cree_le).getTime() - new Date(b.cree_le).getTime())

  const oml = profil.objectif_modifie_le
  const refDate = oml
    ? oml
    : (sorted.length === 0 ? new Date(nowMs).toISOString() : profil.cree_le)
  const t0 = refDate ? new Date(refDate).getTime() : nowMs
  const totalElapsedMs = Math.max(nowMs - t0, 1)

  const idSet = new Set(sousObjectifs.map((so) => so.id))
  const titreToId: Record<string, string> = {}
  for (const so of sousObjectifs) {
    titreToId[so.titre] = so.id
  }

  const soProgression: Record<string, number> = {}
  for (const so of sousObjectifs) {
    soProgression[so.id] = 0
  }

  const timelinesMap = new Map<string, { elapsedMs: number; prog: number }[]>()
  for (const so of sousObjectifs) {
    timelinesMap.set(so.id, [{ elapsedMs: 0, prog: 0 }])
  }

  for (const d of sorted) {
    const soRef = d.sous_objectif_id || d.sous_objectif_impacte
    if (!soRef) continue
    const soId = idSet.has(soRef) ? soRef : titreToId[soRef]
    if (!soId || !timelinesMap.has(soId)) continue
    const tMs = Math.max(0, new Date(d.cree_le).getTime() - t0)
    const impact = d.impact_sous_objectif ?? d.impact_net ?? 0
    soProgression[soId] = Math.max(0, Math.min(100, soProgression[soId] + impact))
    timelinesMap.get(soId)!.push({ elapsedMs: tMs, prog: soProgression[soId] })
  }

  // Scaling + final point
  for (const so of sousObjectifs) {
    const tl = timelinesMap.get(so.id)!
    const currentProg = so.progression
    if (tl.length <= 1) {
      tl.push({ elapsedMs: totalElapsedMs, prog: currentProg })
    } else {
      const lastProg = tl[tl.length - 1].prog
      if (lastProg > 0) {
        const scale = currentProg / lastProg
        for (let i = 1; i < tl.length; i++) {
          tl[i].prog = Math.max(0, Math.min(100, tl[i].prog * scale))
        }
      }
      tl.push({ elapsedMs: totalElapsedMs, prog: currentProg })
    }
  }

  const timelines: SOTimeline[] = sousObjectifs.map((so) => ({
    soId: so.id,
    titre: so.titre,
    points: timelinesMap.get(so.id) || [{ elapsedMs: 0, prog: 0 }],
  }))

  return { timelines, totalElapsedMs }
}
