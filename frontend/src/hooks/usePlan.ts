// Hook React qui expose le plan d'abonnement de l'utilisateur courant.
//
// Utilise par les composants qui ont besoin de gater des fonctionnalites
// premium (ex: tile "Que faire ?", Agent 2, Sylea Desktop) selon que l'user
// soit Free ou Avance.
//
// Cache module-level : une seule requete /api/plan par session, partagee
// entre tous les composants. Au logout, useAuthStore vide le cache via
// invalidatePlanCache() pour eviter de fuir le plan d'un compte vers l'autre.

import { useEffect, useState } from 'react'
import { api } from '../api/client'

// Note : 'pro' garde sa place comme alias backward-compat pour les comptes
// crees avant le rename pro -> advanced. Toute la logique d'app traite
// 'pro' comme equivalent a 'advanced'.
export type PlanName = 'free' | 'advanced' | 'pro' | 'team' | string

export interface UsePlanResult {
  plan: PlanName | null
  isFree: boolean
  isAdvanced: boolean   // advanced/pro ou team (toute souscription payante)
  loading: boolean
}

// Cache module-level pour eviter le fetch redondant entre composants.
let _cachedPlan: PlanName | null = null
let _cachedPromise: Promise<PlanName> | null = null
const _listeners = new Set<(p: PlanName | null) => void>()

async function _fetchPlan(): Promise<PlanName> {
  if (_cachedPlan !== null) return _cachedPlan
  if (_cachedPromise !== null) return _cachedPromise
  _cachedPromise = api.getPlan()
    .then(d => {
      _cachedPlan = (d?.plan?.name || 'free') as PlanName
      _listeners.forEach(fn => fn(_cachedPlan))
      return _cachedPlan
    })
    .catch(() => {
      _cachedPlan = 'free'
      _listeners.forEach(fn => fn(_cachedPlan))
      return _cachedPlan as PlanName
    })
    .finally(() => {
      _cachedPromise = null
    })
  return _cachedPromise
}

/** Vide le cache du plan (a appeler au logout / changement de compte). */
export function invalidatePlanCache(): void {
  _cachedPlan = null
  _cachedPromise = null
  _listeners.forEach(fn => fn(null))
}

export function usePlan(): UsePlanResult {
  const [plan, setPlan] = useState<PlanName | null>(_cachedPlan)
  const [loading, setLoading] = useState<boolean>(_cachedPlan === null)

  useEffect(() => {
    let mounted = true
    const listener = (p: PlanName | null) => {
      if (!mounted) return
      setPlan(p)
      setLoading(false)
    }
    _listeners.add(listener)
    if (_cachedPlan !== null) {
      setPlan(_cachedPlan)
      setLoading(false)
    } else {
      _fetchPlan().then(() => {
        if (mounted) setLoading(false)
      })
    }
    return () => {
      mounted = false
      _listeners.delete(listener)
    }
  }, [])

  return {
    plan,
    isFree: plan === null || plan === 'free',
    isAdvanced: plan === 'advanced' || plan === 'pro' || plan === 'team',
    loading,
  }
}
