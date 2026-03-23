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
  DeviceContext,
} from '../types'

const BASE = '/api'
const AUTH_TOKEN_KEY = 'sylea_auth_token'

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem(AUTH_TOKEN_KEY)
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: getAuthHeaders(),
    ...options,
  })
  if (!res.ok) {
    // Token expiré ou invalide → déconnexion automatique
    if (res.status === 401) {
      localStorage.removeItem(AUTH_TOKEN_KEY)
      localStorage.removeItem('sylea_auth_user')
      window.location.href = '/login'
      throw new Error('Session expirée')
    }
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
  recalculerProbabilite: (contexte_appareil?: DeviceContext): Promise<ProbabiliteResult> =>
    request<ProbabiliteResult>('/profil/probabilite', {
      method: 'POST',
      body: JSON.stringify({ contexte_appareil }),
    }),

  // Supprimer le profil
  supprimerProfil: (): Promise<{ detail: string }> =>
    request<{ detail: string }>('/profil', { method: 'DELETE' }),

  // ── Dilemme ────────────────────────────────────────────────────────────────

  // Analyser un dilemme (appel IA) — N options
  analyserDilemme: (data: {
    question: string
    options: string[]
    impact_temporel_jours?: number
    contexte_appareil?: DeviceContext
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
    impact_temporel_jours?: number
    contexte_appareil?: DeviceContext
  }): Promise<Decision> =>
    request<Decision>('/dilemme/choisir', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── Historique ────────────────────────────────────────────────────────────

  // Liste des décisions
  getHistorique: (limite = 20): Promise<Decision[]> =>
    request<Decision[]>(`/historique?limite=${limite}`),

  deleteDecision: (id: string): Promise<void> =>
    request<void>(`/historique/${id}`, { method: 'DELETE' }),

  getHistoriquePagine: (params: {
    page?: number; par_page?: number; tri?: string; recherche?: string
  } = {}): Promise<{
    decisions: Decision[]; total: number; page: number; par_page: number; pages_total: number
  }> => {
    const p = params.page ?? 1
    const pp = params.par_page ?? 10
    const tri = params.tri ?? 'recent'
    const rech = params.recherche ?? ''
    return request(`/historique/pagine?page=${p}&par_page=${pp}&tri=${tri}&recherche=${encodeURIComponent(rech)}`)
  },

  // Analyser la journée pour en extraire les scores bien-être
  analyserJournee: (description: string, contexte_appareil?: DeviceContext): Promise<BienEtreScores> =>
    request<BienEtreScores>('/profil/analyser-journee', {
      method: 'POST',
      body: JSON.stringify({ description, contexte_appareil }),
    }),

  // Générer 12 questions personnalisées basées sur l'objectif
  genererQuestions: (description: string, contexte_appareil?: DeviceContext): Promise<string[]> =>
    request<string[]>('/profil/generer-questions', {
      method: 'POST',
      body: JSON.stringify({ description, contexte_appareil }),
    }),


  // ── Evenement ──────────────────────────────────────────────────────────────────

  // Analyser un evenement (appel IA)
  analyserEvenement: (description: string, contexte_appareil?: DeviceContext): Promise<AnalyseEvenement> =>
    request<AnalyseEvenement>('/evenement/analyser', {
      method: 'POST',
      body: JSON.stringify({ description, contexte_appareil }),
    }),

  // Confirmer un evenement et sauvegarder la decision
  confirmerEvenement: (data: {
    description: string
    impact_probabilite: number
    resume: string
    contexte_appareil?: DeviceContext
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

  genererSousObjectifs: (contexte_appareil?: DeviceContext): Promise<SousObjectif[]> =>
    request<SousObjectif[]>('/sous-objectifs/generer', {
      method: 'POST',
      body: JSON.stringify({ contexte_appareil }),
    }),

  // ── Taches quotidiennes ─────────────────────────────────────────────────

  checkTachesAujourdhui: (): Promise<TachesCheck> =>
    request<TachesCheck>('/taches/aujourd-hui'),

  genererTaches: (contexte_appareil?: DeviceContext): Promise<TachesQuotidiennes> =>
    request<TachesQuotidiennes>('/taches/generer', {
      method: 'POST',
      body: JSON.stringify({ contexte_appareil }),
    }),

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

  // ── Service client chatbot ──────────────────────────────────────────

  serviceClientChat: (messages: { role: string; content: string }[], contexte_appareil?: DeviceContext): Promise<{ message: string }> =>
    request<{ message: string }>('/service-client/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil }),
    }),

  // ── Agent companion (Agent Sylea 1) ──────────────────────────────────

  agentChat: (messages: Array<{ role: string; content: string }>, contexte_appareil?: DeviceContext): Promise<{ message: string }> =>
    request<{ message: string }>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil }),
    }),

  // ── Auth ────────────────────────────────────────────────────────────────
  authLogin: (email: string, password: string): Promise<{ token: string; user: { id: string; email: string; provider: string } }> =>
    request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  authRegister: (email: string, password: string): Promise<{ requires_verification?: boolean; message?: string; token?: string }> =>
    request('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  authVerify: (email: string, code: string): Promise<{ access_token: string }> =>
    request('/auth/verify', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    }),

  authMe: (): Promise<{ id: string; email: string; provider: string }> =>
    request('/auth/me'),
}
