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

export const API_BASE = import.meta.env.VITE_API_URL || ''
const BASE = `${API_BASE}/api`
const AUTH_TOKEN_KEY = 'sylea_auth_token'

export function getAuthHeaders(): Record<string, string> {
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

  agentChat: (messages: Array<{ role: string; content: string; type?: string }>, contexte_appareil?: DeviceContext, audioData?: string): Promise<{ message: string; choices?: string[]; audioData?: string }> =>
    request<{ message: string; choices?: string[]; audioData?: string }>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, contexte_appareil, audio_data: audioData }),
    }),

  getAgentMessages: (): Promise<Array<{ id: string; role: string; content: string; type: string; created_at: string; audioData?: string }>> =>
    request('/agent/messages'),

  clearAgentMessages: (): Promise<{ detail: string }> =>
    request('/agent/messages', { method: 'DELETE' }),

  agentProactive: (): Promise<{ message: string | null }> =>
    request('/agent/proactive', { method: 'POST' }),

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

  // ── Agent assistant (Agent Sylea 2) ──────────────────────────────────

  agent2Chat: (messages: Array<{ role: string; content: string; type?: string }>, contexte_appareil?: DeviceContext, audioData?: string): Promise<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string }> =>
    request<{ message: string; choices?: string[]; actions?: Array<{ type: string; data: Record<string, string> }>; audioData?: string }>('/agent2/chat', {
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

  // ── Scenarios ──────────────────────────────────────────────────────────────
  getScenarios: () => request<any[]>('/scenarios'),
  createScenario: (data: any) => request<any>('/scenarios/create', { method: 'POST', body: JSON.stringify(data) }),
  deleteScenario: (id: string) => request<void>(`/scenarios/${id}`, { method: 'DELETE' }),
  compareScenarios: (ids: string[]) => request<any>('/scenarios/compare', { method: 'POST', body: JSON.stringify({ scenario_ids: ids }) }),

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
}
