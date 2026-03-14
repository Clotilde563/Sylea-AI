// Client API typé pour Syléa.AI

import type {
  Profil,
  ProfilIn,
  AnalyseDilemme,
  AnalyseEvenement,
  Decision,
  ProbabiliteResult,
  BienEtreScores,
  BilanQuotidien,
  BilanCheck,
  SousObjectif,
  TachesQuotidiennes,
  TachesCheck,
  CompleterTacheResult,
  PersonnaliteIA,
} from '../types'

const BASE = '/api'

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Erreur ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Profil ────────────────────────────────────────────────────────────────────

export const api = {
  // Charger le profil existant (404 si absent)
  getProfil: (): Promise<Profil> =>
    request<Profil>('/profil'),

  // Créer ou mettre à jour le profil
  upsertProfil: (data: ProfilIn): Promise<Profil> =>
    request<Profil>('/profil', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Recalculer la probabilité
  recalculerProbabilite: (): Promise<ProbabiliteResult> =>
    request<ProbabiliteResult>('/profil/probabilite', { method: 'POST' }),

  // Supprimer le profil
  supprimerProfil: (): Promise<{ detail: string }> =>
    request<{ detail: string }>('/profil', { method: 'DELETE' }),

  // ── Dilemme ────────────────────────────────────────────────────────────────

  // Analyser un dilemme (appel IA) — N options
  analyserDilemme: (data: {
    question: string
    options: string[]
  }): Promise<AnalyseDilemme> =>
    request<AnalyseDilemme>('/dilemme/analyser', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Valider un choix et sauvegarder la décision
  choisirOption: (data: {
    question: string
    options: {
      lettre: string
      description: string
      pros: string[]
      cons: string[]
      impact_probabilite: number
      resume: string
    }[]
    choix: string  // "A", "B", "C"...
  }): Promise<Decision> =>
    request<Decision>('/dilemme/choisir', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── Historique ────────────────────────────────────────────────────────────

  // Liste des décisions
  getHistorique: (limite = 20): Promise<Decision[]> =>
    request<Decision[]>(`/historique?limite=${limite}`),

  // Analyser la journée pour en extraire les scores bien-être
  analyserJournee: (description: string): Promise<BienEtreScores> =>
    request<BienEtreScores>('/profil/analyser-journee', {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),

  // Générer 12 questions personnalisées basées sur l'objectif
  genererQuestions: (description: string): Promise<string[]> =>
    request<string[]>('/profil/generer-questions', {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),


  // ── Evenement ──────────────────────────────────────────────────────────────────

  // Analyser un evenement (appel IA)
  analyserEvenement: (description: string): Promise<AnalyseEvenement> =>
    request<AnalyseEvenement>('/evenement/analyser', {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),

  // Confirmer un evenement et sauvegarder la decision
  confirmerEvenement: (data: {
    description: string
    impact_probabilite: number
    resume: string
  }): Promise<Decision> =>
    request<Decision>('/evenement/confirmer', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── Health ─────────────────────────────────────────────────────────────────

  health: (): Promise<{ status: string; version: string }> =>
    request<{ status: string; version: string }>('/health'),

  // ── Bilan quotidien ─────────────────────────────────────────────────────────────────

  // Vérifier si le bilan du jour est fait
  checkBilanAujourdhui: (): Promise<BilanCheck> =>
    request<BilanCheck>('/bilan/aujourd-hui'),

  // Créer le bilan du jour
  creerBilan: (data: {
    niveau_sante: number
    niveau_stress: number
    niveau_energie: number
    niveau_bonheur: number
    heures_travail: number
    heures_sommeil: number
    heures_loisirs: number
    heures_transport: number
    heures_objectif: number
    description: string
  }): Promise<BilanQuotidien> =>
    request<BilanQuotidien>('/bilan', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── Sous-objectifs ──────────────────────────────────────────────────────

  getSousObjectifs: (): Promise<SousObjectif[]> =>
    request<SousObjectif[]>('/sous-objectifs'),

  genererSousObjectifs: (): Promise<SousObjectif[]> =>
    request<SousObjectif[]>('/sous-objectifs/generer', { method: 'POST' }),

  // ── Taches quotidiennes ─────────────────────────────────────────────────

  checkTachesAujourdhui: (): Promise<TachesCheck> =>
    request<TachesCheck>('/taches/aujourd-hui'),

  genererTaches: (): Promise<TachesQuotidiennes> =>
    request<TachesQuotidiennes>('/taches/generer', { method: 'POST' }),

  completerTache: (tache_id: string): Promise<CompleterTacheResult> =>
    request<CompleterTacheResult>('/taches/completer', {
      method: 'POST',
      body: JSON.stringify({ tache_id }),
    }),

  abandonnerTaches: (): Promise<{ detail: string }> =>
    request<{ detail: string }>('/taches/abandonner', { method: 'POST' }),

  // ── Personnalite IA ─────────────────────────────────────────────────────

  getPersonnalite: (): Promise<PersonnaliteIA> =>
    request<PersonnaliteIA>('/profil/personnalite'),
}
