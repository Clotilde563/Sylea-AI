// Helpers purs pour le systeme tracking — extraits pour facilier les tests.

import type { TrackingItem, AnalyseOption } from '../types'

/**
 * Decide si on doit afficher un badge "Recommande" sur une option.
 *
 * Regle (revisitee 2026-05-28) : on recommande TOUJOURS une option si il y
 * en a au moins une. C'est la option avec le MEILLEUR impact, meme si toutes
 * sont negatives. Recommander "la moins pire" donne un signal d'arbitrage
 * utile a l'utilisateur. Le verdict apporte la nuance (ex: "aucune n'est
 * vraiment alignee, mais si tu dois en choisir une, prends A").
 */
export function shouldShowRecommendation(options: AnalyseOption[]): boolean {
  return options.length > 0
}

/**
 * Retourne la lettre de l'option avec le meilleur impact (= impact_jours
 * le plus eleve). Sert de fallback si analyse.option_recommandee est absent
 * ou incoherent.
 */
export function bestOptionByImpact(options: AnalyseOption[]): string | null {
  if (options.length === 0) return null
  let best = options[0]
  for (const o of options.slice(1)) {
    if ((o.impact_jours ?? 0) > (best.impact_jours ?? 0)) best = o
  }
  return best.lettre
}

/**
 * Compte les periodes due (= notif arrivee a echeance mais pas repondue).
 */
export function countDuePeriodsForTracking(
  tracking: Pick<TrackingItem, 'status' | 'next_notif_at' | 'choices'>,
  now: number = Date.now(),
): number {
  if (tracking.status !== 'tracking') return 0
  if (!tracking.next_notif_at) return 0
  const target = new Date(tracking.next_notif_at).getTime()
  if (now < target) return 0
  const idx = tracking.choices.findIndex(c => c.choice === null)
  return idx >= 0 ? 1 : 0
}

/**
 * Format d'un compte a rebours human-friendly :
 * - "Maintenant" si echeance depassee
 * - "2j 3h"  pour > 1 jour
 * - "4h 23m" pour > 1 heure
 * - "12m"    pour < 1 heure
 * - "—"      si null
 */
export function formatCountdown(targetIso: string | null, now: number = Date.now()): string {
  if (!targetIso) return '—'
  const target = new Date(targetIso).getTime()
  const diffMs = target - now
  if (diffMs <= 0) return 'Maintenant'
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))
  if (days > 0) return `${days}j ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

/**
 * Calcule le ratio de progression (0 -> 1) d'un tracking en cours.
 */
export function trackingProgress(tracking: Pick<TrackingItem, 'choices' | 'nb_periodes'>): number {
  if (tracking.nb_periodes <= 0) return 0
  const responded = tracking.choices.filter(c => c.choice !== null).length
  return Math.min(1, responded / tracking.nb_periodes)
}

/**
 * Verifie si la cancellation 'partial' a un sens (= au moins 1 reponse deja
 * enregistree). Sinon on n'a rien a appliquer, le mode 'zero' suffit.
 */
export function canCancelPartial(tracking: Pick<TrackingItem, 'choices'>): boolean {
  return tracking.choices.some(c => c.choice !== null)
}
