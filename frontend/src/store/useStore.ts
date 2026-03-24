// Store Zustand global — état de l'application Syléa.AI

import { create } from 'zustand'
import type { Profil, AnalyseDilemme, SousObjectif } from '../types'
import { api } from '../api/client'

interface SyleaStore {
  // Profil utilisateur
  profil: Profil | null
  setProfil: (p: Profil | null) => void

  // Analyse dilemme en cours (entre /analyser et /choisir)
  analyse: AnalyseDilemme | null
  setAnalyse: (a: AnalyseDilemme | null) => void

  // État de chargement global
  loading: boolean
  setLoading: (l: boolean) => void

  // Message d'erreur global
  error: string | null
  setError: (e: string | null) => void

  // Probabilité initiale déjà calculée ?
  probCalculee: boolean
  setProbCalculee: (v: boolean) => void

  // Sous-objectifs (partagés entre pages)
  sousObjectifs: SousObjectif[]
  setSousObjectifs: (so: SousObjectif[]) => void
  refreshSousObjectifs: () => Promise<void>

  // Unread agent proactive messages count
  unreadAgentMessages: number
  setUnreadAgentMessages: (n: number) => void
  incrementUnreadAgentMessages: () => void
  clearUnreadAgentMessages: () => void
}

export const useStore = create<SyleaStore>((set) => ({
  profil: null,
  setProfil: (p) => set({ profil: p }),

  analyse: null,
  setAnalyse: (a) => set({ analyse: a }),

  loading: false,
  setLoading: (l) => set({ loading: l }),

  error: null,
  setError: (e) => set({ error: e }),

  probCalculee: false,
  setProbCalculee: (v) => set({ probCalculee: v }),

  sousObjectifs: [],
  setSousObjectifs: (so) => set({ sousObjectifs: so }),
  refreshSousObjectifs: async () => {
    try {
      const so = await api.getSousObjectifs()
      set({ sousObjectifs: so })
    } catch {
      // Silently fail — sous-objectifs may not exist yet
    }
  },

  unreadAgentMessages: 0,
  setUnreadAgentMessages: (n) => set({ unreadAgentMessages: n }),
  incrementUnreadAgentMessages: () => set((s) => ({ unreadAgentMessages: s.unreadAgentMessages + 1 })),
  clearUnreadAgentMessages: () => set({ unreadAgentMessages: 0 }),
}))
