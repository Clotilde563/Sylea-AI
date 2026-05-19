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
  AgentProposal,
} from '../types'

export const API_BASE = import.meta.env.VITE_API_URL || ''
const BASE = `${API_BASE}/api`
const AUTH_TOKEN_KEY = 'sylea_auth_token'
const CSRF_COOKIE_NAME = 'sylea_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'

/**
 * Lit le cookie CSRF posé par le backend sur chaque GET.
 *
 * Le cookie est non-HttpOnly (lisible JS) pour que ce double-submit
 * pattern fonctionne : on lit le cookie côté JS et on le renvoie en
 * header `X-CSRF-Token` sur tous les POST/PUT/PATCH/DELETE.
 *
 * Voir api/csrf_middleware.py côté backend.
 */
function getCsrfToken(): string {
  try {
    const match = document.cookie
      .split('; ')
      .find((c) => c.startsWith(`${CSRF_COOKIE_NAME}=`))
    return match ? match.split('=')[1] : ''
  } catch {
    return ''
  }
}

/**
 * Méthodes HTTP qui nécessitent un token CSRF côté backend.
 * Doit matcher api/csrf_middleware.py _UNSAFE_METHODS.
 */
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export function getAuthHeaders(method?: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem(AUTH_TOKEN_KEY)
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  // Inject X-CSRF-Token sur les méthodes mutantes. Si le cookie n'est pas
  // encore posé (1er chargement avant le 1er GET), le header sera vide et
  // le backend retournera 403 — corrigé par un GET préalable (cf. ensureCsrfCookie).
  if (method && UNSAFE_METHODS.has(method.toUpperCase())) {
    const csrf = getCsrfToken()
    if (csrf) {
      headers[CSRF_HEADER_NAME] = csrf
    }
  }
  return headers
}

/**
 * Garantit qu'on a un cookie CSRF avant la première requête mutante.
 *
 * Le cookie est posé par le backend sur n'importe quel GET. On déclenche
 * donc un GET léger (/api/health) si on n'a pas encore de cookie en
 * localStorage flag. Idempotent — appelable plusieurs fois sans coût.
 */
let _csrfReady = false
async function ensureCsrfCookie(): Promise<void> {
  if (_csrfReady || getCsrfToken()) {
    _csrfReady = true
    return
  }
  try {
    await fetch(`${API_BASE}/api/health`, { credentials: 'include' })
    _csrfReady = true
  } catch {
    // si /api/health échoue, on ne bloque pas — le backend renverra l'erreur réelle
    // sur l'appel mutant
  }
}

// Messages FR user-friendly par status HTTP.
const HTTP_STATUS_FR: Record<number, string> = {
  400: 'Requête mal formée.',
  403: 'Accès refusé.',
  404: 'Ressource introuvable.',
  408: 'Le serveur met trop de temps à répondre.',
  409: 'Conflit : la ressource existe déjà ou a été modifiée.',
  413: 'Contenu trop volumineux.',
  422: 'Données invalides.',
  429: 'Trop de requêtes — réessaie dans quelques secondes.',
  500: 'Erreur serveur — réessaie plus tard.',
  502: 'Service indisponible.',
  503: 'Service surchargé — réessaie plus tard.',
  504: 'Délai dépassé côté serveur.',
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const method = (options?.method || 'GET').toUpperCase()
  // Avant un POST/PUT/PATCH/DELETE : on s'assure qu'on a bien un cookie CSRF.
  // Le cookie est posé par le backend sur n'importe quel GET (cf. CSRFMiddleware).
  if (UNSAFE_METHODS.has(method)) {
    await ensureCsrfCookie()
  }

  // Merge des headers : custom headers passés par l'appelant > auth/CSRF.
  // On utilise un Headers object pour gérer la casse correctement.
  const finalHeaders: Record<string, string> = {
    ...getAuthHeaders(method),
    ...(options?.headers as Record<string, string> | undefined),
  }

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: finalHeaders,
      // credentials: 'include' = envoie les cookies cross-origin
      // (localhost:5173 frontend <-> localhost:8000 backend).
      // Nécessaire pour que le cookie sylea_csrf soit propagé.
      credentials: 'include',
    })
  } catch (e) {
    // Erreurs réseau (offline, CORS, DNS) — pas de res.ok
    throw new Error('Connexion au serveur impossible. Vérifie ta connexion internet.')
  }
  if (!res.ok) {
    // Token expiré ou invalide → déconnexion automatique avec message clair.
    if (res.status === 401) {
      localStorage.removeItem(AUTH_TOKEN_KEY)
      localStorage.removeItem('sylea_auth_user')
      // Flag pour la page login : affiche un banner "session expirée".
      try {
        sessionStorage.setItem('sylea_session_expired', '1')
      } catch {
        // ignore
      }
      // Laisse un court delai pour que l'UI appelante puisse catch avant redirect.
      setTimeout(() => {
        window.location.href = '/login?expired=1'
      }, 100)
      throw new Error('Session expirée — redirection vers la page de connexion…')
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const friendly = HTTP_STATUS_FR[res.status]
    const detail = err.detail || friendly || `Erreur ${res.status}`
    throw new Error(detail)
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

  // Upload photo de profil (multipart/form-data)
  uploadProfilPhoto: async (file: File): Promise<{ photo_url: string; filename: string }> => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY)
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(`${BASE}/profil/photo`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    })
    if (!r.ok) {
      const err = await r.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${r.status}`)
    }
    return r.json()
  },

  deleteProfilPhoto: (): Promise<{ deleted: boolean }> =>
    request<{ deleted: boolean }>('/profil/photo', { method: 'DELETE' }),

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
    impact_jours?: number
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

  agentChat: (messages: Array<{ role: string; content: string; type?: string }>, contexte_appareil?: DeviceContext, audioData?: string): Promise<{ message: string; choices?: string[]; audioData?: string; proposal?: AgentProposal | null }> =>
    request<{ message: string; choices?: string[]; audioData?: string; proposal?: AgentProposal | null }>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil, audio_data: audioData }),
    }),

  getAgentMessages: (): Promise<Array<{ id: string; role: string; content: string; type: string; created_at: string; audioData?: string }>> =>
    request('/agent/messages'),

  clearAgentMessages: (): Promise<{ detail: string }> =>
    request('/agent/messages', { method: 'DELETE' }),

  agentProactive: (): Promise<{ message: string | null }> =>
    request('/agent/proactive', { method: 'POST' }),

  // ── Agent proposals (boutons Confirmer/Refuser dans la chat) ────────────
  listAgentProposals: (): Promise<AgentProposal[]> =>
    request('/agent/proposals'),

  confirmAgentProposal: (id: string): Promise<{ detail: string; decision_id: string; sous_objectif_impacte: string | null; temps_gagne_jours: number; probabilite_actuelle: number }> =>
    request(`/agent/proposals/${id}/confirm`, { method: 'POST' }),

  rejectAgentProposal: (id: string): Promise<{ detail: string }> =>
    request(`/agent/proposals/${id}/reject`, { method: 'POST' }),

  agentCheckContext: (type: string, question: string, options?: string[], deviceContext?: DeviceContext): Promise<{ needs_context: boolean; agent_question: string | null; choices: string[] | null }> =>
    request('/agent/check-context', {
      method: 'POST',
      body: JSON.stringify({ type, question, options, contexte_appareil: deviceContext }),
    }),

  agentSaveContext: (contextText: string, relatedTo: string, type?: string, question?: string, options?: string[]): Promise<{ ok: boolean; sufficient: boolean; feedback: string | null }> =>
    request('/agent/save-context', {
      method: 'POST',
      body: JSON.stringify({ context_text: contextText, related_to: relatedTo, type: type || 'dilemme', question: question || '', options }),
    }),

  agentTTS: async (text: string): Promise<Blob | null> => {
    try {
      const res = await fetch(`${BASE}/agent/tts`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ text }),
      })
      if (res.ok) {
        const blob = await res.blob()
        if (blob.size > 0) return blob
      }
      return null
    } catch {
      return null
    }
  },

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

  // Google OAuth
  authGoogleUrl: (redirectUri?: string, state: string = 'login'): Promise<{ url: string }> => {
    const params = new URLSearchParams()
    if (redirectUri) params.set('redirect_uri', redirectUri)
    params.set('state', state)
    return request(`/auth/oauth/google/url?${params.toString()}`)
  },

  authOAuthGoogle: (code: string, redirectUri: string): Promise<{ access_token: string }> =>
    request('/auth/oauth/google', {
      method: 'POST',
      body: JSON.stringify({ code, redirect_uri: redirectUri }),
    }),

  // GitHub OAuth
  authGithubUrl: (redirectUri?: string): Promise<{ url: string }> => {
    const params = new URLSearchParams()
    if (redirectUri) params.set('redirect_uri', redirectUri)
    return request(`/auth/oauth/github/url?${params.toString()}`)
  },

  authOAuthGithub: (code: string, redirectUri: string): Promise<{ access_token: string }> =>
    request('/auth/oauth/github', {
      method: 'POST',
      body: JSON.stringify({ code, redirect_uri: redirectUri }),
    }),

  // Apple Sign-In
  authAppleUrl: (redirectUri?: string, state: string = 'login'): Promise<{ url: string; state: string }> => {
    const params = new URLSearchParams()
    if (redirectUri) params.set('redirect_uri', redirectUri)
    params.set('state', state)
    return request(`/auth/oauth/apple/url?${params.toString()}`)
  },

  authOAuthApple: (
    code: string,
    redirectUri: string,
    options?: { firstName?: string; lastName?: string; idToken?: string },
  ): Promise<{ access_token: string }> =>
    request('/auth/oauth/apple', {
      method: 'POST',
      body: JSON.stringify({
        code,
        redirect_uri: redirectUri,
        first_name: options?.firstName,
        last_name: options?.lastName,
        id_token: options?.idToken,
      }),
    }),

  // ── Agent assistant (Agent Sylea 2) ──────────────────────────────────

  agent2Chat: (messages: Array<{ role: string; content: string; type?: string }>, contexte_appareil?: DeviceContext, audioData?: string): Promise<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string; proposal?: AgentProposal | null }> =>
    request<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string; proposal?: AgentProposal | null }>('/agent2/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil, audio_data: audioData }),
    }),

  getAgent2Messages: (): Promise<Array<{ id: string; role: string; content: string; type: string; created_at: string; audioData?: string }>> =>
    request('/agent2/messages'),

  clearAgent2Messages: (): Promise<{ detail: string }> =>
    request('/agent2/messages', { method: 'DELETE' }),

  agent2SendEmail: (to: string, subject: string, body: string): Promise<{ ok: boolean; gmail_url?: string; error?: string }> =>
    request('/agent2/send-email', {
      method: 'POST',
      body: JSON.stringify({ to, subject, body }),
    }),

  agent2CreateReminder: (time: string, date: string, message: string): Promise<{ ok: boolean; error?: string }> =>
    request('/agent2/create-reminder', {
      method: 'POST',
      body: JSON.stringify({ time, date, message }),
    }),

  agent2GetReminders: (): Promise<Array<{ id: number; time: string; date: string; message: string; completed: boolean; created_at: string }>> =>
    request('/agent2/reminders'),

  agent2CompleteReminder: (id: number): Promise<{ ok: boolean }> =>
    request(`/agent2/reminders/${id}/complete`, { method: 'POST' }),

  agent2Proactive: (): Promise<{ message: string | null }> =>
    request('/agent2/proactive', { method: 'POST' }),

  agent2TTS: async (text: string): Promise<Blob | null> => {
    try {
      const res = await fetch(`${BASE}/agent2/tts`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ text }),
      })
      if (res.ok) {
        const blob = await res.blob()
        if (blob.size > 0) return blob
      }
      return null
    } catch {
      return null
    }
  },

  // ── Agent 3 (Agent Sylea 3 — OpenClaw) ──────────────────────────────────

  agent3Chat: (messages: Array<{ role: string; content: string; type?: string }>, contexte_appareil?: DeviceContext, audioData?: string): Promise<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string; openclaw_model?: string }> =>
    request<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string; openclaw_model?: string }>('/agent3/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil, audio_data: audioData }),
    }),

  /** Agent 3 Chat with SSE streaming — returns EventSource-like stream */
  agent3ChatStream: (
    messages: Array<{ role: string; content: string; type?: string }>,
    contexte_appareil?: DeviceContext,
    audioData?: string,
    callbacks?: {
      onSteps?: (steps: Array<{ id: string; label: string; status: string; detail: string }>) => void
      onStepUpdate?: (stepId: string, status: string) => void
      onLog?: (text: string, type: string) => void
      onToolProgress?: (tool: string, description: string, status: string, index: number) => void
      onToken?: (token: string) => void
      onResult?: (result: { message: string; actions?: any[]; tools_used?: any[]; openclaw_model?: string }) => void
      onError?: (message: string) => void
    }
  ): Promise<{ message: string; actions?: any[]; tools_used?: any[]; openclaw_model?: string }> => {
    return new Promise(async (resolve, reject) => {
      try {
        const resp = await fetch(`${BASE}/agent3/chat/stream`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ messages, contexte_appareil, audio_data: audioData }),
        })

        if (!resp.ok || !resp.body) {
          reject(new Error(`HTTP ${resp.status}`))
          return
        }

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6))
                switch (currentEvent) {
                  case 'steps':
                    callbacks?.onSteps?.(data.steps)
                    break
                  case 'step_update':
                    callbacks?.onStepUpdate?.(data.step_id, data.status)
                    break
                  case 'log':
                    callbacks?.onLog?.(data.text, data.type)
                    break
                  case 'tool_progress':
                    callbacks?.onToolProgress?.(data.tool, data.description, data.status, data.index ?? 0)
                    break
                  case 'token':
                    callbacks?.onToken?.(data.token)
                    break
                  case 'result':
                    callbacks?.onResult?.(data)
                    resolve(data)
                    break
                  case 'error':
                    callbacks?.onError?.(data.message)
                    reject(new Error(data.message))
                    break
                }
              } catch { /* skip malformed JSON */ }
              currentEvent = ''
            } else if (line === '') {
              currentEvent = ''
            }
          }
        }
      } catch (err) {
        reject(err)
      }
    })
  },

  /** Agent 3 Chat NATIVE — tool_use via Anthropic native tools API (pas de parser regex) */
  agent3ChatStreamNative: (
    messages: Array<{ role: string; content: string; type?: string }>,
    contexte_appareil?: DeviceContext,
    audioData?: string,
    callbacks?: {
      onTurnStart?: (turn: number) => void
      onThinking?: (text: string) => void
      onTokenDelta?: (text: string, turn: number) => void
      onThinkingDelta?: (text: string, turn: number) => void
      onThinkingBlock?: (payload: { text: string; length: number; turn: number }) => void
      onContextCompacted?: (payload: { chars_saved: number; turn: number }) => void
      onCancelled?: (payload: { turn: number; phase: string }) => void
      onToolUse?: (tool: { id: string; name: string; input: Record<string, unknown> }) => void
      onToolResult?: (result: { tool_use_id: string; content: string; is_error: boolean }) => void
      onTurnDone?: (turn: number) => void
      onResult?: (result: { message: string; turns: number; actions_count: number; tools_used?: any[] }) => void
      onError?: (message: string) => void
      onAwaitingConfirmation?: (payload: {
        resume_token: string
        pending_tool_uses: Array<{ tool_use_id: string; name: string; action_type: string; input: Record<string, unknown> }>
        turn: number
        preview_text?: string
      }) => void
      // Phase 4 : feedback live auto-extension ClawHub
      onAutoExtensionStart?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'search' | 'install' | 'publish'
        action_type: string
        trigger: string
      }) => void
      onAutoExtensionFound?: (payload: {
        turn: number
        tool_use_id: string
        query: string
        count: number
        candidates: Array<{ slug: string; name: string; description: string; author?: string; version?: string }>
      }) => void
      onAutoExtensionReady?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'install' | 'publish'
        slug: string
        tool_alias?: string
      }) => void
      onAutoExtensionError?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'search' | 'install' | 'publish'
        action_type: string
        message: string
      }) => void
      onToolsRefreshed?: (payload: {
        turn: number
        tool_use_id: string
        trigger: string
        slug: string
        added_slugs: string[]
        total_before: number
        total_after: number
        ok: boolean
      }) => void
      // Card visuelle apres chaque action destructive reussie (EMAIL/FILE_CREATE/...)
      onActionDone?: (payload: {
        turn: number
        tool_use_id: string
        action_type: string
        title: string
        subtitle?: string | null
        download_url?: string | null
        external_url?: string | null
        method?: string | null
      }) => void
      // Health check OpenClaw Gateway (envoye au debut de session si down)
      onOpenClawStatus?: (payload: {
        is_up: boolean
        message: string
      }) => void
    },
    options?: {
      stream?: boolean
      thinking?: boolean
      thinking_budget?: number
      cancel_token?: string
      signal?: AbortSignal
    }
  ): Promise<{ message: string; turns: number; actions_count: number; tools_used?: any[] }> => {
    return new Promise(async (resolve, reject) => {
      try {
        const resp = await fetch(`${BASE}/agent3/chat/native`, {
          method: 'POST',
          headers: getAuthHeaders(),
          signal: options?.signal,
          body: JSON.stringify({
            messages, contexte_appareil, audio_data: audioData,
            stream: options?.stream,
            thinking: options?.thinking,
            thinking_budget: options?.thinking_budget,
            cancel_token: options?.cancel_token,
          }),
        })

        if (!resp.ok || !resp.body) {
          reject(new Error(`HTTP ${resp.status}`))
          return
        }

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6))
                switch (currentEvent) {
                  case 'turn_start':
                    callbacks?.onTurnStart?.(data.turn)
                    break
                  case 'thinking':
                    callbacks?.onThinking?.(data.text)
                    break
                  case 'token_delta':
                    callbacks?.onTokenDelta?.(data.text || '', data.turn ?? 0)
                    break
                  case 'thinking_delta':
                    callbacks?.onThinkingDelta?.(data.text || '', data.turn ?? 0)
                    break
                  case 'thinking_block':
                    callbacks?.onThinkingBlock?.(data)
                    break
                  case 'context_compacted':
                    callbacks?.onContextCompacted?.(data)
                    break
                  case 'cancelled':
                    callbacks?.onCancelled?.(data)
                    break
                  case 'tool_use':
                    callbacks?.onToolUse?.(data)
                    break
                  case 'tool_result':
                    callbacks?.onToolResult?.(data)
                    break
                  case 'auto_extension_start':
                    callbacks?.onAutoExtensionStart?.(data)
                    break
                  case 'auto_extension_found':
                    callbacks?.onAutoExtensionFound?.(data)
                    break
                  case 'auto_extension_ready':
                    callbacks?.onAutoExtensionReady?.(data)
                    break
                  case 'auto_extension_error':
                    callbacks?.onAutoExtensionError?.(data)
                    break
                  case 'tools_refreshed':
                    callbacks?.onToolsRefreshed?.(data)
                    break
                  case 'action_done':
                    callbacks?.onActionDone?.(data)
                    break
                  case 'openclaw_status':
                    callbacks?.onOpenClawStatus?.(data)
                    break
                  case 'turn_llm_done':
                  case 'done':
                    callbacks?.onTurnDone?.(data.turn ?? 0)
                    break
                  case 'result':
                    callbacks?.onResult?.(data)
                    resolve(data)
                    break
                  case 'awaiting_confirmation':
                    callbacks?.onAwaitingConfirmation?.(data)
                    resolve({ message: data.preview_text || '', turns: data.turn ?? 0, actions_count: 0, tools_used: [] })
                    break
                  case 'error':
                    callbacks?.onError?.(data.message)
                    reject(new Error(data.message))
                    break
                }
              } catch { /* skip malformed JSON */ }
              currentEvent = ''
            } else if (line === '') {
              currentEvent = ''
            }
          }
        }
      } catch (err) {
        reject(err)
      }
    })
  },

  /** Agent 3 Native — annuler un stream en cours via son cancel_token. */
  agent3ChatCancelNative: async (cancelToken: string): Promise<{ cancelled: boolean; reason?: string }> => {
    try {
      const resp = await fetch(`${BASE}/agent3/chat/native/cancel`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ cancel_token: cancelToken }),
      })
      if (!resp.ok) return { cancelled: false, reason: `HTTP ${resp.status}` }
      return await resp.json()
    } catch (err) {
      return { cancelled: false, reason: (err as Error).message }
    }
  },

  /** Agent 3 Native — reprendre une boucle apres confirmation utilisateur d'une action destructive */
  agent3ChatResumeNative: (
    resumeToken: string,
    approvals: Record<string, boolean>,
    callbacks?: {
      onTurnStart?: (turn: number) => void
      onThinking?: (text: string) => void
      onToolUse?: (tool: { id: string; name: string; input: Record<string, unknown> }) => void
      onToolResult?: (result: { tool_use_id: string; content: string; is_error: boolean; user_approved?: boolean }) => void
      onResult?: (result: { message: string; turns: number; actions_count: number }) => void
      onAwaitingConfirmation?: (payload: {
        resume_token: string
        pending_tool_uses: Array<{ tool_use_id: string; name: string; action_type: string; input: Record<string, unknown> }>
        turn: number
        preview_text?: string
      }) => void
      onError?: (message: string) => void
      // Phase 4 : feedback live auto-extension ClawHub (chemin resume)
      onAutoExtensionStart?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'search' | 'install' | 'publish'
        action_type: string
        trigger: string
      }) => void
      onAutoExtensionFound?: (payload: {
        turn: number
        tool_use_id: string
        query: string
        count: number
        candidates: Array<{ slug: string; name: string; description: string; author?: string; version?: string }>
      }) => void
      onAutoExtensionReady?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'install' | 'publish'
        slug: string
        tool_alias?: string
      }) => void
      onAutoExtensionError?: (payload: {
        turn: number
        tool_use_id: string
        phase: 'search' | 'install' | 'publish'
        action_type: string
        message: string
      }) => void
      onToolsRefreshed?: (payload: {
        turn: number
        tool_use_id: string
        trigger: string
        slug: string
        added_slugs: string[]
        total_before: number
        total_after: number
        ok: boolean
      }) => void
      onActionDone?: (payload: {
        turn: number
        tool_use_id: string
        action_type: string
        title: string
        subtitle?: string | null
        download_url?: string | null
        external_url?: string | null
        method?: string | null
      }) => void
      onOpenClawStatus?: (payload: { is_up: boolean; message: string }) => void
    }
  ): Promise<{ message: string; turns: number; actions_count: number }> => {
    return new Promise(async (resolve, reject) => {
      try {
        const resp = await fetch(`${BASE}/agent3/chat/native/resume`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ resume_token: resumeToken, approvals }),
        })
        if (!resp.ok || !resp.body) {
          reject(new Error(`HTTP ${resp.status}`))
          return
        }
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6))
                switch (currentEvent) {
                  case 'turn_start': callbacks?.onTurnStart?.(data.turn); break
                  case 'thinking': callbacks?.onThinking?.(data.text); break
                  case 'tool_use': callbacks?.onToolUse?.(data); break
                  case 'tool_result': callbacks?.onToolResult?.(data); break
                  case 'auto_extension_start': callbacks?.onAutoExtensionStart?.(data); break
                  case 'auto_extension_found': callbacks?.onAutoExtensionFound?.(data); break
                  case 'auto_extension_ready': callbacks?.onAutoExtensionReady?.(data); break
                  case 'auto_extension_error': callbacks?.onAutoExtensionError?.(data); break
                  case 'tools_refreshed': callbacks?.onToolsRefreshed?.(data); break
                  case 'action_done': callbacks?.onActionDone?.(data); break
                  case 'openclaw_status': callbacks?.onOpenClawStatus?.(data); break
                  case 'result':
                    callbacks?.onResult?.(data)
                    resolve(data)
                    break
                  case 'awaiting_confirmation':
                    callbacks?.onAwaitingConfirmation?.(data)
                    resolve({ message: data.preview_text || '', turns: data.turn ?? 0, actions_count: 0 })
                    break
                  case 'error':
                    callbacks?.onError?.(data.message)
                    reject(new Error(data.message))
                    break
                }
              } catch { /* skip malformed JSON */ }
              currentEvent = ''
            } else if (line === '') {
              currentEvent = ''
            }
          }
        }
      } catch (err) {
        reject(err)
      }
    })
  },

  getAgent3Messages: (): Promise<Array<{ id: string; role: string; content: string; type: string; created_at: string; audioData?: string }>> =>
    request('/agent3/messages'),

  clearAgent3Messages: (): Promise<{ detail: string }> =>
    request('/agent3/messages', { method: 'DELETE' }),

  agent3Status: (): Promise<{ openclaw_connected: boolean; openclaw_error?: string }> =>
    request('/agent3/status'),

  agent3Proactive: (): Promise<{ message: string | null }> =>
    request('/agent3/proactive', { method: 'POST' }),

  agent3TTS: async (text: string): Promise<Blob | null> => {
    try {
      const res = await fetch(`${BASE}/agent3/tts`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ text }),
      })
      if (res.ok) {
        const blob = await res.blob()
        if (blob.size > 0) return blob
      }
      return null
    } catch {
      return null
    }
  },

  // ── Integrations ──────────────────────────────────────────────────────

  getIntegrations: (): Promise<any[]> =>
    request<any[]>('/integrations'),

  connectIntegration: (provider: string, data: any): Promise<any> =>
    request<any>(`/integrations/${provider}/connect`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Connecter Google (Calendar+Gmail+Drive) via OAuth — pour utilisateurs inscrits par email
  connectGoogleOAuth: (code: string, redirectUri: string): Promise<{ connected: boolean; services: string[] }> =>
    request('/integrations/google/oauth', {
      method: 'POST',
      body: JSON.stringify({ code, redirect_uri: redirectUri }),
    }),

  disconnectIntegration: (provider: string): Promise<void> =>
    request<void>(`/integrations/${provider}/disconnect`, { method: 'DELETE' }),

  getIntegrationStatus: (provider: string): Promise<any> =>
    request<any>(`/integrations/${provider}/status`),

  getCalendarEvents: (): Promise<any[]> =>
    request<any[]>('/integrations/google_calendar/events'),

  getGmailInbox: (): Promise<any[]> =>
    request<any[]>('/integrations/gmail/inbox'),

  getGithubActivity: (): Promise<any[]> =>
    request<any[]>('/integrations/github/activity'),

  getDriveFiles: (): Promise<any[]> =>
    request<any[]>('/integrations/google_drive/files'),

  // ── Network ─────────────────────────────────────────────────────────

  getNetworkProfile: (): Promise<any> =>
    request<any>('/network/profile'),

  updateNetworkProfile: (data: any): Promise<any> =>
    request<any>('/network/profile', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  discoverUsers: (): Promise<any[]> =>
    request<any[]>('/network/discover'),

  sendConnectionRequest: (userId: string): Promise<any> =>
    request<any>(`/network/connect/${userId}`, { method: 'POST' }),

  getConnections: (): Promise<any[]> =>
    request<any[]>('/network/connections'),

  getPendingConnections: (): Promise<any[]> =>
    request<any[]>('/network/connections/pending'),

  acceptConnection: (id: string): Promise<any> =>
    request<any>(`/network/connections/${id}/accept`, { method: 'PUT' }),

  rejectConnection: (id: string): Promise<any> =>
    request<any>(`/network/connections/${id}/reject`, { method: 'PUT' }),

  getMentors: (): Promise<any[]> =>
    request<any[]>('/network/mentors'),

  requestMentoring: (data: any): Promise<any> =>
    request<any>('/network/mentoring/request', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getChallenges: (): Promise<any[]> =>
    request<any[]>('/network/challenges'),

  joinChallenge: (id: string): Promise<any> =>
    request<any>(`/network/challenges/${id}/join`, { method: 'POST' }),

  getChallengeLeaderboard: (id: string): Promise<any[]> =>
    request<any[]>(`/network/challenges/${id}/leaderboard`),

  updateChallengeProgress: (id: string, progress: number): Promise<any> =>
    request<any>(`/network/challenges/${id}/progress`, {
      method: 'PUT',
      body: JSON.stringify({ progress }),
    }),

  getVictories: (): Promise<any[]> =>
    request<any[]>('/network/victories'),

  getVictoriesFeed: (): Promise<any[]> =>
    request<any[]>('/network/victories/feed'),

  postVictory: (data: any): Promise<any> =>
    request<any>('/network/victories', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  reactToVictory: (id: string): Promise<any> =>
    request<any>(`/network/victories/${id}/react`, {
      method: 'POST',
      body: JSON.stringify({ reaction_type: 'celebrate' }),
    }),

  // Desktop status
  checkDesktopStatus: (): Promise<{ connected: boolean }> =>
    request('/desktop/status'),

  // --- Computer Use ---
  computerUseStart: (
    prompt: string,
    callbacks?: {
      onScreenshot?: () => void
      onAction?: (action: string, params: Record<string, any>) => void
      onThinking?: (text: string) => void
      onConfirmationNeeded?: (data: { action: string; params: Record<string, any>; reason: string }) => void
      onUserActionNeeded?: (data: { instruction: string; action_type: string }) => void
      onUserActionResult?: (data: { result: string }) => void
      onStep?: (current: number) => void
      onComplete?: (text: string) => void
      onError?: (message: string) => void
      onCostUpdate?: (data: { estimated_usd: number; calls: number; input_tokens: number; output_tokens: number }) => void
      onCostWarning?: (data: { threshold_usd: number; current_usd: number; calls: number }) => void
      onCompaction?: (data: { old_count: number; new_count: number }) => void
    }
  ): Promise<void> => {
    return new Promise(async (resolve, reject) => {
      try {
        const response = await fetch(`${BASE}/agent3/computer-use/start`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify({ prompt }),
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (!response.body) throw new Error('No response body')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let currentEvent = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6))
                switch (currentEvent) {
                  case 'screenshot': callbacks?.onScreenshot?.(); break
                  case 'action': callbacks?.onAction?.(data.action, data.params); break
                  case 'thinking': callbacks?.onThinking?.(data.text); break
                  case 'confirmation_needed': callbacks?.onConfirmationNeeded?.(data); break
                  case 'user_action_needed': callbacks?.onUserActionNeeded?.(data); break
                  case 'user_action_result': callbacks?.onUserActionResult?.(data); break
                  case 'step': callbacks?.onStep?.(data.current); break
                  case 'complete': callbacks?.onComplete?.(data.text); resolve(); break
                  case 'error': callbacks?.onError?.(data.message); break
                  case 'cost_update': callbacks?.onCostUpdate?.(data); break
                  case 'cost_warning': callbacks?.onCostWarning?.(data); break
                  case 'compaction': callbacks?.onCompaction?.(data); break
                }
              } catch {}
              currentEvent = ''
            }
          }
        }
        resolve()
      } catch (err: any) {
        callbacks?.onError?.(err.message)
        reject(err)
      }
    })
  },

  computerUseScreenshot: (): Promise<{ screenshot: string }> =>
    request('/agent3/computer-use/screenshot'),

  computerUseConfirm: (approved: boolean): Promise<{ success: boolean }> =>
    request('/agent3/computer-use/confirm', {
      method: 'POST',
      body: JSON.stringify({ approved }),
    }),

  computerUseAbort: (): Promise<{ success: boolean }> =>
    request('/agent3/computer-use/abort', { method: 'POST' }),

  computerUseUserAction: (result: string): Promise<{ success: boolean }> =>
    request('/agent3/computer-use/user-action', {
      method: 'POST',
      body: JSON.stringify({ result }),
    }),

  // ── Browser Agent (Playwright) ───────────────────────────────────────────
  browserAgentStart: (
    task: string, url: string, code: string,
    callbacks?: {
      onScreenshot?: () => void
      onThinking?: (text: string) => void
      onAction?: (action: string, params: Record<string, any>) => void
      onUserActionNeeded?: (data: { instruction: string; action_type: string }) => void
      onUserActionResult?: (data: { result: string }) => void
      onStep?: (current: number) => void
      onComplete?: (text: string) => void
      onError?: (message: string) => void
      // ── Claude-Code-inspired events ──
      onPermissionNeeded?: (data: { prompt: string; action: string; params: Record<string, any>; risk: string }) => void
      onPermissionDenied?: (data: { action: string; reason: string; risk: string }) => void
      onPermissionResult?: (data: { decision: string }) => void
      onPlanModeActive?: (data: { reason: string; action: string }) => void
      onPlanAttached?: (plan: any) => void
      onCostUpdate?: (data: { usd: number; input_tokens: number; output_tokens: number; calls: number }) => void
      onCostWarning?: (data: { threshold_usd: number; current_usd: number; calls: number }) => void
      onCostExhausted?: (data: { message: string }) => void
    },
    options?: { planId?: string; permissionMode?: 'default' | 'plan' | 'auto_safe' | 'bypass' }
  ): Promise<void> => {
    return new Promise(async (resolve, reject) => {
      try {
        const body: any = { task, url, code }
        if (options?.planId) body.plan_id = options.planId
        if (options?.permissionMode) body.permission_mode = options.permissionMode
        const response = await fetch(`${BASE}/agent3/browser-agent/start`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: JSON.stringify(body),
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (!response.body) throw new Error('No response body')
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let currentEvent = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6))
                switch (currentEvent) {
                  case 'screenshot': callbacks?.onScreenshot?.(); break
                  case 'thinking': callbacks?.onThinking?.(data.text); break
                  case 'action': callbacks?.onAction?.(data.action, data.params); break
                  case 'user_action_needed': callbacks?.onUserActionNeeded?.(data); break
                  case 'user_action_result': callbacks?.onUserActionResult?.(data); break
                  case 'step': callbacks?.onStep?.(data.current); break
                  case 'complete': callbacks?.onComplete?.(data.text); resolve(); break
                  case 'error': callbacks?.onError?.(data.message); break
                  case 'permission_needed': callbacks?.onPermissionNeeded?.(data); break
                  case 'permission_denied': callbacks?.onPermissionDenied?.(data); break
                  case 'permission_result': callbacks?.onPermissionResult?.(data); break
                  case 'plan_mode_active': callbacks?.onPlanModeActive?.(data); break
                  case 'plan_attached': callbacks?.onPlanAttached?.(data); break
                  case 'cost_update': callbacks?.onCostUpdate?.(data); break
                  case 'cost_warning': callbacks?.onCostWarning?.(data); break
                  case 'cost_exhausted': callbacks?.onCostExhausted?.(data); break
                }
              } catch {}
              currentEvent = ''
            }
          }
        }
        resolve()
      } catch (err: any) {
        callbacks?.onError?.(err.message)
        reject(err)
      }
    })
  },

  browserAgentScreenshot: (): Promise<{ screenshot: string }> =>
    request('/agent3/browser-agent/screenshot'),

  browserAgentUserAction: (result: string): Promise<{ success: boolean }> =>
    request('/agent3/browser-agent/user-action', {
      method: 'POST',
      body: JSON.stringify({ result }),
    }),

  browserAgentAbort: (): Promise<{ success: boolean }> =>
    request('/agent3/browser-agent/abort', { method: 'POST' }),

  // ── Plan Mode / Permissions / Cost (Claude-Code-inspired) ────────────────
  browserAgentGeneratePlan: (task: string, url: string, code: string): Promise<any> =>
    request('/agent3/browser-agent/plan', {
      method: 'POST',
      body: JSON.stringify({ task, url, code }),
    }),

  browserAgentApprovePlan: (planId: string): Promise<any> =>
    request(`/agent3/browser-agent/plan/${planId}/approve`, { method: 'POST' }),

  browserAgentEditPlanStep: (planId: string, stepId: number, changes: { description?: string; risk?: string }): Promise<any> =>
    request(`/agent3/browser-agent/plan/${planId}/edit-step`, {
      method: 'POST',
      body: JSON.stringify({ step_id: stepId, ...changes }),
    }),

  browserAgentAbortPlan: (planId: string): Promise<any> =>
    request(`/agent3/browser-agent/plan/${planId}/abort`, { method: 'POST' }),

  browserAgentGetPlan: (planId: string): Promise<any> =>
    request(`/agent3/browser-agent/plan/${planId}`),

  browserAgentPermissionRespond: (allow: boolean): Promise<{ success: boolean; decision: string }> =>
    request('/agent3/browser-agent/permission/respond', {
      method: 'POST',
      body: JSON.stringify({ allow }),
    }),

  browserAgentGetPolicy: (): Promise<any> =>
    request('/agent3/browser-agent/permission/policy'),

  browserAgentSetPolicy: (policy: {
    mode?: 'default' | 'bypass'
    always_ask_domains?: string[]
    trusted_domains?: string[]
    blocked_domains?: string[]
    destructive_quota?: number
  }): Promise<any> =>
    request('/agent3/browser-agent/permission/policy', {
      method: 'POST',
      body: JSON.stringify(policy),
    }),

  browserAgentCost: (): Promise<{
    input_tokens: number; output_tokens: number; cache_read_tokens: number;
    calls: number; errors: number; estimated_usd: number;
    model_breakdown: Record<string, any>; session_duration_seconds: number;
  }> => request('/agent3/browser-agent/cost'),

  browserAgentCostReset: (): Promise<{ success: boolean }> =>
    request('/agent3/browser-agent/cost/reset', { method: 'POST' }),

  // ── Workspace ──────────────────────────────────────────────────────────────
  getProjects: () => request<any[]>('/workspace/projects'),
  createProject: (data: any) => request<any>('/workspace/projects', { method: 'POST', body: JSON.stringify(data) }),
  deleteProject: (id: string) => request<void>(`/workspace/projects/${id}`, { method: 'DELETE' }),
  getDocuments: () => request<any[]>('/workspace/documents'),
  deleteDocument: (id: string) => request<void>(`/workspace/documents/${id}`, { method: 'DELETE' }),
  getTemplates: () => request<any[]>('/workspace/templates'),
  getKnowledge: () => request<any[]>('/workspace/knowledge'),
  addKnowledge: (data: any) => request<any>('/workspace/knowledge', { method: 'POST', body: JSON.stringify(data) }),
  searchKnowledge: (q: string) => request<any[]>(`/workspace/knowledge/search?q=${encodeURIComponent(q)}`),
  deleteKnowledge: (id: string) => request<void>(`/workspace/knowledge/${id}`, { method: 'DELETE' }),

  // ── Coaching ───────────────────────────────────────────────────────────────
  getCoachingPreferences: () => request<any>('/coaching/preferences'),
  updateCoachingPreferences: (data: any) => request<any>('/coaching/preferences', { method: 'PUT', body: JSON.stringify(data) }),
  getCoachingSessions: () => request<any[]>('/coaching/sessions'),
  getPendingSession: () => request<any>('/coaching/sessions/pending'),
  startCoachingSession: (type: string) => request<any>('/coaching/sessions/start', { method: 'POST', body: JSON.stringify({ session_type: type }) }),

  // ── Agent 3 Management endpoints ──────────────────────────────────────

  // CRON management
  agent3GetCrons: (): Promise<Array<{ id: string; label: string; instruction: string; cron_expr: string; enabled: boolean; last_run?: string; last_result?: string; created_at: string }>> =>
    request('/agent3/cron'),

  agent3CreateCron: (data: { label: string; instruction: string; cron_expr?: string; enabled?: boolean }): Promise<{ cron_id: string }> =>
    request('/agent3/cron', { method: 'POST', body: JSON.stringify(data) }),

  agent3DeleteCron: (cronId: string): Promise<{ success: boolean }> =>
    request(`/agent3/cron/${cronId}`, { method: 'DELETE' }),

  agent3ToggleCron: (cronId: string): Promise<{ success: boolean; enabled: boolean }> =>
    request(`/agent3/cron/${cronId}/toggle`, { method: 'PUT' }),

  agent3RunCron: (cronId: string): Promise<{ success: boolean; result: string }> =>
    request(`/agent3/cron/${cronId}/run`, { method: 'POST' }),

  // Memory management
  agent3GetMemories: (): Promise<Array<{ key: string; value: string; category?: string; created_at: string }>> =>
    request('/agent3/memory'),

  agent3DeleteMemory: (key: string): Promise<{ success: boolean }> =>
    request(`/agent3/memory/${encodeURIComponent(key)}`, { method: 'DELETE' }),

  // File management
  agent3GetFiles: (): Promise<Array<{ id: string; filename: string; filetype: string; filesize: number; created_at: string }>> =>
    request('/agent3/files'),

  // Tool diagnostics
  agent3TestTools: (): Promise<Record<string, any>> =>
    request('/agent3/tools/test'),

  // Capabilities
  agent3Capabilities: (): Promise<Record<string, any>> =>
    request('/agent3/capabilities'),

  // Preferences (confirmation actions destructives, etc.)
  agent3GetPreferences: (): Promise<{ confirm_destructive: boolean }> =>
    request('/agent3/preferences'),

  agent3UpdatePreferences: (prefs: { confirm_destructive?: boolean }): Promise<{ ok: boolean }> =>
    request('/agent3/preferences', { method: 'PUT', body: JSON.stringify(prefs) }),

  // Tasks (tâches multi-étapes persistantes)
  agent3GetTasks: (): Promise<Array<{ id: string; title: string; description: string; steps: Array<{ label: string; status: string; result?: string }>; status: string; progress: number; created_at: string; updated_at: string }>> =>
    request('/agent3/tasks'),

  agent3DeleteTask: (taskId: string): Promise<{ success: boolean }> =>
    request(`/agent3/tasks/${taskId}`, { method: 'DELETE' }),

  // ── Agent 3 / Phase 3 — Outils OpenClaw ────────────────────────────────
  // Gestion fine des 38 outils : activer/desactiver par utilisateur en plus
  // du profil agent (TOOL_PROFILES whitelist/blacklist).

  /** Retourne les 38 outils OpenClaw avec leur statut (profil + override user). */
  agent3GetTools: (): Promise<{
    agent_id: string
    total_tools: number
    enabled_count: number
    has_user_overrides: boolean
    tools: Array<{
      name: string
      description: string
      group: string
      enabled_profile: boolean
      enabled_user: boolean | null
      effectively_enabled: boolean
    }>
    groups: Record<string, Array<{
      name: string
      description: string
      group: string
      enabled_profile: boolean
      enabled_user: boolean | null
      effectively_enabled: boolean
    }>>
  }> =>
    request('/agent3/tools'),

  /** Toggle on/off d'un outil pour l'utilisateur courant (override). */
  agent3ToggleTool: (toolName: string, enabled: boolean): Promise<{
    success: boolean
    tool: string
    enabled_user: boolean
    enabled_profile: boolean
    effectively_enabled: boolean
  }> =>
    request(`/agent3/tools/${encodeURIComponent(toolName)}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  /** Supprime l'override utilisateur sur un outil (retour au reglage du profil). */
  agent3ClearToolOverride: (toolName: string): Promise<{
    success: boolean
    tool: string
    override_cleared: boolean
  }> =>
    request(`/agent3/tools/${encodeURIComponent(toolName)}/override`, { method: 'DELETE' }),

  /** Toggle en masse : {"tool_name": enabled, ...}. */
  agent3BulkToggleTools: (preferences: Record<string, boolean>): Promise<{
    success: boolean
    updated_count: number
    updated: string[]
    skipped: string[]
  }> =>
    request('/agent3/tools/bulk-toggle', {
      method: 'POST',
      body: JSON.stringify({ preferences }),
    }),

  // ── Agent 3 / Phase 4 — ClawHub skills ─────────────────────────────────
  // Agent auto-extensible : skills bundled OpenClaw + skills installees
  // depuis le registre ClawHub.com (search/install/publish).

  /** Liste toutes les skills (bundled + user) via le loader Phase 4. */
  agent3ClawhubListSkills: (opts?: {
    include_bundled?: boolean
    include_user?: boolean
    force_refresh?: boolean
  }): Promise<{
    success: boolean
    count: number
    bundled_count: number
    user_count: number
    enabled_mode: 'all' | 'filter'
    enabled_slugs: string[] | null
    skills: Array<{
      slug: string
      name: string
      description: string
      path: string
      is_bundled: boolean
      version: string
      author: string
      homepage: string
      emoji: string
      tags: string[]
      required_bins: string[]
      body_preview: string
      tool_name: string
      enabled: boolean
    }>
    error?: string
  }> => {
    const params = new URLSearchParams()
    if (opts?.include_bundled !== undefined) params.set('include_bundled', String(opts.include_bundled))
    if (opts?.include_user !== undefined) params.set('include_user', String(opts.include_user))
    if (opts?.force_refresh !== undefined) params.set('force_refresh', String(opts.force_refresh))
    const qs = params.toString()
    return request(`/agent3/clawhub/skills${qs ? '?' + qs : ''}`)
  },

  /** Detail complet d'une skill (metas + SKILL.md). */
  agent3ClawhubGetSkill: (slug: string): Promise<{
    success: boolean
    skill?: {
      slug: string
      name: string
      description: string
      path: string
      is_bundled: boolean
      emoji: string
      tags: string[]
      required_bins: string[]
      tool_name: string
    }
    skill_md?: string
    error?: string
  }> =>
    request(`/agent3/clawhub/skills/${encodeURIComponent(slug)}`),

  /** Force le rescan du disque (invalide le cache). Utile apres qu'un skill
   * ait ete installe/modifie en dehors de l'agent. */
  agent3ClawhubRefresh: (): Promise<{
    success: boolean
    count: number
    bundled_count: number
    user_count: number
    error?: string
  }> =>
    request('/agent3/clawhub/skills/refresh', { method: 'POST' }),

  /** Historique des actions destructives de l'Agent 3 (EMAIL/FILE_CREATE/...). */
  agent3GetAudit: (limit: number = 100): Promise<{
    success: boolean
    count: number
    success_count: number
    counts_by_type: Record<string, number>
    entries: Array<{
      id: string
      action_type: string
      summary: string
      success: boolean
      error_message: string
      created_at: string
    }>
  }> =>
    request(`/agent3/audit?limit=${limit}`),

  /** Liste les fichiers crees dans le workspace (authentifie). */
  agent3ListWorkspaceFiles: (): Promise<{
    files: Array<{
      filename: string
      size: number
      modified_at: string
      download_url: string
    }>
    workspace: string | null
  }> =>
    request('/agent3/workspace-files'),

  /** Liste les 38 outils OpenClaw directs + leur statut exposition LLM. */
  agent3ListOpenClawTools: (): Promise<{
    success: boolean
    tools: Array<{
      name: string
      group: string
      description: string
      exposed_to_llm: boolean
      is_destructive: boolean
    }>
    direct_tools_enabled: boolean
    enabled_filter: 'all' | 'subset'
    counts: { total: number; exposed: number; destructive: number }
  }> =>
    request('/agent3/openclaw-tools'),

  /** Breakdown des couts externes OpenClaw (USD) pour l'utilisateur courant. */
  agent3GetExternalCost: (): Promise<{
    total_usd: number
    by_tool: Record<string, { usd: number; calls: number }>
  }> =>
    request('/agent3/cost-external'),

  /** Metrics Agent 3 : retries, circuit breakers, gateway health, couts externes. */
  agent3GetMetrics: (): Promise<{
    retries: Record<string, number>
    breakers: Record<string, {
      name: string
      state: 'closed' | 'open' | 'half_open'
      failures: number
      threshold: number
    }>
    gateway_health: {
      is_up: boolean | null
      checked_at: number
      ttl_s: number
      last_error: string
    }
    external_cost_global: {
      total_by_user: Record<string, number>
      total_calls: number
    }
    external_cost_mine: {
      total_usd: number
      by_tool: Record<string, { usd: number; calls: number }>
    }
    latencies?: Record<string, {
      count: number
      p50_ms: number
      p95_ms: number
      p99_ms: number
      min_ms: number
      max_ms: number
      avg_ms: number
    }>
    daily_cost?: {
      used_usd: number
      cap_usd: number
      pct: number
    }
  }> =>
    request('/agent3/metrics'),

  /** Met a jour la liste des outils OpenClaw exposes au LLM (filtrage granulaire). */
  agent3SetOpenClawEnabledTools: (
    enabledNames: string[] | null,
    directToolsEnabled?: boolean,
  ): Promise<{ success: boolean; preferences: Record<string, unknown> }> =>
    request('/agent3/preferences', {
      method: 'PUT',
      body: JSON.stringify({
        openclaw_enabled_tools: enabledNames,  // null = tous (filter 'all')
        ...(directToolsEnabled !== undefined ? { openclaw_direct_tools_enabled: directToolsEnabled } : {}),
      }),
    }),

  // ────────────────────────────────────────────────────────────────────────
  // Credential Vault (api/credentials/*)  — gestion cles API tierces
  // ────────────────────────────────────────────────────────────────────────

  /** Catalogue public des providers supportes. */
  credentialsListProviders: (): Promise<{
    providers: Array<{
      slug: string
      display_name: string
      description: string
      category: string
      logo_emoji: string
      aliases: string[]
      fields: Array<{
        key: string
        label: string
        type: string
        required: boolean
        pattern?: string
        pattern_hint?: string
      }>
      tutorial_url: string
      tutorial_steps: string[]
      used_by_skills: string[]
    }>
  }> => {
    // Appel absolu car le prefix du router est /api/credentials (pas /api/agent3/).
    return fetch(`${API_BASE}/api/credentials/providers`, {
      headers: getAuthHeaders(),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Liste des credentials du user (masquees). */
  credentialsListMine: (): Promise<{
    credentials: Array<{
      provider_slug: string
      field_key: string
      preview: string
      metadata: Record<string, unknown> | null
      created_at: string
      updated_at: string
      last_used_at: string | null
      last_tested_at: string | null
      last_test_ok: boolean | null
      expires_at: string | null
    }>
    count: number
  }> => {
    return fetch(`${API_BASE}/api/credentials`, {
      headers: getAuthHeaders(),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Detecte un provider a partir d'un input (nom ou cle API collee). */
  credentialsDetect: (input: string): Promise<{
    type: 'api_key_detected' | 'provider_suggestions' | 'no_match' | 'empty'
    matches: Array<{
      provider_slug: string
      field_key: string
      provider_display_name: string
      provider_logo_emoji: string
      metadata: Record<string, string>
    }>
    suggestions: Array<{
      slug: string
      display_name: string
      description: string
      category: string
      logo_emoji: string
      score: number
    }>
  }> => {
    return fetch(`${API_BASE}/api/credentials/detect`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ input }),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Save + test en un seul appel. Detection auto si provider_slug omis. */
  credentialsQuickSave: (
    input: string,
    providerSlug?: string,
    fieldKey?: string,
  ): Promise<{
    success: boolean
    validated?: boolean
    ambiguous?: boolean
    provider_slug?: string
    field_key?: string
    preview?: string
    test_message?: string
    skills_activated?: string[]
    metadata?: Record<string, unknown>
    matches?: Array<{ provider_slug: string; field_key: string }>
    message?: string
  }> => {
    return fetch(`${API_BASE}/api/credentials/quick-save`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        input,
        provider_slug: providerSlug,
        field_key: fieldKey,
      }),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Save manuel multi-champs (form complet). */
  credentialsSave: (
    providerSlug: string,
    values: Record<string, string>,
    metadata?: Record<string, unknown>,
  ): Promise<{
    success: boolean
    validated: boolean
    test_message: string
    saved_fields: string[]
    skills_activated: string[]
  }> => {
    return fetch(`${API_BASE}/api/credentials`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        provider_slug: providerSlug,
        values,
        metadata,
      }),
    }).then(async r => {
      if (!r.ok) {
        const body = await r.json().catch(() => ({ detail: 'Erreur' }))
        throw new Error(body.detail || `HTTP ${r.status}`)
      }
      return r.json()
    })
  },

  /** Supprime toutes les credentials d'un provider. */
  credentialsDeleteProvider: (providerSlug: string): Promise<{
    success: boolean
    deleted_count: number
  }> => {
    return fetch(`${API_BASE}/api/credentials/${encodeURIComponent(providerSlug)}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Re-test les credentials existantes d'un provider. */
  credentialsTest: (providerSlug: string): Promise<{
    success: boolean
    message: string
  }> => {
    return fetch(`${API_BASE}/api/credentials/${encodeURIComponent(providerSlug)}/test`, {
      method: 'POST',
      headers: getAuthHeaders(),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Liste des credentials requises par les skills ClawHub installes, avec status. */
  credentialsMissingForSkills: (): Promise<{
    skills: Array<{
      slug: string
      name: string
      emoji: string
      required_env: string[]
      missing: Array<{
        env_name: string
        matched_provider: string | null
        field_key: string | null
        has_credential: boolean
        custom_provider_slug?: string
      }>
    }>
    total_missing_count: number
  }> => {
    return fetch(`${API_BASE}/api/credentials/missing-for-skills`, {
      headers: getAuthHeaders(),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
  },

  /** Save une credential custom pour un skill ClawHub (env var arbitraire). */
  credentialsSaveCustomSkillEnv: (
    skillSlug: string,
    envName: string,
    value: string,
  ): Promise<{
    success: boolean
    provider_slug: string
    field_key: string
    preview: string
  }> => {
    return fetch(`${API_BASE}/api/credentials/custom-skill-env`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ skill_slug: skillSlug, env_name: envName, value }),
    }).then(async r => {
      if (!r.ok) {
        const body = await r.json().catch(() => ({ detail: 'Erreur' }))
        throw new Error(body.detail || `HTTP ${r.status}`)
      }
      return r.json()
    })
  },

  /** Recupere le SKILL.md complet d'un skill installe (pour affichage UI). */
  agent3ClawhubGetSkillMarkdown: (slug: string): Promise<{
    success: boolean
    slug: string
    name: string
    description: string
    version: string
    author: string
    homepage: string
    emoji: string
    is_bundled: boolean
    required_bins: string[]
    markdown: string
  }> =>
    request(`/agent3/clawhub/skill/${encodeURIComponent(slug)}/md`),

  /** Historique des auto-extensions (search/install/publish) faites par l'agent. */
  agent3ClawhubGetEvents: (limit: number = 50): Promise<{
    success: boolean
    count: number
    counts_by_type: { auto_search: number; auto_install: number; auto_publish: number; auto_unknown?: number }
    events: Array<{
      id: number
      event_type: 'auto_search' | 'auto_install' | 'auto_publish' | 'auto_unknown'
      slug: string
      trigger_context: string
      success: boolean
      error_message: string
      created_at: string
    }>
    error?: string
  }> =>
    request(`/agent3/clawhub/events?limit=${limit}`),

  /** Retourne les preferences ClawHub (permission_mode + toggles). */
  agent3ClawhubGetSettings: (): Promise<{
    success: boolean
    permission_mode: 'default' | 'bypass'
    clawhub_skills_enabled: boolean
    clawhub_meta_enabled: boolean
    clawhub_enabled_slugs: string[] | null
    enabled_mode: 'all' | 'filter'
  }> =>
    request('/agent3/clawhub/settings'),

  /** Met a jour les preferences ClawHub. */
  agent3ClawhubUpdateSettings: (data: {
    permission_mode?: 'default' | 'bypass'
    clawhub_skills_enabled?: boolean
    clawhub_meta_enabled?: boolean
    clawhub_enabled_slugs?: string[] | null
  }): Promise<{
    success: boolean
    permission_mode: 'default' | 'bypass'
    clawhub_skills_enabled: boolean
    clawhub_meta_enabled: boolean
    clawhub_enabled_slugs: string[] | null
  }> =>
    request('/agent3/clawhub/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 10A — Plans & Quotas
  // ─────────────────────────────────────────────────────────────────────────

  getPlan: (): Promise<{
    plan: {
      name: 'free' | 'pro' | 'team'
      display_name: string
      price_usd: number
      limits: Record<string, number>
      started_at?: string
      expires_at?: string
    }
    usage: {
      month_key: string
      tokens: number
      requests: number
      skills_installed: number
      crons: number
      uploads: number
      deep_researches: number
      updated_at?: string
    }
  }> => request('/agent3/plan'),

  getQuotasUsage: (month?: string): Promise<{
    month_key: string
    tokens: number
    requests: number
    skills_installed: number
    crons: number
    uploads: number
    deep_researches: number
  }> => request(`/agent3/quotas/usage${month ? `?month=${encodeURIComponent(month)}` : ''}`),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 10B — Workspaces multi-tenant
  // ─────────────────────────────────────────────────────────────────────────

  listWorkspaces: (): Promise<{ items: Array<{
    id: string
    name: string
    owner_id: string
    created_at: string
    my_role: 'owner' | 'admin' | 'member'
  }> }> => request('/agent3/workspaces'),

  createWorkspace: (name: string): Promise<{
    ok: boolean
    workspace_id?: string
    name?: string
    error?: string
  }> => request('/agent3/workspaces', {
    method: 'POST',
    body: JSON.stringify({ name }),
  }),

  deleteWorkspace: (id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/workspaces/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  listWorkspaceMembers: (id: string): Promise<{ members: Array<{
    user_id: string
    role: 'owner' | 'admin' | 'member'
    joined_at: string
  }> }> => request(`/agent3/workspaces/${encodeURIComponent(id)}/members`),

  addWorkspaceMember: (id: string, user_id: string, role: 'owner' | 'admin' | 'member'): Promise<{ ok: boolean; error?: string }> =>
    request(`/agent3/workspaces/${encodeURIComponent(id)}/members`, {
      method: 'POST',
      body: JSON.stringify({ user_id, role }),
    }),

  removeWorkspaceMember: (id: string, target_user_id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/workspaces/${encodeURIComponent(id)}/members/${encodeURIComponent(target_user_id)}`, {
      method: 'DELETE',
    }),

  listWorkspaceSharedMemory: (id: string): Promise<{ items: Array<{
    id: string
    key: string
    value: string
    category: string
    created_by: string
    created_at: string
  }> }> => request(`/agent3/workspaces/${encodeURIComponent(id)}/shared-memory`),

  shareWorkspaceMemory: (id: string, key: string, value: string, category = 'general'): Promise<{ ok: boolean; memory_id?: string }> =>
    request(`/agent3/workspaces/${encodeURIComponent(id)}/shared-memory`, {
      method: 'POST',
      body: JSON.stringify({ key, value, category }),
    }),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 10C — Admin dashboard
  // ─────────────────────────────────────────────────────────────────────────

  adminListUsers: (limit = 100): Promise<{ items: Array<{
    id: string
    email: string
    provider: string
    created_at: string
    is_admin: boolean
    disabled: boolean
    plan: string
    usage_this_month: { tokens: number; requests: number }
    messages_total: number
  }> }> => request(`/agent3/admin/users?limit=${limit}`),

  adminGetStats: (): Promise<{
    users_total: number
    users_active: number
    admins: number
    messages_total: number
    plans_distribution: Record<string, number>
    tokens_this_month: number
    requests_this_month: number
    month_key: string
  }> => request('/agent3/admin/stats'),

  adminRecentActivity: (limit = 50): Promise<{ items: Array<{
    id: string
    user_id: string
    action_type: string
    summary: string
    success: boolean
    created_at: string
  }> }> => request(`/agent3/admin/activity?limit=${limit}`),

  adminSetPlan: (user_id: string, plan_name: string): Promise<{ ok: boolean }> =>
    request(`/agent3/admin/users/${encodeURIComponent(user_id)}/plan`, {
      method: 'POST',
      body: JSON.stringify({ plan_name }),
    }),

  adminDisableUser: (user_id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/admin/users/${encodeURIComponent(user_id)}/disable`, {
      method: 'POST',
    }),

  adminEnableUser: (user_id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/admin/users/${encodeURIComponent(user_id)}/enable`, {
      method: 'POST',
    }),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 10D — API keys + Webhooks
  // ─────────────────────────────────────────────────────────────────────────

  listApiKeys: (): Promise<{ items: Array<{
    id: string
    name: string
    prefix: string
    scopes: string[]
    last_used_at?: string
    created_at: string
    revoked: boolean
  }> }> => request('/agent3/api-keys'),

  createApiKey: (name: string, scopes?: string[]): Promise<{
    ok: boolean
    key_id?: string
    token?: string
    prefix?: string
    scopes?: string[]
    warning?: string
    error?: string
  }> => request('/agent3/api-keys', {
    method: 'POST',
    body: JSON.stringify({ name, scopes }),
  }),

  revokeApiKey: (id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/api-keys/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  listWebhooks: (): Promise<{ items: Array<{
    id: string
    target_url: string
    events: string[]
    enabled: boolean
    last_success_at?: string
    last_error?: string
    failures_count: number
    created_at: string
  }> }> => request('/agent3/webhooks'),

  createWebhook: (target_url: string, events: string[]): Promise<{
    ok: boolean
    subscription_id?: string
    secret?: string
    events?: string[]
    target_url?: string
    error?: string
  }> => request('/agent3/webhooks', {
    method: 'POST',
    body: JSON.stringify({ target_url, events }),
  }),

  deleteWebhook: (id: string): Promise<{ ok: boolean }> =>
    request(`/agent3/webhooks/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  webhookDeliveries: (limit = 50): Promise<{ items: Array<{
    id: string
    subscription_id: string
    event: string
    status_code?: number
    attempted_at: string
    delivered_at?: string
    error?: string
  }> }> => request(`/agent3/webhooks/deliveries?limit=${limit}`),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 11C — Voice (wrappers pour le STT/TTS backend)
  // ─────────────────────────────────────────────────────────────────────────

  voiceTranscribe: (audio: Blob, language = 'fr'): Promise<{
    text: string
    cost_usd?: number
    estimated_minutes?: number
    error?: string
  }> => {
    const fd = new FormData()
    fd.append('file', audio, 'audio.mp3')
    return fetch(`${BASE}/agent3/voice/transcribe?language=${encodeURIComponent(language)}`, {
      method: 'POST',
      headers: (() => {
        const h: Record<string, string> = {}
        const t = localStorage.getItem(AUTH_TOKEN_KEY)
        if (t) h['Authorization'] = `Bearer ${t}`
        return h
      })(),
      body: fd,
    }).then(r => r.json())
  },

  voiceTts: (text: string, voice = 'nova', speed = 1.0): Promise<{
    audio_b64?: string
    format?: string
    chars?: number
    voice?: string
    cost_usd?: number
    error?: string
  }> => request('/agent3/voice/tts', {
    method: 'POST',
    body: JSON.stringify({ text, voice, speed }),
  }),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 9C — Feedback explicite (thumbs up/down)
  // ─────────────────────────────────────────────────────────────────────────

  recordFeedback: (data: {
    vote: 'up' | 'down'
    message_id?: string
    comment?: string
    agent_response?: string
  }): Promise<{ ok: boolean; feedback_id?: string; error?: string }> =>
    request('/agent3/feedback', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getFeedbackStats: (): Promise<{
    thumbs_up: number
    thumbs_down: number
    total: number
    ratio: number
  }> => request('/agent3/feedback/stats'),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 9A — GDPR
  // ─────────────────────────────────────────────────────────────────────────

  exportMyData: async (): Promise<Blob> => {
    const res = await fetch(`${BASE}/agent3/export-my-data`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) throw new Error('Export failed')
    return res.blob()
  },

  deleteMyData: (): Promise<{
    deleted_by_table?: Record<string, number>
    files_deleted?: number
    total_rows?: number
    deleted_at?: string
    error?: string
  }> => request('/agent3/delete-my-data?confirm=YES-DELETE-EVERYTHING', {
    method: 'DELETE',
  }),

  // ─────────────────────────────────────────────────────────────────────────
  // Phase 13 — Stripe checkout / portal
  // ─────────────────────────────────────────────────────────────────────────

  stripeConfig: (): Promise<{ configured: boolean }> =>
    request('/agent3/stripe/config'),

  stripeCheckout: (plan: 'pro' | 'team'): Promise<{
    ok: boolean
    url?: string
    session_id?: string
    error?: string
  }> => request('/agent3/stripe/checkout', {
    method: 'POST',
    body: JSON.stringify({ plan }),
  }),

  stripePortal: (): Promise<{
    ok: boolean
    url?: string
    error?: string
  }> => request('/agent3/stripe/portal', {
    method: 'POST',
  }),
}

// ─────────────────────────────────────────────────────────────────────────────
// Types exported (Phase 10/11)
// ─────────────────────────────────────────────────────────────────────────────

